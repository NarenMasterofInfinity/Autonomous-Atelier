from uuid import uuid4

import pytest

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.art_direction.service import build_identity, review_identity
from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import SceneVersion
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts.models import PaletteToken, ScenePatch, SetOpacityOp
from editorial_studio.contracts.operation_registry import REGISTRY, RuntimePolicy
from editorial_studio.core.jobs import BuildIdentityCommand, Command, Queue, ReviewIdentityCommand
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.settings import Settings
from editorial_studio.worker import process_one


@pytest.fixture
def identity_context():
    return CallContext(
        project_id="project", run_id="identity-run", agent_name="Verifier", stage="M2"
    )


def test_provisional_identity_has_three_completed_proofs_and_no_invented_approval(
    store, identity_context
):
    identity = build_identity(store, identity_context, dpi=72)
    assert len(identity.proofs) == 3 and identity.review is None
    assert identity.bible.approval_state == "provisional"
    assert identity.bible.approved_visual_examples == []
    assert len(identity.capabilities) == 10 and all(
        c.verification_status == "planned" for c in identity.capabilities
    )
    assert all(p.report.unplaced_body_start is None for p in identity.proofs)
    assert store.get("identity", identity.id, ProvisionalIdentity) == identity


def test_finished_build_reuses_its_proofs_without_rerender(store, identity_context, monkeypatch):
    one = build_identity(store, identity_context, dpi=72)

    def fail(*args, **kwargs):
        raise AssertionError("finished proof was rendered twice")

    monkeypatch.setattr(Renderer, "render", fail)
    two = build_identity(store, identity_context, dpi=72)
    assert one == two and len(store.list("scene_version", SceneVersion, "project")) == 3


def test_interrupted_build_resumes_frozen_inputs_and_reuses_committed_proof(
    store, identity_context, monkeypatch
):
    original = Executor.initialize
    calls = []

    def interrupt(self, document, context, **kwargs):
        calls.append(document.scene.id)
        if len(calls) == 2:
            raise RuntimeError("simulated interruption before second proof commit")
        return original(self, document, context, **kwargs)

    monkeypatch.setattr(Executor, "initialize", interrupt)
    with pytest.raises(RuntimeError):
        build_identity(store, identity_context, dpi=72)
    assert len(store.list("scene_version", SceneVersion, "project")) == 1
    assert store.get("identity", identity_context.run_id, ProvisionalIdentity) is None
    result = build_identity(store, identity_context, pairing_id="direct-sans", dpi=72)
    assert result.pairing.id == "quiet-serif", "Recovery must use the original frozen build request"
    assert (
        len(result.proofs) == 3 and len(store.list("scene_version", SceneVersion, "project")) == 3
    )
    assert len(calls) == 4, "One interrupted attempt and exactly three successful scene commits"


def test_explicit_review_binds_proofs_and_stays_provisional(store, identity_context):
    identity = build_identity(store, identity_context, dpi=72)
    context = identity_context.model_copy(update={"run_id": "review-1"})
    reviewed = review_identity(
        store,
        context,
        identity.id,
        expected_revision=0,
        actor="Test reviewer",
        verdict="approved",
        note="Test fixture review only.",
    )
    assert reviewed.review.actor == "Test reviewer" and reviewed.review.verdict == "approved"
    assert reviewed.bible.approval_state == "provisional" and reviewed.revision == 1
    assert reviewed.bible.final_proof_spread_ids == []
    assert reviewed.bible.approved_visual_examples == reviewed.guidelines.reference_ids
    with pytest.raises(ValueError, match="stale"):
        review_identity(
            store,
            context,
            identity.id,
            expected_revision=0,
            actor="Reviewer",
            verdict="approved",
            note="stale",
        )


