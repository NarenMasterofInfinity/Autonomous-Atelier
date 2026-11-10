"""Rendered technique evidence is technical until an explicit visual/artistic review is recorded."""

from pydantic import Field

from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts import models as m
from editorial_studio.contracts.capability_matrix import CAPABILITIES
from editorial_studio.core.storage import utcnow
from editorial_studio.spatial.assistant import SpatialAssistant
from editorial_studio.spatial.skills import fixture_assets, technique_operations


class CapabilityProof(m.StrictModel):
    id: str
    capability_id: str
    project_id: str
    scene_id: str
    scene_version: str
    operation_names: list[str]
    png_asset_id: str
    pdf_asset_id: str
    document_asset_id: str
    metadata_asset_id: str
    thumbnail_asset_id: str
    crop_asset_id: str
    status: str = Field(
        default="technically_verified",
        pattern="^(technically_verified|visually_reviewed|artistically_verified)$",
    )
    reviewer: str | None = None
    review_note: str | None = None


def build_capability_proofs(store, context, *, dpi=144):
    from io import BytesIO

    from PIL import Image

    from editorial_studio.photos.pipeline import png

    repo = SceneRepository(store, context.project_id)
    executor = Executor(repo, Renderer(store, context.project_id))
    assistant = SpatialAssistant(executor)
    photo, mask = fixture_assets(store, context.project_id)
    proofs = []
    for capability in CAPABILITIES:
        record_id = context.run_id + "-" + capability.id
        old = store.get("capability_proof", record_id, CapabilityProof)
        if old:
            for asset in [
                old.png_asset_id,
                old.pdf_asset_id,
                old.document_asset_id,
                old.metadata_asset_id,
                old.thumbnail_asset_id,
                old.crop_asset_id,
            ]:
                store.read_blob(context.project_id, asset)
            proofs.append(old)
            continue
        scene_id = record_id
        ctx = context.model_copy(update={"spread_id": scene_id})
        try:
            version = repo.head(scene_id)
        except KeyError:
            doc = CanvasDocument.from_scene(
                m.Scene(
                    id=scene_id,
                    spread_id=scene_id,
                    version="initial",
                    width_mm=420,
                    height_mm=297,
                    design_language_id="m5-technique-proof",
                    created_at=utcnow(),
                )
            )
            doc.background_color = "#f4f0e8"
            version = executor.initialize(doc, ctx, dpi=dpi)
        operations = technique_operations(capability.id, photo, mask)
        if not set(capability.operation_names) <= {op.op for op in operations}:
            raise ValueError("technique proof does not exercise its required operations")
        if version.version == "initial":
            version = assistant.apply(operations, scene_id, ctx, dpi=dpi)
        else:
            patch = (
                store.get("scene_patch", version.patch_id, m.ScenePatch)
                if version.patch_id
                else None
            )
            if version.run_id != context.run_id or patch is None or patch.operations != operations:
                raise ValueError(
                    "existing scene does not prove the expected capability operation batch"
                )
        metadata = RenderMetadata.model_validate_json(
            store.read_blob(context.project_id, version.metadata_asset_id)
        )
        if any(item.result.overflow_start_char is not None for item in metadata.text_layouts):
            raise ValueError("proof has unplaced copy")
        image = Image.open(BytesIO(store.read_blob(context.project_id, version.png_asset_id)))
        thumb = image.copy()
        thumb.thumbnail((600, 420))
        x = round(30 * dpi / 25.4)
        y = round(60 * dpi / 25.4)
        thumb_asset = store.put_blob(context.project_id, png(thumb), "image/png")
        crop_asset = store.put_blob(
            context.project_id,
            png(image.crop((x, y, min(x + 700, image.width), min(y + 500, image.height)))),
            "image/png",
        )
        result = CapabilityProof(
            id=record_id,
            capability_id=capability.id,
            project_id=context.project_id,
            scene_id=scene_id,
            scene_version=version.version,
            operation_names=sorted({op.op for op in operations}),
            png_asset_id=version.png_asset_id,
            pdf_asset_id=version.pdf_asset_id,
            document_asset_id=version.document_asset_id,
            metadata_asset_id=version.metadata_asset_id,
            thumbnail_asset_id=thumb_asset.id,
            crop_asset_id=crop_asset.id,
        )
        store.put_records(("capability_proof", result.id, context.project_id, result))
        proofs.append(result)
    return proofs


def build_subject_flow_proof(store, context, cutout_asset_id):
    """Place full reading copy around a real isolated subject, using its actual crop mapping."""
    from editorial_studio.segmentation.geometry import silhouette_path
    from editorial_studio.spatial.skills import BODY, rect

    scene_id = context.run_id + "-subject-flow"
    repo = SceneRepository(store, context.project_id)
    try:
        return repo.head(scene_id)
    except KeyError:
        pass
    executor = Executor(repo, Renderer(store, context.project_id))
    assistant = SpatialAssistant(executor)
    doc = CanvasDocument.from_scene(
        m.Scene(
            id=scene_id,
            spread_id=scene_id,
            version="initial",
            width_mm=420,
            height_mm=297,
            design_language_id="m5-real-silhouette",
            created_at=utcnow(),
        )
    )
    doc.background_color = "#f4f0e8"
    executor.initialize(doc, context)
    frame = m.BoundsMM(x_mm=75, y_mm=105, width_mm=70, height_mm=120)
    exclusion = silhouette_path(store, context.project_id, cutout_asset_id, frame)
    operations = [
        m.FlowTextIntoShapeOp(
            layer_id="reading",
            text_content=BODY * 5,
            style_name="body",
            boundary=rect(20, 50, 180, 220),
            exclusion_paths=[exclusion],
        ),
        m.AddImageOp(layer_id="subject", asset_id=cutout_asset_id, bounds=frame),
        m.SetZIndexOp(layer_id="subject", z_index=1),
        m.AddTextOp(
            layer_id="headline",
            text_content="Around a\nhuman silhouette",
            style_name="headline",
            bounds=m.BoundsMM(x_mm=225, y_mm=70, width_mm=175, height_mm=85),
        ),
    ]
    return assistant.apply(operations, scene_id, context)
