"""Real MobileSAM inference, alpha diagnostics and a committed depth-typography proof."""

from pathlib import Path

from editorial_studio.contracts.models import NormalizedPoint, NormalizedRegion
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import CallContext
from editorial_studio.photos.pipeline import decode, png
from editorial_studio.segmentation.models import SegmentPrompt
from editorial_studio.segmentation.proof import depth_proof
from editorial_studio.segmentation.service import segment
from editorial_studio.settings import load_settings


def main():
    store = Store(load_settings().data_root)
    context = CallContext(
        project_id="m4-proof",
        run_id="m4-live-astronaut",
        agent_name="SegmentationProof",
        stage="M4",
    )
    target = Path("data/exports/m4-proof")
    target.mkdir(parents=True, exist_ok=True)
    with worker_lock(store):
        source = store.put_blob(
            context.project_id,
            png(decode(Path("data/fixtures/photos/astronaut.png").read_bytes())),
            "image/png",
        )
        prompt = SegmentPrompt(
            source_asset_id=source.id,
            box=NormalizedRegion(x=0.05, y=0.02, width=0.90, height=0.98),
            points=[NormalizedPoint(x=0.42, y=0.4)],
            labels=[1],
        )
        result = segment(store, context, prompt)
        assert result.quality.passed
        from editorial_studio.canvas.repository import SceneRepository

        try:
            version = SceneRepository(store, context.project_id).head("depth-proof")
        except KeyError:
            version = depth_proof(store, context, result)
        for name, asset in [
            ("cutout.png", result.cutout_asset_id),
            ("alpha.png", result.alpha_asset_id),
            ("spread.png", version.png_asset_id),
            ("spread.pdf", version.pdf_asset_id),
            ("scene.json", version.document_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(context.project_id, asset))
        (target / "segmentation.json").write_text(result.model_dump_json(indent=2))
    print("MobileSAM:", result.backend, "predicted IoU:", result.predicted_iou)
    print("Edge diagnostics:", result.quality.model_dump())
    print("Depth proof:", target / "spread.pdf", "human visual review remains required")


if __name__ == "__main__":
    main()
