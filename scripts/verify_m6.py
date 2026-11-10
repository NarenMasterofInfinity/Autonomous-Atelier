"""One contextual gateway-generated motif, Potrace vectorization and saved integration proof."""

from pathlib import Path

from editorial_studio.artifacts.inspection import inspect_render
from editorial_studio.artifacts.service import build_artifact, integrate_artifact
from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts import models as m
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store, utcnow
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import load_settings
from editorial_studio.spatial.skills import rect
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    settings = load_settings()
    store = Store(settings.data_root)
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    context = CallContext(
        project_id="m6-proof",
        run_id="m6-contextual-motif",
        agent_name="ArtifactPlanner",
        stage="M6",
        spread_id="artifact-proof",
        prompt_version="m6-v1",
    )
    target = Path("data/exports/m6-proof")
    target.mkdir(parents=True, exist_ok=True)
    with worker_lock(store):
        repo = SceneRepository(store, context.project_id)
        executor = Executor(repo, Renderer(store, context.project_id))
        try:
            version = repo.head("artifact-proof")
        except KeyError:
            layers = [
                m.TextLayer(
                    id="title",
                    name="Headline",
                    semantic_role="headline",
                    z_index=0,
                    text_content="A line around\nthe ordinary",
                    style_name="headline",
                    bounds=m.BoundsMM(x_mm=25, y_mm=65, width_mm=170, height_mm=80),
                ),
                m.TextLayer(
                    id="body",
                    name="Story",
                    semantic_role="body",
                    z_index=0,
                    text_content="A small motif can carry the movement of a story. It responds to the surrounding space, then gives the reader a point of return. The source photograph and the publication palette guide its shape; the final mark remains an editable vector.",
                    style_name="body",
                    bounds=m.BoundsMM(x_mm=25, y_mm=175, width_mm=145, height_mm=80),
                ),
                m.VectorLayer(
                    id="target",
                    name="Motif region",
                    semantic_role="target",
                    z_index=0,
                    bounds=m.BoundsMM(x_mm=225, y_mm=55, width_mm=165, height_mm=180),
                    path=rect(225, 55, 165, 180),
                ),
            ]
            doc = CanvasDocument.from_scene(
                m.Scene(
                    id="artifact-proof",
                    spread_id="artifact-proof",
                    version="initial",
                    width_mm=420,
                    height_mm=297,
                    design_language_id="m6-proof",
                    created_at=utcnow(),
                    layers=layers,
                )
            )
            doc.background_color = "#f4f0e8"
            version = executor.initialize(doc, context)
        req = m.ArtifactRequest(
            id="orbit-mark",
            asset_type="vector",
            visual_role="one fluid orbit with an open center",
            generation_spec="A single elegant black curved loop or ribbon silhouette with a clearly open center on pure white. No shadows, no gradients, no letters. Keep a wide white margin.",
            target_region=m.NormalizedRegion(x=0.55, y=0.2, width=0.35, height=0.6),
            color_constraints=["#9e4d32", "#22211f"],
            preferred_generation_method="gpt-image-2",
            target_layer_dependency_id="target",
            integration_method="direct",
            output=m.VectorOutputSpec(),
            provenance_notes="Contextual generated acceptance motif, traced to editable paths.",
            visual_acceptance_checks=["open center", "simple silhouette", "no text"],
        )
        reference = next(v for v in repo.history("artifact-proof") if v.version == "initial")
        build = build_artifact(gateway, context, req, [reference.png_asset_id])
        version = integrate_artifact(store, context, executor, build, "artifact-proof")
        inspection = inspect_render(store, context, version.png_asset_id)
        for name, asset in [
            ("spread.png", version.png_asset_id),
            ("spread.pdf", version.pdf_asset_id),
            ("scene.json", version.document_asset_id),
            ("motif.png", build.raster_asset_id),
            ("motif.svg", build.output_asset_id),
            ("thumbnail.png", inspection.thumbnail_asset_id),
            ("crop.png", inspection.crop_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(context.project_id, asset))
        (target / "artifact.json").write_text(build.model_dump_json(indent=2))
        (target / "inspection.json").write_text(inspection.model_dump_json(indent=2))
        print(
            "M6 contextual image call:",
            build.provider_call_id,
            "traced IoU:",
            build.traced.reconstructed_iou,
            "proof:",
            target / "spread.pdf",
        )


if __name__ == "__main__":
    main()
