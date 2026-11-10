"""A saved source photograph, headline and matching foreground cutout demonstrate depth."""

from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import RuntimePolicy
from editorial_studio.core.storage import utcnow


def depth_proof(store, context, result, scene_id="depth-proof"):
    executor = Executor(
        SceneRepository(store, context.project_id), Renderer(store, context.project_id)
    )
    doc = CanvasDocument.from_scene(
        m.Scene(
            id=scene_id,
            spread_id=scene_id,
            version="initial",
            width_mm=420,
            height_mm=297,
            design_language_id="segmentation-proof",
            created_at=utcnow(),
        )
    )
    executor.initialize(doc, context, dpi=144)
    b = m.BoundsMM(x_mm=0, y_mm=0, width_mm=420, height_mm=297)
    patch = m.ScenePatch(
        patch_id=context.run_id + "-depth",
        parent_version="initial",
        target_scene_id=scene_id,
        operations=[
            m.AddImageOp(layer_id="background", asset_id=result.source_asset_id, bounds=b),
            m.AddTextOp(
                layer_id="headline",
                text_content="INTO THE LIGHT",
                style_name="headline",
                bounds=m.BoundsMM(x_mm=22, y_mm=45, width_mm=376, height_mm=65),
            ),
            m.AddImageOp(layer_id="foreground", asset_id=result.cutout_asset_id, bounds=b),
            m.SetZIndexOp(layer_id="headline", z_index=1),
            m.SetZIndexOp(layer_id="foreground", z_index=2),
        ],
        created_layer_ids=["background", "headline", "foreground"],
        declared_dependencies=sorted({result.source_asset_id, result.cutout_asset_id}),
    )
    policy = RuntimePolicy(
        readable_layer_ids=set(),
        writable_layer_ids=set(),
        asset_ids={result.source_asset_id, result.cutout_asset_id},
        style_names={"headline"},
        allowed_operations=executor.supported_operations,
        renderer_operations=executor.supported_operations,
    )
    return executor.apply(patch, policy, context, dpi=144)
