import os
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from editorial_studio.contracts.models import ProviderCallRecord, ToolExecutionRecord
from editorial_studio.core.jobs import (
    Command,
    LeaseLost,
    ModelCommand,
    Queue,
    StepOutput,
    worker_lock,
)
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import TextRequest
from editorial_studio.llm.gateway import Gateway
from editorial_studio.settings import Settings
from editorial_studio.telemetry.tools import tool_span
from editorial_studio.worker import process_one


def command():
    return Command(
        project_id="project",
        payload=ModelCommand(
            request=TextRequest(
                model="gpt-6-luna", prompt="Test", reasoning_effort="medium", max_output_tokens=512
            )
        ),
    )


def test_sqlite_is_wal_and_readonly_viewer_cannot_mutate(store):
    with store.connection() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    viewer = Store(store.root, readonly=True)
    with pytest.raises(PermissionError):
        viewer.put_blob("project", b"no", "text/plain")
    with viewer.connection() as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM records")
    Queue(viewer).submit(command())
    assert len(Queue(store).list()) == 1


def test_content_addressed_assets_are_immutable_and_project_scoped(store):
    first = store.put_blob("project", b"asset", "text/plain")
    second = store.put_blob("project", b"asset", "text/plain")
    assert first == second and len(store.assets("project")) == 1
    assert store.read_blob("project", first.id) == b"asset"
    with pytest.raises(KeyError):
        store.read_blob("other", first.id)
    with pytest.raises(ValueError):
        store.put_blob("../escape", b"asset", "text/plain")


def test_atomic_write_fsyncs_before_rename(store, monkeypatch):
    events = []
    original_sync, original_replace = os.fsync, os.replace

    def sync(fd):
        events.append("fsync")
        return original_sync(fd)

    def replace(a, b):
        assert events and events[-1] == "fsync"
        events.append("rename")
        return original_replace(a, b)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    store.put_blob("project", b"durable", "text/plain")
    assert events == ["fsync", "rename", "fsync"]


def test_failed_rename_does_not_publish_an_asset(store, monkeypatch):
    def broken(*args):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        store.put_blob("project", b"partial", "text/plain")
    assert store.assets("project") == []
    assert list((store.root / "project" / "blobs").iterdir()) == []


def test_startup_reconciliation_finds_missing_corrupt_and_orphan_files(store):
    missing = store.put_blob("project", b"missing", "text/plain")
    corrupt = store.put_blob("project", b"original", "text/plain")
    folder = store.root / "project" / "blobs"
    (folder / missing.sha256).unlink()
    (folder / corrupt.sha256).write_bytes(b"corrupted")
    (folder / "orphan").write_bytes(b"orphan")
    (folder / ".pending-abandoned").write_bytes(b"partial")
    report = store.reconcile()
    assert report.missing_asset_ids == [missing.id]
    assert report.corrupt_asset_ids == [corrupt.id]
    assert len(report.quarantined_paths) == 2
    assert not (folder / "orphan").exists()
    with pytest.raises(ValueError, match="hash mismatch"):
        store.read_blob("project", corrupt.id)


def test_only_one_worker_can_own_data_directory(store):
    with worker_lock(store):
        with pytest.raises(RuntimeError, match="another worker"):
            with worker_lock(store):
                pass


def test_lease_ownership_heartbeat_and_expiry(store):
    queue = Queue(store)
    cmd = command()
    queue.submit(cmd)
    assert queue.claim("first", 60).worker_id == "first"
    assert queue.claim("second", 60) is None
    queue.heartbeat(cmd.id, "first", 60)
    with pytest.raises(LeaseLost):
        queue.commit_step(cmd.id, "second", "step", StepOutput())
    with store.connection() as db:
        db.execute("UPDATE commands SET lease_until=0 WHERE id=?", (cmd.id,))
    with pytest.raises(LeaseLost):
        queue.finish(cmd.id, "first")
    assert queue.claim("second", 60).worker_id == "second"
    with pytest.raises(LeaseLost):
        queue.heartbeat(cmd.id, "first", 60)