def test_revised_proof_invalidates_old_identity_review(store, identity_context):
    identity = build_identity(store, identity_context, dpi=72)
    proof = identity.proofs[0]
    repo = SceneRepository(store, "project")
    document = repo.load(proof.scene_id)
    ids = {layer.id for layer in document.scene.layers}
    policy = RuntimePolicy(
        readable_layer_ids=ids,
        writable_layer_ids=ids,
        allowed_operations=set(REGISTRY),
        renderer_operations=set(REGISTRY),
    )
    patch = ScenePatch(
        patch_id=uuid4().hex,
        target_scene_id=proof.scene_id,
        parent_version=proof.scene_version,
        operations=[SetOpacityOp(layer_id="headline", opacity=0.9)],
        modified_layer_ids=["headline"],
        declared_dependencies=["headline"],
    )
    Executor(repo, Renderer(store, "project")).apply(patch, policy, identity_context, dpi=72)
    with pytest.raises(ValueError, match="proof changed"):
        review_identity(
            store,
            identity_context.model_copy(update={"run_id": "review"}),
            identity.id,
            expected_revision=0,
            actor="Reviewer",
            verdict="approved",
            note="Review",
        )
    assert store.get("identity", identity.id, ProvisionalIdentity).review is None


def test_missing_proof_artifact_cannot_be_approved(store, identity_context):
    identity = build_identity(store, identity_context, dpi=72)
    (store.root / "project" / "blobs" / identity.proofs[0].metadata_asset_id).unlink()
    with pytest.raises(FileNotFoundError):
        review_identity(
            store,
            identity_context,
            identity.id,
            expected_revision=0,
            actor="Reviewer",
            verdict="approved",
            note="Review",
        )


def test_cross_project_identity_access_is_rejected(store, identity_context):
    identity = build_identity(store, identity_context, dpi=72)
    wrong = identity_context.model_copy(update={"project_id": "other"})
    with pytest.raises(PermissionError):
        build_identity(store, wrong, dpi=72)
    with pytest.raises(PermissionError):
        review_identity(
            store,
            wrong,
            identity.id,
            expected_revision=0,
            actor="Reviewer",
            verdict="approved",
            note="Review",
        )


def test_build_and_review_commands_do_not_call_provider(store, pricing, provider_factory):
    provider = provider_factory([])
    gateway = Gateway(store, provider, pricing)
    queue = Queue(store)
    command = Command(project_id="project", payload=BuildIdentityCommand())
    queue.submit(command)
    process_one(queue, gateway, "worker", Settings())
    assert queue.list()[0].status == "completed"
    identity = store.get("identity", command.id, ProvisionalIdentity)
    review = Command(
        project_id="project",
        payload=ReviewIdentityCommand(
            identity_id=identity.id,
            expected_revision=0,
            actor="Test reviewer",
            verdict="approved",
            note="Test review only.",
        ),
    )
    queue.submit(review)
    process_one(queue, gateway, "worker", Settings())
    assert all(job.status == "completed" for job in queue.list())
    assert store.get("identity", identity.id, ProvisionalIdentity).review.verdict == "approved"
    assert provider.calls == 0


def test_palette_choice_controls_executable_proofs(store, identity_context):
    colors = [
        PaletteToken(name=name, hex_color=color)
        for name, color in [
            ("paper", "#ffffff"),
            ("ink", "#102030"),
            ("muted", "#445566"),
            ("accent", "#cc3300"),
        ]
    ]
    identity = build_identity(store, identity_context, palette=colors, dpi=72)
    doc = SceneRepository(store, "project").load(identity.proofs[0].scene_id)
    assert doc.background_color == "#ffffff"
    body = next(style for style in doc.typography.styles if style.name.endswith(".body"))
    assert body.color == identity.guidelines.palette_roles["ink"] == "#102030"


def test_capability_matrix_never_promotes_quality_from_operation_availability():
    from editorial_studio.contracts.capability_matrix import capability_coverage

    all_operations = capability_coverage(set(REGISTRY))
    assert all(not item.missing_operations for item in all_operations)
    assert all(item.verification_status == "planned" for item in all_operations)
    none = capability_coverage(set())
    assert all(item.missing_operations for item in none)


