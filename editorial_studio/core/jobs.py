"""Command-only UI writes; lease ownership and completed steps survive restarts."""

from __future__ import annotations

import fcntl
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field

from editorial_studio.contracts.models import PaletteToken, ScenePatch, StrictModel
from editorial_studio.core.storage import Store, identifier, utcnow
from editorial_studio.creative.issue_models import IssueCorrection
from editorial_studio.llm.contracts import ModelRequest
from editorial_studio.photos.models import StoryInput
from editorial_studio.segmentation.models import SegmentPrompt


class ModelCommand(StrictModel):
    kind: Literal["model_call"] = "model_call"
    request: ModelRequest


class ReconcileCommand(StrictModel):
    kind: Literal["reconcile"] = "reconcile"
    call_id: str


class CreateProofCommand(StrictModel):
    kind: Literal["create_proof"] = "create_proof"
    scene_id: str


class PatchSceneCommand(StrictModel):
    kind: Literal["patch_scene"] = "patch_scene"
    patch: ScenePatch


class RollbackSceneCommand(StrictModel):
    kind: Literal["rollback_scene"] = "rollback_scene"
    scene_id: str
    expected_parent_version: str
    restored_version: str


class BuildIdentityCommand(StrictModel):
    kind: Literal["build_identity"] = "build_identity"
    pairing_id: str = "quiet-serif"
    reference_ids: list[str] | None = None
    photo_asset_id: str | None = None
    palette: list[PaletteToken] | None = None


class ReviewIdentityCommand(StrictModel):
    kind: Literal["review_identity"] = "review_identity"
    identity_id: str
    expected_revision: int = Field(ge=0)
    actor: str = Field(min_length=1)
    verdict: Literal["approved", "revision_required"]
    note: str = Field(min_length=1)


class IngestStoryCommand(StrictModel):
    kind: Literal["ingest_story"] = "ingest_story"
    story: StoryInput


class SegmentSubjectCommand(StrictModel):
    kind: Literal["segment_subject"] = "segment_subject"
    prompt: SegmentPrompt


class BuildCreativeSpreadCommand(StrictModel):
    kind: Literal["build_creative_spread"] = "build_creative_spread"
    story_id: str
    identity_id: str
    mandate: str = "Find the visual metaphor in the story."


class PackageFinalIdentityCommand(StrictModel):
    kind: Literal["package_final_identity"] = "package_final_identity"
    identity_id: str
    spread_ids: list[str] = Field(min_length=2, max_length=3)
    capability_proof_ids: list[str]


class ReviewFinalIdentityCommand(StrictModel):
    kind: Literal["review_final_identity"] = "review_final_identity"
    package_id: str
    expected_revision: int = Field(ge=0)
    actor: str = Field(min_length=1)
    note: str = Field(min_length=1)
    verdict: Literal["approved", "revision_required"]
    reviewed_techniques: bool
    override_critic_recommendations: bool = False


class BuildCapabilityProofsCommand(StrictModel):
    kind: Literal["build_capability_proofs"] = "build_capability_proofs"


class BuildTournamentCommand(StrictModel):
    kind: Literal["build_tournament"] = "build_tournament"
    story_id: str
    identity_id: str
    mandate: str = "Find the story's strongest visual expression."
    authored_reference_ids: list[str] = Field(default_factory=list, max_length=6)
    authored_reference_project: str = "m10a-references"


class BuildReferenceCompositionCommand(StrictModel):
    kind: Literal["build_reference_composition"] = "build_reference_composition"
    story_id: str
    identity_id: str
    reference_ids: list[str] = Field(min_length=1, max_length=12)
    reference_project: str = "m10a-references"
    art_director: bool = False


class BuildIssueCommand(StrictModel):
    kind: Literal["build_issue"] = "build_issue"
    story_ids: list[str] = Field(min_length=6, max_length=6)
    identity_id: str
    tournament_ids: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list, max_length=12)
    reference_project: str = "m10a-references"
    reference_art_director: bool = True
    prepared_composition_ids: list[str] = Field(default_factory=list, max_length=6)


class ReviseIssueCommand(StrictModel):
    kind: Literal["revise_issue"] = "revise_issue"
    issue_id: str
    expected_evidence_fingerprint: str
    corrections: list[IssueCorrection] = Field(min_length=1, max_length=6)


class ExportProductionCommand(StrictModel):
    kind: Literal["export_production"] = "export_production"
    issue_id: str
    expected_evidence_fingerprint: str


CommandPayload = Annotated[
    ModelCommand
    | ReconcileCommand
    | CreateProofCommand
    | PatchSceneCommand
    | RollbackSceneCommand
    | BuildIdentityCommand
    | ReviewIdentityCommand
    | IngestStoryCommand
    | SegmentSubjectCommand
    | BuildCreativeSpreadCommand
    | PackageFinalIdentityCommand
    | ReviewFinalIdentityCommand
    | BuildCapabilityProofsCommand
    | BuildTournamentCommand
    | BuildReferenceCompositionCommand
    | BuildIssueCommand
    | ReviseIssueCommand
    | ExportProductionCommand,
    Field(discriminator="kind"),
]