def test_worker_process_killed_after_step_resumes_without_repeating_it(
    store, pricing, provider_factory, text_result
):
    queue = Queue(store)
    cmd = command()
    queue.submit(cmd)
    # A real child commits a durable step and is then SIGKILLed before finishing.
    script = """
from pathlib import Path
import sys,time
from editorial_studio.core.storage import Store
from editorial_studio.core.jobs import Queue,StepOutput,worker_lock
s=Store(Path(sys.argv[1])); q=Queue(s)
with worker_lock(s):
 job=q.claim('killed-worker',1)
 q.commit_step(job.command.id,'killed-worker','provider_call',StepOutput(visible_text='saved'))
 print('committed',flush=True)
 time.sleep(60)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(store.root)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "committed"
        process.kill()
        process.wait(timeout=5)
        assert process.returncode == -signal.SIGKILL
        time.sleep(1.05)
        provider = provider_factory([text_result])
        with worker_lock(store):
            assert process_one(queue, Gateway(store, provider, pricing), "new-worker", Settings())
        assert provider.calls == 0
        assert queue.list()[0].status == "completed"
        assert queue.step(cmd.id, "provider_call").visible_text == "saved"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_worker_runs_provider_step_once_and_finishes(store, pricing, provider_factory, text_result):
    queue = Queue(store)
    cmd = command()
    queue.submit(cmd)
    provider = provider_factory([text_result])
    gateway = Gateway(store, provider, pricing)
    assert process_one(queue, gateway, "worker", Settings())
    assert queue.list()[0].status == "completed"
    assert queue.step(cmd.id, "provider_call").call_id
    assert not process_one(queue, gateway, "worker", Settings())
    assert provider.calls == 1


def test_local_tool_is_timed_and_correlated_without_a_billable_call(store, context):
    with tool_span(store, context, "fixture_transform") as tool:
        tool.output_asset_ids.append(store.put_blob("project", b"result", "text/plain").id)
    records = store.list("tool", ToolExecutionRecord)
    assert len(records) == 1
    assert records[0].run_id == context.run_id and records[0].elapsed_ms >= 0
    assert records[0].status == "completed" and records[0].output_asset_ids
    assert store.list("call", ProviderCallRecord) == []


def test_failed_tool_is_logged(store, context):
    with pytest.raises(ValueError):
        with tool_span(store, context, "broken"):
            raise ValueError("bad input")
    tool = store.list("tool", ToolExecutionRecord)[0]
    assert tool.status == "failed" and tool.error_summary == "bad input"


def test_retrieval_completes_the_original_blocked_job(
    store, pricing, provider_factory, text_result
):
    from editorial_studio.core.jobs import ReconcileCommand
    from editorial_studio.llm.contracts import ProgressUpdate, ProviderFailure

    queue = Queue(store)
    original = command()
    queue.submit(original)
    provider = provider_factory([ProviderFailure("lost stream", ambiguous=True)])
    provider.on_execute = lambda req, progress: progress(ProgressUpdate(response_id="resp_1"))
    gateway = Gateway(store, provider, pricing)
    process_one(queue, gateway, "worker", Settings())
    assert queue.list()[0].status == "needs_reconciliation"
    call = store.list("call", ProviderCallRecord)[0]
    provider.recovered = text_result
    recovery = Command(project_id="project", payload=ReconcileCommand(call_id=call.call_id))
    queue.submit(recovery)
    process_one(queue, gateway, "worker", Settings())
    assert all(job.status == "completed" for job in queue.list())
    assert queue.step(original.id, "provider_call").call_id == call.call_id
    assert provider.calls == provider.retrievals == 1


def test_recovery_does_not_approve_missing_committed_assets(store, pricing, provider_factory):
    queue = Queue(store)
    cmd = command()
    queue.submit(cmd)
    queue.claim("old-worker", 60)
    asset = store.put_blob("project", b"committed-artifact", "text/plain")
    queue.commit_step(cmd.id, "old-worker", "provider_call", StepOutput(asset_ids=[asset.id]))
    (store.root / "project" / "blobs" / asset.id).unlink()
    with store.connection() as db:
        db.execute("UPDATE commands SET lease_until=0 WHERE id=?", (cmd.id,))
    provider = provider_factory([])
    process_one(queue, Gateway(store, provider, pricing), "new-worker", Settings())
    assert queue.list()[0].status == "failed" and provider.calls == 0


def test_killed_canvas_worker_resumes_committed_scene_without_rendering_twice(
    store, pricing, provider_factory, monkeypatch
):
    from editorial_studio.canvas.models import SceneVersion
    from editorial_studio.canvas.renderer import Renderer
    from editorial_studio.core.jobs import CreateProofCommand

    queue = Queue(store)
    cmd = Command(project_id="project", payload=CreateProofCommand(scene_id="crash-proof"))
    queue.submit(cmd)
    script = """