def test_review_command_recovery_does_not_create_a_second_approval(
    store, pricing, provider_factory
):
    from editorial_studio.art_direction.models import IdentityReview
    from editorial_studio.worker import process_identity_command

    context = CallContext(
        project_id="project", run_id="recovery-identity", agent_name="Fixture", stage="M2"
    )
    identity = build_identity(store, context, dpi=72)
    gateway = Gateway(store, provider_factory([]), pricing)
    command = Command(
        project_id="project",
        payload=ReviewIdentityCommand(
            identity_id=identity.id,
            expected_revision=0,
            actor="Test reviewer",
            verdict="approved",
            note="Test recovery only.",
        ),
    )
    first = process_identity_command(gateway, command)
    second = process_identity_command(gateway, command)
    assert first == second
    assert len(store.list("identity_review", IdentityReview, "project")) == 1
    assert store.get("identity", identity.id, ProvisionalIdentity).revision == 1


def test_identity_proof_book_contains_three_vector_spreads(store, identity_context):
    import pymupdf

    identity = build_identity(store, identity_context, dpi=72)
    book = pymupdf.open(
        stream=store.read_blob("project", identity.proof_book_asset_id), filetype="pdf"
    )
    assert len(book) == 3
    for page in book:
        assert page.rect.width == pytest.approx(420 * 72 / 25.4, abs=0.001)
        assert page.get_fonts() and page.get_text()
    assert identity.contact_sheet_asset_id


def test_review_transaction_rechecks_proof_heads_after_asset_validation(
    store, identity_context, monkeypatch
):
    from editorial_studio.art_direction.service import identity_assets

    identity = build_identity(store, identity_context, dpi=72)
    original_read = store.read_blob
    last = identity_assets(identity)[-1]
    changed = []

    def race(project, asset):
        data = original_read(project, asset)
        if not changed and asset == last:
            changed.append(True)
            proof = identity.proofs[0]
            repo = SceneRepository(store, "project")
            doc = repo.load(proof.scene_id)
            ids = {layer.id for layer in doc.scene.layers}
            policy = RuntimePolicy(
                readable_layer_ids=ids,
                writable_layer_ids=ids,
                allowed_operations=set(REGISTRY),
                renderer_operations=set(REGISTRY),
            )
            patch = ScenePatch(
                patch_id=uuid4().hex,
                target_scene_id=proof.scene_id,
                parent_version=proof.scene_version,
                operations=[SetOpacityOp(layer_id="headline", opacity=0.8)],
                modified_layer_ids=["headline"],
                declared_dependencies=["headline"],
            )
            Executor(repo, Renderer(store, "project")).apply(
                patch, policy, identity_context, dpi=72
            )
        return data

    monkeypatch.setattr(store, "read_blob", race)
    with pytest.raises(ValueError, match="proof changed during review"):
        review_identity(
            store,
            identity_context.model_copy(update={"run_id": "racing-review"}),
            identity.id,
            expected_revision=0,
            actor="Reviewer",
            verdict="approved",
            note="Race fixture",
        )
    assert changed and store.get("identity", identity.id, ProvisionalIdentity).review is None


def test_recovery_keeps_checkpointed_resolution(store, identity_context, monkeypatch):
    from editorial_studio.canvas.models import RenderMetadata

    original = Executor.initialize
    calls = []

    def interrupt(self, document, context, **kwargs):
        calls.append(document.scene.id)
        if len(calls) == 2:
            raise RuntimeError("interrupt")
        return original(self, document, context, **kwargs)

    monkeypatch.setattr(Executor, "initialize", interrupt)
    with pytest.raises(RuntimeError):
        build_identity(store, identity_context, dpi=72)
    identity = build_identity(store, identity_context, dpi=144)
    for proof in identity.proofs:
        metadata = RenderMetadata.model_validate_json(
            store.read_blob("project", proof.metadata_asset_id)
        )
        assert metadata.dpi == 72