class Command(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: str
    payload: CommandPayload
    created_at: datetime = Field(default_factory=utcnow)


class Job(StrictModel):
    command: Command
    status: Literal["queued", "running", "completed", "failed", "needs_reconciliation"]
    worker_id: str | None = None
    lease_until: float | None = None
    error: str | None = None


class StepOutput(StrictModel):
    asset_ids: list[str] = Field(default_factory=list)
    call_id: str | None = None
    visible_text: str | None = None
    scene_id: str | None = None
    scene_version: str | None = None
    identity_id: str | None = None


class LeaseLost(RuntimeError):
    pass


class Queue:
    def __init__(self, store: Store):
        self.store = store

    def submit(self, command: Command):
        # This is the UI's sole write path. Its Store may be read-only.
        identifier(command.project_id)
        with sqlite3.connect(self.store.db_path, timeout=5) as db:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute(
                "INSERT INTO commands(id,project_id,payload,created_at) VALUES(?,?,?,?)",
                (
                    command.id,
                    command.project_id,
                    command.model_dump_json(),
                    command.created_at.isoformat(),
                ),
            )
        return command.id

    def list(self, project_id: str | None = None) -> list[Job]:
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT * FROM commands WHERE (? IS NULL OR project_id=?) ORDER BY created_at,id",
                (project_id, project_id),
            ).fetchall()
        return [
            Job(
                command=Command.model_validate_json(r["payload"]),
                status=r["status"],
                worker_id=r["worker_id"],
                lease_until=r["lease_until"],
                error=r["error"],
            )
            for r in rows
        ]

    def claim(self, worker_id: str, lease_seconds: int) -> Job | None:
        now = utcnow().timestamp()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM commands WHERE status='queued' OR "
                "(status='running' AND lease_until < ?) ORDER BY created_at LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE commands SET status='running',worker_id=?,lease_until=? WHERE id=?",
                (worker_id, now + lease_seconds, row["id"]),
            )
        return Job(
            command=Command.model_validate_json(row["payload"]),
            status="running",
            worker_id=worker_id,
            lease_until=now + lease_seconds,
        )

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int):
        now = utcnow().timestamp()
        with self.store.connection() as db:
            changed = db.execute(
                "UPDATE commands SET lease_until=? WHERE id=? AND worker_id=? "
                "AND status='running' AND lease_until>=?",
                (now + lease_seconds, job_id, worker_id, now),
            ).rowcount
        if changed != 1:
            raise LeaseLost("worker no longer owns the job lease")

    def step(self, job_id: str, name: str) -> StepOutput | None:
        with self.store.connection() as db:
            row = db.execute(
                "SELECT output FROM steps WHERE job_id=? AND step_name=?", (job_id, name)
            ).fetchone()
        return StepOutput.model_validate_json(row[0]) if row else None

    def commit_step(self, job_id: str, worker_id: str, name: str, output: StepOutput):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute(
                "SELECT worker_id,lease_until,status FROM commands WHERE id=?", (job_id,)
            ).fetchone()
            if (
                not owner
                or owner["worker_id"] != worker_id
                or owner["status"] != "running"
                or owner["lease_until"] < utcnow().timestamp()
            ):
                raise LeaseLost("cannot commit a step without a live lease")
            db.execute(
                "INSERT OR IGNORE INTO steps VALUES(?,?,?)",
                (job_id, name, output.model_dump_json()),
            )

    def finish(self, job_id: str, worker_id: str, *, status: str = "completed", error=None):
        if status not in {"completed", "failed", "needs_reconciliation"}:
            raise ValueError("invalid final job state")
        with self.store.connection() as db:
            changed = db.execute(
                "UPDATE commands SET status=?,error=?,lease_until=NULL "
                "WHERE id=? AND worker_id=? AND status='running' AND lease_until>=?",
                (status, error, job_id, worker_id, utcnow().timestamp()),
            ).rowcount
        if changed != 1:
            raise LeaseLost("cannot finish a job without a live lease")

    def resolve_job(self, job_id: str, project_id: str, output: StepOutput):
        """A retrieved authoritative response completes the original blocked job."""
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE commands SET status='completed',error=NULL WHERE id=? AND project_id=? "
                "AND status='needs_reconciliation'",
                (job_id, project_id),
            ).rowcount
            if changed:
                db.execute(
                    "INSERT OR IGNORE INTO steps VALUES(?,?,?)",
                    (job_id, "provider_call", output.model_dump_json()),
                )

    @contextmanager
    def lease(self, job: Job, lease_seconds: int, heartbeat_seconds: int):
        stop = threading.Event()
        failures = []

        def pulse():
            while not stop.wait(heartbeat_seconds):
                try:
                    self.heartbeat(job.command.id, job.worker_id, lease_seconds)
                except BaseException as error:
                    failures.append(error)
                    return

        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            yield
            if failures:
                raise failures[0]
        finally:
            stop.set()
            thread.join(timeout=2)


@contextmanager
def worker_lock(store: Store):
    # Process-level single writer. OS releases this lock after SIGKILL.
    with (store.root / ".worker.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another worker owns this data directory") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
