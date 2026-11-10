"""Build and export the M1 proof, reusing the real M0 image without another API call."""

from pathlib import Path
from uuid import uuid4

from editorial_studio.canvas.demo import proof_document
from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts.models import (
    DecisionEvent,
    ProviderCallRecord,
    ReviewDecision,
    WorkflowEvent,
)
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store, utcnow
from editorial_studio.llm.contracts import CallContext
from editorial_studio.settings import load_settings


def main():
    settings = load_settings()
    store = Store(settings.data_root)
    with worker_lock(store):
        project = "m1-proof"
        source = next(
            c
            for c in store.list("call", ProviderCallRecord, "m0-live")
            if c.status == "completed" and c.generated_artifact_ids and not c.cache_hit
        )
        asset = store.put_blob(
            project, store.read_blob("m0-live", source.generated_artifact_ids[0]), "image/png"
        )
        scene_id = "proof-" + uuid4().hex[:8]
        context = CallContext(
            project_id=project,
            run_id=uuid4().hex,
            agent_name="M1Proof",
            stage="M1",
            spread_id="proof-spread",
            parent_call_id=source.call_id,
        )
        document = proof_document(scene_id, asset.id)
        executor = Executor(SceneRepository(store, project), Renderer(store, project))
        version = executor.initialize(document, context, dpi=144)
        # This is a technical review only. Artistic criticism belongs to M7.
        decision = ReviewDecision(
            verdict="ACCEPT",
            execution_findings=[],
            artistic_findings=[],
            concept_fidelity_findings=[],
            rule_break_evaluations=[],
            target_edit_instructions=None,
        )
        decision_id = uuid4().hex
        event = WorkflowEvent(
            event_id=uuid4().hex,
            project_id=project,
            run_id=context.run_id,
            spread_id=context.spread_id,
            timestamp=utcnow(),
            payload=DecisionEvent(decision_id=decision_id, verdict="ACCEPT"),
        )
        store.put_records(
            ("technical_review", decision_id, project, decision),
            ("event", event.event_id, project, event),
        )
        target = Path("data/exports/m1-proof")
        target.mkdir(parents=True, exist_ok=True)
        for filename, asset_id in [
            ("spread.png", version.png_asset_id),
            ("spread.pdf", version.pdf_asset_id),
            ("scene.json", version.document_asset_id),
            ("render-metadata.json", version.metadata_asset_id),
        ]:
            (target / filename).write_bytes(store.read_blob(project, asset_id))
        print("Proof scene:", scene_id)
        print("PNG:", target / "spread.png")
        print("Vector PDF:", target / "spread.pdf")


if __name__ == "__main__":
    main()
