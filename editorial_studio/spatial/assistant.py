"""Typed spatial operations, source-retaining text masks, and exact patch access declarations."""

from uuid import uuid4

from editorial_studio.canvas.models import LayerPresentation
from editorial_studio.canvas.typography.advanced import AdvancedTypography
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import (
    REGISTRY,
    OperationAccess,
    RuntimePolicy,
    Validator,
)


class SpatialAssistant:
    def __init__(self, executor):
        self.executor = executor

    def policy(self, document, *, skill_id=None):
        ids = {item.id for item in document.scene.layers}
        store = self.executor.repository.store
        project = self.executor.repository.project_id
        assets = store.assets(project)
        from editorial_studio.contracts.models import DerivedText

        return RuntimePolicy(
            skill_id=skill_id,
            readable_layer_ids=ids,
            writable_layer_ids=ids,
            asset_ids={a.id for a in assets},
            mask_asset_ids={a.id for a in assets if a.media_type.startswith("image/")},
            derived_text_ids={d.id for d in store.list("derived_text", DerivedText, project)},
            style_names={s.name for s in document.typography.styles}
            if document.typography
            else set(self.executor.renderer.typography.fonts.styles),
            allowed_operations=self.executor.supported_operations,
            renderer_operations=self.executor.supported_operations,
        )

    def patch(self, document, operations, *, skill_id=None):
        policy = self.policy(document, skill_id=skill_id)
        validator = Validator(document.scene, policy)
        total = OperationAccess()
        for op in operations:
            definition = REGISTRY[op.op]
            access = getattr(validator, definition.handler)(
                definition.model.model_validate(op.model_dump())
            )
            for name in ("created", "read", "written", "assets"):
                getattr(total, name).update(getattr(access, name))
        patch = m.ScenePatch(
            patch_id=uuid4().hex,
            parent_version=document.scene.version,
            target_scene_id=document.scene.id,
            operations=operations,
            created_layer_ids=sorted(total.created),
            modified_layer_ids=sorted(total.written - total.created),
            declared_dependencies=sorted((total.read - total.created) | total.assets),
        )
        return patch, policy

    def apply(self, operations, scene_id, context, *, skill_id=None, dpi=144):
        document = self.executor.repository.load(scene_id)
        patch, policy = self.patch(document, operations, skill_id=skill_id)
        from editorial_studio.telemetry.tools import tool_span

        with tool_span(self.executor.repository.store, context, "execute_spatial_recipe") as tool:
            version = self.executor.apply(patch, policy, context, dpi=dpi)
            tool.output_asset_ids.extend(
                [
                    version.document_asset_id,
                    version.png_asset_id,
                    version.pdf_asset_id,
                    version.metadata_asset_id,
                ]
            )
            return version

    def solve(self, intent, scene_id, context, *, dpi=144):
        from editorial_studio.spatial.anchors import anchor_operations

        document = self.executor.repository.load(scene_id)
        operations = anchor_operations(
            {layer.id: layer for layer in document.scene.layers},
            intent,
            self.executor.repository.store,
            self.executor.repository.project_id,
            width_mm=document.scene.width_mm,
            height_mm=document.scene.height_mm,
        )
        if not operations:
            return self.executor.repository.head(scene_id)
        return self.apply(operations, scene_id, context, dpi=dpi)

    @staticmethod
    def text_mask(layer: m.TextLayer, engine: TypographyEngine | None = None) -> m.PathGeometry:
        advanced = AdvancedTypography(engine or TypographyEngine())
        p = LayerPresentation(layer_id=layer.id, source_bounds=layer.bounds, outline_text=True)
        report, glyphs = advanced.layout(layer, p)
        if report.result.overflow_start_char is not None:
            raise ValueError("cannot create a mask from overflowing text")
        commands = [cmd for g in glyphs if g.path for cmd in g.path.commands]
        if not commands:
            raise ValueError("text has no visible glyph outlines")
        return m.PathGeometry(commands=commands)
