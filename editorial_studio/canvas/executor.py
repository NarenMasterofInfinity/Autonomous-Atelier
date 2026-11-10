"""Execute only registry-defined operations supported by M1; render before publishing."""

from uuid import uuid4

from editorial_studio.canvas import geometry
from editorial_studio.canvas.models import CanvasDocument, LayerPresentation
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository, SnapshotRollback
from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import (
    REGISTRY,
    RuntimePolicy,
    group_bounds,
    path_bounds,
    validate_patch,
)
from editorial_studio.llm.contracts import CallContext
from editorial_studio.telemetry.tools import tool_span


class Executor:
    def __init__(self, repository: SceneRepository, renderer: Renderer):
        if repository.project_id != renderer.project_id:
            raise PermissionError("renderer project mismatch")
        self.repository, self.renderer = repository, renderer

    @property
    def supported_operations(self):
        return {
            name
            for name, definition in REGISTRY.items()
            if name in self.renderer.supported_operations and hasattr(self, definition.handler)
        }

    def initialize(self, document: CanvasDocument, context: CallContext, *, dpi=144):
        if document.scene.parent_version is not None:
            raise ValueError("initial scene cannot have a parent")
        return self._render_commit(document, context, expected_parent=None, dpi=dpi)

    def _render_commit(
        self, document, context, *, expected_parent, patch=None, rollback=None, dpi=144
    ):
        with tool_span(self.repository.store, context, "render_scene") as tool:
            rendered = self.renderer.render(document, dpi=dpi, strict=True)
            version = self.repository.commit(
                document,
                rendered,
                context,
                expected_parent=expected_parent,
                patch=patch,
                rollback=rollback,
            )
            tool.output_asset_ids.extend(
                [
                    version.document_asset_id,
                    version.png_asset_id,
                    version.pdf_asset_id,
                    version.metadata_asset_id,
                ]
            )
        return version

    def apply(self, patch: m.ScenePatch, policy: RuntimePolicy, context: CallContext, *, dpi=144):
        original = self.repository.load(patch.target_scene_id)
        # A caller cannot claim support on behalf of the renderer.
        policy = policy.model_copy(
            update={"renderer_operations": policy.renderer_operations & self.supported_operations}
        )
        validate_patch(original.scene, patch, policy)
        current = self.repository.head(patch.target_scene_id)
        if patch.snapshot_asset_id and patch.snapshot_asset_id != current.document_asset_id:
            raise ValueError("patch snapshot does not match the parent document")
        candidate = original.model_copy(deep=True)
        layers = {layer.id: layer for layer in candidate.scene.layers}
        presentations = {p.layer_id: p for p in candidate.presentations}
        # Reuse the same model registry/handler names as validation; no competing parameter dispatch table.
        for op in patch.operations:
            typed = REGISTRY[op.op].model.model_validate(op.model_dump())
            getattr(self, REGISTRY[op.op].handler)(typed, layers, presentations)
            if op.op in {
                "transform_layer",
                "add_image",
                "add_text",
                "add_path",
                "edit_path",
                "create_group",
                "boolean_path",
                "text_on_path",
                "flow_text_into_shape",
            }:
                self._refresh_groups(layers, presentations)
        candidate.scene.layers = list(layers.values())
        candidate.presentations = list(presentations.values())
        for layer in candidate.scene.layers:
            if layer.id in patch.created_layer_ids:
                layer.owner_skill_id = policy.skill_id
        candidate.scene.parent_version = original.scene.version
        candidate.scene.version = uuid4().hex
        candidate = CanvasDocument.model_validate(candidate.model_dump())
        stored_patch = patch.model_copy(update={"snapshot_asset_id": current.document_asset_id})
        return self._render_commit(
            candidate, context, expected_parent=patch.parent_version, patch=stored_patch, dpi=dpi
        )

    def rollback(
        self,
        scene_id: str,
        restored_version: str,
        expected_parent: str,
        context: CallContext,
        *,
        dpi=144,
    ):
        current = self.repository.head(scene_id)
        if current.version != expected_parent:
            raise ValueError("stale rollback parent version")
        snapshot = self.repository.version(scene_id, restored_version)
        candidate = CanvasDocument.model_validate_json(
            self.repository.store.read_blob(self.repository.project_id, snapshot.document_asset_id)
        )
        candidate.scene.parent_version = expected_parent
        candidate.scene.version = uuid4().hex
        request = SnapshotRollback(
            id=uuid4().hex,
            scene_id=scene_id,
            project_id=self.repository.project_id,
            expected_parent_version=expected_parent,
            restored_version=restored_version,
        )
        return self._render_commit(
            candidate, context, expected_parent=expected_parent, rollback=request, dpi=dpi
        )

    def _base(self, layer_id, bounds):
        return dict(
            id=layer_id, name=layer_id, semantic_role="unassigned", z_index=0, bounds=bounds
        )

    def _refresh_groups(self, layers, presentations):
        visited = set()

        def refresh(layer_id):
            if layer_id in visited:
                return
            layer = layers[layer_id]
            if isinstance(layer, m.GroupLayer):
                for child in layer.member_layer_ids:
                    refresh(child)
                presentation = presentations[layer_id]
                presentation.source_bounds = group_bounds(
                    [layers[i] for i in layer.member_layer_ids]
                )
                layer.bounds = geometry.bounds(presentation.transform, presentation.source_bounds)
            visited.add(layer_id)

        for layer_id in layers:
            refresh(layer_id)

    def _add(self, layer, layers, presentations):
        layers[layer.id] = layer
        presentations[layer.id] = LayerPresentation(layer_id=layer.id, source_bounds=layer.bounds)

    def add_image(self, op: m.AddImageOp, layers, presentations):
        self._add(
            m.ImageLayer(
                **self._base(op.layer_id, op.bounds), asset_id=op.asset_id, opacity=op.opacity
            ),
            layers,
            presentations,
        )
        if op.rotation_deg:
            self.transform_layer(
                m.TransformLayerOp(layer_id=op.layer_id, rotation_deg=op.rotation_deg),
                layers,
                presentations,
            )

    def add_text(self, op: m.AddTextOp, layers, presentations):
        self._add(
            m.TextLayer(
                **self._base(op.layer_id, op.bounds),
                text_content=op.text_content,
                style_name=op.style_name,
                derived_text_id=op.derived_text_id,
            ),
            layers,
            presentations,
        )

    def add_path(self, op: m.AddPathOp, layers, presentations):
        self._add(
            m.VectorLayer(
                **self._base(op.layer_id, path_bounds(op.path)),
                path=op.path,
                fill_color=op.fill_color,
                stroke_color=op.stroke_color,
            ),
            layers,
            presentations,
        )
        presentations[op.layer_id].stroke_width_mm = op.stroke_width_mm

    def transform_layer(self, op: m.TransformLayerOp, layers, presentations):
        layer = layers[op.layer_id]
        p = presentations[op.layer_id]
        p.transform = geometry.compose(geometry.operation_transform(op, layer.bounds), p.transform)
        layer.bounds = geometry.bounds(p.transform, p.source_bounds)

    def clip_to_path(self, op: m.ClipToPathOp, layers, presentations):
        p = presentations[op.target_layer_id]
        p.clips.append(geometry.transform_path(op.path, geometry.inverse(p.transform)))

    def set_z_index(self, op: m.SetZIndexOp, layers, presentations):
        layers[op.layer_id].z_index = op.z_index

    def apply_mask(self, op: m.ApplyMaskOp, layers, presentations):
        p = presentations[op.target_layer_id]
        p.mask_asset_id = op.mask_asset_id
        p.invert_mask = op.invert

    def edit_path(self, op: m.EditPathOp, layers, presentations):
        layer = layers[op.layer_id]
        p = presentations[op.layer_id]
        layer.path = geometry.transform_path(op.path, geometry.inverse(p.transform))
        p.source_bounds = path_bounds(layer.path)
        layer.bounds = geometry.bounds(p.transform, p.source_bounds)

    def set_blend_mode(self, op: m.SetBlendModeOp, layers, presentations):
        layers[op.layer_id].blend_mode = op.blend_mode

    def create_group(self, op: m.CreateGroupOp, layers, presentations):
        members = [layers[i] for i in op.member_layer_ids]
        self._add(
            m.GroupLayer(
                **self._base(op.group_layer_id, group_bounds(members)),
                member_layer_ids=op.member_layer_ids,
            ),
            layers,
            presentations,
        )

    def set_clip_stack(self, op: m.SetClipStackOp, layers, presentations):
        presentations[op.target_layer_id].clip_layer_ids = op.clip_path_layer_ids

    def bind_asset(self, op: m.BindAssetOp, layers, presentations):
        layer = layers[op.layer_id]
        if isinstance(layer, m.ImageLayer):
            layer.asset_id = op.asset_id
        else:
            layer.mask_asset_id = op.asset_id

    def set_opacity(self, op: m.SetOpacityOp, layers, presentations):
        layers[op.layer_id].opacity = op.opacity

    def boolean_path(self, op: m.BooleanPathOp, layers, presentations):
        from editorial_studio.canvas.typography.paths import geometry_path, region

        target = layers[op.target_layer_id]
        operand = layers[op.operand_layer_id]
        a = region(geometry.transform_path(target.path, presentations[target.id].transform))
        b = region(geometry.transform_path(operand.path, presentations[operand.id].transform))
        result = {"union": a.union, "difference": a.difference, "intersection": a.intersection}[
            op.operation_type
        ](b)
        path = geometry_path(result)
        self.edit_path(m.EditPathOp(layer_id=target.id, path=path), layers, presentations)

    def text_on_path(self, op: m.TextOnPathOp, layers, presentations):
        from editorial_studio.canvas.typography.advanced_models import PathTextSpec

        if op.layer_id not in layers:
            self.add_text(
                m.AddTextOp(
                    layer_id=op.layer_id,
                    text_content=op.text_content,
                    style_name=op.style_name,
                    bounds=path_bounds(op.path),
                ),
                layers,
                presentations,
            )
        layer = layers[op.layer_id]
        p = presentations[op.layer_id]
        layer.text_content = op.text_content
        layer.style_name = op.style_name
        p.shape_flow = None
        p.path_text = PathTextSpec(
            path=geometry.transform_path(op.path, geometry.inverse(p.transform)),
            side=op.side,
            start_offset_mm=op.start_offset_mm,
        )
        p.source_bounds = path_bounds(p.path_text.path)
        layer.bounds = geometry.bounds(p.transform, p.source_bounds)

    def flow_text_into_shape(self, op: m.FlowTextIntoShapeOp, layers, presentations):
        from editorial_studio.canvas.typography.advanced_models import ShapeFlowSpec

        if op.layer_id not in layers:
            self.add_text(
                m.AddTextOp(
                    layer_id=op.layer_id,
                    text_content=op.text_content,
                    style_name=op.style_name,
                    bounds=path_bounds(op.boundary),
                ),
                layers,
                presentations,
            )
        layer = layers[op.layer_id]
        p = presentations[op.layer_id]
        layer.text_content = op.text_content
        layer.style_name = op.style_name
        p.path_text = None
        p.shape_flow = ShapeFlowSpec(
            boundary=geometry.transform_path(op.boundary, geometry.inverse(p.transform)),
            exclusion_paths=[
                geometry.transform_path(path, geometry.inverse(p.transform))
                for path in op.exclusion_paths
            ],
        )
        p.source_bounds = path_bounds(p.shape_flow.boundary)
        layer.bounds = geometry.bounds(p.transform, p.source_bounds)

    def set_glyph_transforms(self, op: m.SetGlyphTransformsOp, layers, presentations):
        presentations[op.layer_id].glyph_transforms = op.transforms
        presentations[op.layer_id].outline_text = True

    def gradient_mask(self, op: m.GradientMaskOp, layers, presentations):
        p = presentations[op.target_layer_id]
        inverse = geometry.inverse(p.transform)
        p.gradient = op.model_copy(
            update={
                "start": geometry.point(inverse, op.start),
                "end": geometry.point(inverse, op.end),
            }
        )

    def color_adjust(self, op: m.ColorAdjustOp, layers, presentations):
        presentations[op.layer_id].color_adjustments.append(op)

    def apply_filter(self, op: m.ApplyFilterOp, layers, presentations):
        presentations[op.layer_id].filters.append(op.filter)

    def displacement_map(self, op: m.DisplacementMapOp, layers, presentations):
        presentations[op.target_layer_id].displacements.append(op)
