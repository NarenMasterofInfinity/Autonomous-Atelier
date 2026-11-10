"""Single typed operation registry and prospective-patch validation.

These are validation handlers, not claims of renderer support. M1 supplies the
renderer capability set and transactional render/commit executor. Validation
uses a private scene copy and never changes a live scene.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from pydantic import Field, TypeAdapter

from editorial_studio.contracts import models as m


class PatchRejected(ValueError):
    pass


class RuntimePolicy(m.StrictModel):
    skill_id: str | None = None
    readable_layer_ids: set[str]
    writable_layer_ids: set[str]
    asset_ids: set[str] = Field(default_factory=set)
    mask_asset_ids: set[str] = Field(default_factory=set)
    derived_text_ids: set[str] = Field(default_factory=set)
    style_names: set[str] = Field(default_factory=set)
    allowed_operations: set[str]
    renderer_operations: set[str]


class OperationAccess(m.StrictModel):
    created: set[str] = Field(default_factory=set)
    read: set[str] = Field(default_factory=set)
    written: set[str] = Field(default_factory=set)
    assets: set[str] = Field(default_factory=set)


class PatchValidation(m.StrictModel):
    patch_id: str
    created_layer_ids: list[str]
    modified_layer_ids: list[str]
    dependencies: list[str]


@dataclass(frozen=True)
class OperationDefinition:
    model: type[m.StrictModel]
    handler: str


REGISTRY: dict[str, OperationDefinition] = {}


def operation(model):
    def decorate(handler):
        name = model.model_fields["op"].default
        if name in REGISTRY:
            raise RuntimeError(f"duplicate operation {name}")
        REGISTRY[name] = OperationDefinition(model=model, handler=handler.__name__)
        return handler

    return decorate


def closed(path: m.PathGeometry) -> None:
    is_open = False
    segment_count = 0
    for cmd in path.commands:
        if isinstance(cmd, m.MoveTo):
            if is_open:
                raise PatchRejected("every clipping subpath must close")
            is_open, segment_count = True, 0
        elif isinstance(cmd, m.ClosePath):
            if segment_count < 2:
                raise PatchRejected("closed region needs at least two segments")
            is_open = False
        else:
            segment_count += 1
    if is_open:
        raise PatchRejected("clipping or flow boundary must be closed")


def group_bounds(members: list[m.Layer]) -> m.BoundsMM:
    x = min(layer.bounds.x_mm for layer in members)
    y = min(layer.bounds.y_mm for layer in members)
    return m.BoundsMM(
        x_mm=x,
        y_mm=y,
        width_mm=max(layer.bounds.x_mm + layer.bounds.width_mm for layer in members) - x,
        height_mm=max(layer.bounds.y_mm + layer.bounds.height_mm for layer in members) - y,
    )


def path_bounds(path: m.PathGeometry) -> m.BoundsMM:
    points = []
    for cmd in path.commands:
        for field in ("p", "control", "control1", "control2"):
            point = getattr(cmd, field, None)
            if point:
                points.append(point)
    xs, ys = [p.x_mm for p in points], [p.y_mm for p in points]
    # Zero-height stroked paths are allowed; bounds enclose their stroke.
    return m.BoundsMM(
        x_mm=min(xs),
        y_mm=min(ys),
        width_mm=max(max(xs) - min(xs), 0.001),
        height_mm=max(max(ys) - min(ys), 0.001),
    )


class Validator:
    def __init__(self, scene: m.Scene, policy: RuntimePolicy):
        self.layers = {layer.id: layer.model_copy(deep=True) for layer in scene.layers}
        self.policy = policy
        self.created: set[str] = set()

    def layer(self, layer_id: str, expected=None, *, write=False):
        layer = self.layers.get(layer_id)
        if layer is None:
            raise PatchRejected(f"missing layer: {layer_id}")
        if expected and not isinstance(layer, expected):
            raise PatchRejected(f"incompatible layer type: {layer_id}")
        if layer_id not in self.created:
            if layer_id not in self.policy.readable_layer_ids:
                raise PatchRejected(f"layer is outside read permission: {layer_id}")
            if write and layer_id not in self.policy.writable_layer_ids:
                raise PatchRejected(f"layer is outside write permission: {layer_id}")
            if write and layer.owner_skill_id not in {None, self.policy.skill_id}:
                raise PatchRejected(f"layer owned by another skill: {layer_id}")
        return layer

    def asset(self, asset_id: str, *, mask=False):
        if asset_id not in self.policy.asset_ids:
            raise PatchRejected(f"missing or inaccessible asset: {asset_id}")
        if mask and asset_id not in self.policy.mask_asset_ids:
            raise PatchRejected(f"asset is not a mask: {asset_id}")

    def style(self, name: str):
        if name not in self.policy.style_names:
            raise PatchRejected(f"unknown typography style: {name}")

    def create(self, layer: m.Layer) -> OperationAccess:
        if layer.id in self.layers:
            raise PatchRejected(f"layer already exists: {layer.id}")
        self.layers[layer.id] = layer
        self.created.add(layer.id)
        return OperationAccess(created={layer.id})

    def base(self, layer_id, bounds):
        return dict(
            id=layer_id,
            name=layer_id,
            semantic_role="unassigned",
            z_index=0,
            bounds=bounds,
            owner_skill_id=self.policy.skill_id,
        )

    def write(self, layer_id, expected=None) -> OperationAccess:
        layer = self.layer(layer_id, expected, write=True)
        result = OperationAccess(read={layer_id}, written={layer_id})
        if isinstance(layer, m.GroupLayer):
            for member in layer.member_layer_ids:
                access = self.write(member)
                result.read.update(access.read)
                result.written.update(access.written)
        return result

    @operation(m.AddImageOp)
    def add_image(self, op: m.AddImageOp):
        self.asset(op.asset_id)
        result = self.create(
            m.ImageLayer(
                **self.base(op.layer_id, op.bounds), asset_id=op.asset_id, opacity=op.opacity
            )
        )
        result.assets.add(op.asset_id)
        return result

    @operation(m.AddTextOp)
    def add_text(self, op: m.AddTextOp):
        self.style(op.style_name)
        if op.derived_text_id and op.derived_text_id not in self.policy.derived_text_ids:
            raise PatchRejected("missing text provenance")
        return self.create(
            m.TextLayer(
                **self.base(op.layer_id, op.bounds),
                text_content=op.text_content,
                style_name=op.style_name,
                derived_text_id=op.derived_text_id,
            )
        )

    @operation(m.TransformLayerOp)
    def transform_layer(self, op: m.TransformLayerOp):
        access = self.write(op.layer_id)
        layer = self.layers[op.layer_id]
        b = layer.bounds
        layer.bounds = m.BoundsMM(
            x_mm=b.x_mm + op.dx_mm,
            y_mm=b.y_mm + op.dy_mm,
            width_mm=b.width_mm * op.scale_x,
            height_mm=b.height_mm * op.scale_y,
        )
        return access

    @operation(m.ClipToPathOp)
    def clip_to_path(self, op: m.ClipToPathOp):
        result = self.write(op.target_layer_id)
        closed(op.path)
        return result

    @operation(m.SetZIndexOp)
    def set_z_index(self, op: m.SetZIndexOp):
        result = self.write(op.layer_id)
        self.layers[op.layer_id].z_index = op.z_index
        return result

    @operation(m.ApplyMaskOp)
    def apply_mask(self, op: m.ApplyMaskOp):
        result = self.write(op.target_layer_id)
        self.asset(op.mask_asset_id, mask=True)
        result.assets.add(op.mask_asset_id)
        return result

    @operation(m.AddPathOp)
    def add_path(self, op: m.AddPathOp):
        return self.create(
            m.VectorLayer(
                **self.base(op.layer_id, path_bounds(op.path)),
                path=op.path,
                stroke_color=op.stroke_color,
                fill_color=op.fill_color,
            )
        )

    @operation(m.EditPathOp)
    def edit_path(self, op: m.EditPathOp):
        result = self.write(op.layer_id, m.VectorLayer)
        self.layers[op.layer_id].path = op.path
        self.layers[op.layer_id].bounds = path_bounds(op.path)
        return result

    @operation(m.BooleanPathOp)
    def boolean_path(self, op: m.BooleanPathOp):
        result = self.write(op.target_layer_id, m.VectorLayer)
        self.layer(op.operand_layer_id, m.VectorLayer)
        closed(self.layers[op.target_layer_id].path)
        closed(self.layers[op.operand_layer_id].path)
        result.read.add(op.operand_layer_id)
        return result

    @operation(m.TextOnPathOp)
    def text_on_path(self, op: m.TextOnPathOp):
        self.style(op.style_name)
        if op.layer_id in self.layers:
            return self.write(op.layer_id, m.TextLayer)
        return self.create(
            m.TextLayer(
                **self.base(op.layer_id, path_bounds(op.path)),
                text_content=op.text_content,
                style_name=op.style_name,
            )
        )

    @operation(m.SetGlyphTransformsOp)
    def set_glyph_transforms(self, op: m.SetGlyphTransformsOp):
        result = self.write(op.layer_id, m.TextLayer)
        indices = [item.glyph_index for item in op.transforms]
        if len(indices) != len(set(indices)):
            raise PatchRejected("duplicate shaped glyph index")
        # Glyph-run range verification is performed by the M5 shaper.
        return result

    @operation(m.FlowTextIntoShapeOp)
    def flow_text_into_shape(self, op: m.FlowTextIntoShapeOp):
        self.style(op.style_name)
        closed(op.boundary)
        for path in op.exclusion_paths:
            closed(path)
        if op.layer_id in self.layers:
            return self.write(op.layer_id, m.TextLayer)
        return self.create(
            m.TextLayer(
                **self.base(op.layer_id, path_bounds(op.boundary)),
                text_content=op.text_content,
                style_name=op.style_name,
            )
        )

    @operation(m.SetBlendModeOp)
    def set_blend_mode(self, op: m.SetBlendModeOp):
        result = self.write(op.layer_id)
        self.layers[op.layer_id].blend_mode = op.blend_mode
        return result

    @operation(m.CreateGroupOp)
    def create_group(self, op: m.CreateGroupOp):
        if len(op.member_layer_ids) != len(set(op.member_layer_ids)):
            raise PatchRejected("duplicate group member")
        members = [self.layer(i, write=True) for i in op.member_layer_ids]
        bounds = group_bounds(members)
        result = self.create(
            m.GroupLayer(
                **self.base(op.group_layer_id, bounds), member_layer_ids=op.member_layer_ids
            )
        )
        for member_id in op.member_layer_ids:
            access = self.write(member_id)
            result.read.update(access.read)
            result.written.update(access.written)
        return result

    @operation(m.SetClipStackOp)
    def set_clip_stack(self, op: m.SetClipStackOp):
        result = self.write(op.target_layer_id)
        for layer_id in op.clip_path_layer_ids:
            layer = self.layer(layer_id, m.VectorLayer)
            closed(layer.path)
            if layer_id == op.target_layer_id:
                raise PatchRejected("layer cannot clip itself")
            result.read.add(layer_id)
        return result

    @operation(m.ColorAdjustOp)
    def color_adjust(self, op: m.ColorAdjustOp):
        return self.write(op.layer_id, m.ImageLayer)

    @operation(m.GradientMaskOp)
    def gradient_mask(self, op: m.GradientMaskOp):
        result = self.write(op.target_layer_id)
        if op.start == op.end:
            raise PatchRejected("gradient needs nonzero extent")
        return result

    @operation(m.DisplacementMapOp)
    def displacement_map(self, op: m.DisplacementMapOp):
        result = self.write(op.target_layer_id, m.ImageLayer)
        self.asset(op.map_asset_id)
        result.assets.add(op.map_asset_id)
        return result

    @operation(m.ApplyFilterOp)
    def apply_filter(self, op: m.ApplyFilterOp):
        return self.write(op.layer_id, m.ImageLayer)

    @operation(m.BindAssetOp)
    def bind_asset(self, op: m.BindAssetOp):
        result = self.write(op.layer_id, (m.ImageLayer, m.MaskLayer))
        mask = isinstance(self.layers[op.layer_id], m.MaskLayer)
        if op.asset_type != (m.AssetType.MASK if mask else m.AssetType.RASTER):
            raise PatchRejected("asset binding type does not match layer")
        self.asset(op.asset_id, mask=mask)
        result.assets.add(op.asset_id)
        return result

    @operation(m.SetOpacityOp)
    def set_opacity(self, op: m.SetOpacityOp):
        result = self.write(op.layer_id)
        self.layers[op.layer_id].opacity = op.opacity
        return result

    def validate_groups(self):
        visiting, visited, parents = set(), set(), {}

        def visit(layer_id):
            if layer_id in visiting:
                raise PatchRejected("group cycle")
            if layer_id in visited:
                return
            if layer_id not in self.layers:
                raise PatchRejected("group contains missing layer")
            visiting.add(layer_id)
            layer = self.layers[layer_id]
            if isinstance(layer, m.GroupLayer):
                for member in layer.member_layer_ids:
                    if member in parents and parents[member] != layer_id:
                        raise PatchRejected("layer belongs to multiple groups")
                    parents[member] = layer_id
                    visit(member)
            visiting.remove(layer_id)
            visited.add(layer_id)

        for key in self.layers:
            visit(key)


def validate_patch(scene: m.Scene, patch: m.ScenePatch, policy: RuntimePolicy) -> PatchValidation:
    # Revalidate to catch mutation of model lists after initial construction.
    scene = m.Scene.model_validate(scene.model_dump())
    patch = m.ScenePatch.model_validate(patch.model_dump())
    if patch.target_scene_id != scene.id:
        raise PatchRejected("patch belongs to another scene")
    if patch.parent_version != scene.version:
        raise PatchRejected("stale parent version")
    validator = Validator(scene, policy)
    validator.validate_groups()
    total = OperationAccess()
    for op in patch.operations:
        if op.op not in policy.allowed_operations:
            raise PatchRejected(f"operation outside permission: {op.op}")
        definition = REGISTRY[op.op]
        typed_op = definition.model.model_validate(op.model_dump())
        access = getattr(validator, definition.handler)(typed_op)
        if op.op not in policy.renderer_operations:
            raise PatchRejected(f"renderer capability unavailable: {op.op}")
        for name in ("created", "read", "written", "assets"):
            getattr(total, name).update(getattr(access, name))
    validator.validate_groups()
    modified = total.written - total.created
    dependencies = (total.read - total.created) | total.assets
    if (
        len(patch.created_layer_ids) != len(set(patch.created_layer_ids))
        or set(patch.created_layer_ids) != total.created
    ):
        raise PatchRejected("declared create set does not match operations")
    if (
        len(patch.modified_layer_ids) != len(set(patch.modified_layer_ids))
        or set(patch.modified_layer_ids) != modified
    ):
        raise PatchRejected("declared write set does not match operations")
    if set(patch.declared_dependencies) != dependencies:
        raise PatchRejected("declared dependencies do not match reads and assets")
    return PatchValidation(
        patch_id=patch.patch_id,
        created_layer_ids=sorted(total.created),
        modified_layer_ids=sorted(modified),
        dependencies=sorted(dependencies),
    )


OPERATION_ADAPTER = TypeAdapter(m.RegistryOperation)
union_models = set(get_args(get_args(m.RegistryOperation)[0]))
if union_models != {item.model for item in REGISTRY.values()}:
    raise RuntimeError("operation models and validation handlers must match exactly")