from pathlib import Path
import sys,time
from types import SimpleNamespace
from editorial_studio.core.jobs import Queue,worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.worker import process_canvas_command
store=Store(Path(sys.argv[1]));queue=Queue(store)
with worker_lock(store):
 job=queue.claim('killed-worker',1)
 process_canvas_command(queue,SimpleNamespace(store=store),job.command)
 print('scene committed',flush=True)
 time.sleep(60)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(store.root)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "scene committed"
        process.kill()
        process.wait(timeout=5)
        assert process.returncode == -signal.SIGKILL
        time.sleep(1.05)
        before = store.list("scene_version", SceneVersion, "project")

        def fail(*args, **kwargs):
            raise AssertionError("Committed scene must not be rendered again")

        monkeypatch.setattr(Renderer, "render", fail)
        provider = provider_factory([])
        with worker_lock(store):
            process_one(queue, Gateway(store, provider, pricing), "restarted-worker", Settings())
        assert queue.list()[0].status == "completed"
        assert len(store.list("scene_version", SceneVersion, "project")) == len(before) == 1
        assert queue.step(cmd.id, "canvas_operation").scene_id == "crash-proof"
        assert provider.calls == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_canvas_commands_create_edit_and_restore_without_provider_calls(
    store, pricing, provider_factory
):
    from uuid import uuid4

    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.contracts.models import ScenePatch, SetOpacityOp
    from editorial_studio.core.jobs import (
        CreateProofCommand,
        PatchSceneCommand,
        RollbackSceneCommand,
    )

    queue = Queue(store)
    provider = provider_factory([])
    gateway = Gateway(store, provider, pricing)
    first = Command(project_id="project", payload=CreateProofCommand(scene_id="interactive"))
    queue.submit(first)
    process_one(queue, gateway, "worker", Settings())
    repo = SceneRepository(store, "project")
    original = repo.head("interactive")
    patch = ScenePatch(
        patch_id=uuid4().hex,
        target_scene_id="interactive",
        parent_version=original.version,
        operations=[SetOpacityOp(layer_id="headline", opacity=0.4)],
        modified_layer_ids=["headline"],
        declared_dependencies=["headline"],
    )
    second = Command(project_id="project", payload=PatchSceneCommand(patch=patch))
    queue.submit(second)
    process_one(queue, gateway, "worker", Settings())
    changed = repo.head("interactive")
    assert (
        next(
            layer for layer in repo.load("interactive").scene.layers if layer.id == "headline"
        ).opacity
        == 0.4
    )
    third = Command(
        project_id="project",
        payload=RollbackSceneCommand(
            scene_id="interactive",
            expected_parent_version=changed.version,
            restored_version=original.version,
        ),
    )
    queue.submit(third)
    process_one(queue, gateway, "worker", Settings())
    assert all(job.status == "completed" for job in queue.list())
    assert (
        next(
            layer for layer in repo.load("interactive").scene.layers if layer.id == "headline"
        ).opacity
        == 1
    )
    assert len(repo.history("interactive")) == 3 and provider.calls == 0


def test_canvas_recovery_checks_metadata_before_accepting_committed_output(
    store, pricing, provider_factory
):
    from editorial_studio.canvas.models import SceneVersion
    from editorial_studio.core.jobs import CreateProofCommand
    from editorial_studio.worker import process_canvas_command

    queue = Queue(store)
    provider = provider_factory([])
    gateway = Gateway(store, provider, pricing)
    command = Command(project_id="project", payload=CreateProofCommand(scene_id="metadata-proof"))
    queue.submit(command)
    job = queue.claim("old-worker", 60)
    process_canvas_command(queue, gateway, job.command)
    version = store.list("scene_version", SceneVersion, "project")[0]
    (store.root / "project" / "blobs" / version.metadata_asset_id).unlink()
    with store.connection() as db:
        db.execute("UPDATE commands SET lease_until=0 WHERE id=?", (command.id,))
    process_one(queue, gateway, "new-worker", Settings())
    assert queue.list()[0].status == "failed" and provider.calls == 0
    assert len(store.list("scene_version", SceneVersion, "project")) == 1
