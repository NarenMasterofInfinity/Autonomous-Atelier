"""V6 M0 normative Pydantic contracts for the Autonomous AI Editorial Studio.

Executable companion to Section 15 of Implementation Plan v6.0.
Python 3.11+, Pydantic 2.x.  No arbitrary dictionaries at module boundaries.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class SpatialMode(str, Enum):
    SEMANTIC = "semantic"
    GUIDED = "guided"
    FREEFORM = "freeform"


class EditType(str, Enum):
    VERBATIM = "verbatim"
    EXCERPT = "excerpt"
    CONDENSED = "condensed"
    PARAPHRASE = "paraphrase"
    NEW_COPY = "new_copy"


class CriticVerdict(str, Enum):
    ACCEPT = "ACCEPT"
    REVISE = "REVISE"
    RECOMPOSE = "RECOMPOSE"
    RECONCEPT = "RECONCEPT"
    REPLAN = "REPLAN"


class AttemptState(str, Enum):
    SUBMITTING = "SUBMITTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED_AFTER_SUBMIT = "CANCELLED_AFTER_SUBMIT"
    AMBIGUOUS = "AMBIGUOUS"


class AssetType(str, Enum):
    RASTER = "raster"
    VECTOR = "vector"
    MASK = "mask"
    TEXT_PATH = "text_path"
    COMPOSITE = "composite"


class BlendMode(str, Enum):
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    DARKEN = "darken"
    LIGHTEN = "lighten"


class CompositionUnit(str, Enum):
    SINGLE_PAGE = "single_page"
    FACING_SPREAD = "facing_spread"
    MULTI_SPREAD = "multi_spread"
    COVER = "cover"


class PageSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class CoverageStatus(str, Enum):
    UNASSIGNED = "unassigned"
    PLACED = "placed"
    DEFERRED = "deferred"
    OMITTED_APPROVED = "omitted_approved"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CostCertainty(str, Enum):
    REPORTED = "reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


# Geometric coordinates are in MILLIMETRES unless the field explicitly says normalized.
class PointMM(StrictModel):
    x_mm: float
    y_mm: float


class NormalizedPoint(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class BoundsMM(StrictModel):
    x_mm: float
    y_mm: float
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class NormalizedRegion(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_canvas(self):
        if self.x + self.width > 1.0000001 or self.y + self.height > 1.0000001:
            raise ValueError("normalized region extends beyond canvas")
        return self


class MoveTo(StrictModel):
    cmd: Literal["M"] = "M"
    p: PointMM


class LineTo(StrictModel):
    cmd: Literal["L"] = "L"
    p: PointMM


class QuadraticTo(StrictModel):
    cmd: Literal["Q"] = "Q"
    control: PointMM
    p: PointMM


class CubicTo(StrictModel):
    cmd: Literal["C"] = "C"
    control1: PointMM
    control2: PointMM
    p: PointMM


class ClosePath(StrictModel):
    cmd: Literal["Z"] = "Z"


PathCommand: TypeAlias = Annotated[
    Union[MoveTo, LineTo, QuadraticTo, CubicTo, ClosePath], Field(discriminator="cmd")
]


class PathGeometry(StrictModel):
    commands: list[PathCommand] = Field(min_length=2)
    fill_rule: Literal["nonzero", "evenodd"] = "nonzero"

    @model_validator(mode="after")
    def validate_subpaths(self):
        open_subpath = False
        had_segment = False
        for i, command in enumerate(self.commands):
            if isinstance(command, MoveTo):
                if open_subpath and not had_segment:
                    raise ValueError(f"empty subpath before index {i}")
                open_subpath = True
                had_segment = False
            elif isinstance(command, ClosePath):
                if not open_subpath or not had_segment:
                    raise ValueError(f"invalid ClosePath at index {i}")
                open_subpath = False
            else:
                if not open_subpath:
                    raise ValueError(f"path segment without MoveTo at index {i}")
                had_segment = True
        if not isinstance(self.commands[0], MoveTo):
            raise ValueError("path must start with MoveTo")
        if open_subpath and not had_segment:
            raise ValueError("final subpath is empty")
        return self


class GlyphTransform(StrictModel):
    # Index into a *shaped glyph run*, not a Python string character index.
    glyph_index: int = Field(ge=0)
    dx_mm: float = 0.0
    dy_mm: float = 0.0
    rotation_deg: float = 0.0
    scale_x: float = Field(default=1.0, gt=0)
    scale_y: float = Field(default=1.0, gt=0)


class GradientStop(StrictModel):
    offset: float = Field(ge=0, le=1)
    opacity: float = Field(ge=0, le=1)


class BlurFilter(StrictModel):
    kind: Literal["blur"] = "blur"
    radius_mm: float = Field(gt=0)


class ShadowFilter(StrictModel):
    kind: Literal["shadow"] = "shadow"
    offset: PointMM
    radius_mm: float = Field(ge=0)
    rgba_hex: str = Field(pattern=r"^#[0-9a-fA-F]{8}$")


class GrainFilter(StrictModel):
    kind: Literal["grain"] = "grain"
    strength: float = Field(ge=0, le=1)
    random_seed: int


class HalftoneFilter(StrictModel):
    kind: Literal["halftone"] = "halftone"
    dot_spacing_mm: float = Field(gt=0)
    angle_deg: float = 0.0


FilterSpec: TypeAlias = Annotated[
    Union[BlurFilter, ShadowFilter, GrainFilter, HalftoneFilter], Field(discriminator="kind")
]


# 21 executable operations: the 20 in v5 plus SetOpacityOp.
class AddImageOp(StrictModel):
    op: Literal["add_image"] = "add_image"
    layer_id: str
    asset_id: str
    bounds: BoundsMM
    rotation_deg: float = 0.0
    opacity: float = Field(default=1.0, ge=0, le=1)


class AddTextOp(StrictModel):
    op: Literal["add_text"] = "add_text"
    layer_id: str
    text_content: str
    style_name: str
    bounds: BoundsMM
    derived_text_id: str | None = None


class TransformLayerOp(StrictModel):
    op: Literal["transform_layer"] = "transform_layer"
    layer_id: str
    dx_mm: float = 0.0
    dy_mm: float = 0.0
    scale_x: float = Field(default=1.0, gt=0)
    scale_y: float = Field(default=1.0, gt=0)
    rotation_deg: float = 0.0


class ClipToPathOp(StrictModel):
    op: Literal["clip_to_path"] = "clip_to_path"
    target_layer_id: str
    path: PathGeometry


class SetZIndexOp(StrictModel):
    op: Literal["set_z_index"] = "set_z_index"
    layer_id: str
    z_index: int


class ApplyMaskOp(StrictModel):
    op: Literal["apply_mask"] = "apply_mask"
    target_layer_id: str
    mask_asset_id: str
    invert: bool = False


class AddPathOp(StrictModel):
    op: Literal["add_path"] = "add_path"
    layer_id: str
    path: PathGeometry
    stroke_color: str | None = None
    fill_color: str | None = None
    stroke_width_mm: float = Field(default=0.5, ge=0)


class EditPathOp(StrictModel):
    op: Literal["edit_path"] = "edit_path"
    layer_id: str
    path: PathGeometry


class BooleanPathOp(StrictModel):
    op: Literal["boolean_path"] = "boolean_path"
    target_layer_id: str
    operand_layer_id: str
    operation_type: Literal["union", "difference", "intersection"]


class TextOnPathOp(StrictModel):
    op: Literal["text_on_path"] = "text_on_path"
    layer_id: str
    text_content: str
    style_name: str
    path: PathGeometry
    side: Literal["left", "right"] = "left"
    start_offset_mm: float = 0.0


class SetGlyphTransformsOp(StrictModel):
    op: Literal["set_glyph_transforms"] = "set_glyph_transforms"
    layer_id: str
    transforms: list[GlyphTransform] = Field(min_length=1)


class FlowTextIntoShapeOp(StrictModel):
    op: Literal["flow_text_into_shape"] = "flow_text_into_shape"
    layer_id: str
    text_content: str
    style_name: str
    boundary: PathGeometry
    exclusion_paths: list[PathGeometry] = Field(default_factory=list)


class SetBlendModeOp(StrictModel):
    op: Literal["set_blend_mode"] = "set_blend_mode"
    layer_id: str
    blend_mode: BlendMode


class CreateGroupOp(StrictModel):
    op: Literal["create_group"] = "create_group"
    group_layer_id: str
    member_layer_ids: list[str] = Field(min_length=1)


class SetClipStackOp(StrictModel):
    op: Literal["set_clip_stack"] = "set_clip_stack"
    target_layer_id: str
    clip_path_layer_ids: list[str]


class ColorAdjustOp(StrictModel):
    op: Literal["color_adjust"] = "color_adjust"
    layer_id: str
    brightness: float = Field(default=0.0, ge=-1, le=1)
    contrast: float = Field(default=1.0, ge=0, le=4)
    saturation: float = Field(default=1.0, ge=0, le=4)


class GradientMaskOp(StrictModel):
    op: Literal["gradient_mask"] = "gradient_mask"
    target_layer_id: str
    gradient_type: Literal["linear", "radial"]
    start: PointMM
    end: PointMM
    stops: list[GradientStop] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_stops(self):
        offsets = [stop.offset for stop in self.stops]
        if offsets != sorted(set(offsets)):
            raise ValueError("gradient stop offsets must be unique and ascending")
        return self


class DisplacementMapOp(StrictModel):
    op: Literal["displacement_map"] = "displacement_map"
    target_layer_id: str
    map_asset_id: str
    scale_mm: float = Field(ge=0)


class ApplyFilterOp(StrictModel):
    op: Literal["apply_filter"] = "apply_filter"
    layer_id: str
    filter: FilterSpec


class BindAssetOp(StrictModel):
    op: Literal["bind_asset"] = "bind_asset"
    layer_id: str
    asset_id: str
    asset_type: AssetType


class SetOpacityOp(StrictModel):
    op: Literal["set_opacity"] = "set_opacity"
    layer_id: str
    opacity: float = Field(ge=0, le=1)


RegistryOperation: TypeAlias = Annotated[Union[
    AddImageOp, AddTextOp, TransformLayerOp, ClipToPathOp, SetZIndexOp,
    ApplyMaskOp, AddPathOp, EditPathOp, BooleanPathOp, TextOnPathOp,
    SetGlyphTransformsOp, FlowTextIntoShapeOp, SetBlendModeOp, CreateGroupOp,
    SetClipStackOp, ColorAdjustOp, GradientMaskOp, DisplacementMapOp,
    ApplyFilterOp, BindAssetOp, SetOpacityOp,
], Field(discriminator="op")]


class BaseLayer(StrictModel):
    id: str
    name: str
    owner_skill_id: str | None = None
    semantic_role: str
    z_index: int
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0, le=1)
    blend_mode: BlendMode = BlendMode.NORMAL
    bounds: BoundsMM


class ImageLayer(BaseLayer):
    layer_type: Literal["image"] = "image"
    asset_id: str
    effective_ppi: float | None = Field(default=None, gt=0)


class TextLayer(BaseLayer):
    layer_type: Literal["text"] = "text"
    text_content: str
    style_name: str
    derived_text_id: str | None = None


class VectorLayer(BaseLayer):
    layer_type: Literal["vector"] = "vector"
    path: PathGeometry
    stroke_color: str | None = None
    fill_color: str | None = None


class MaskLayer(BaseLayer):
    layer_type: Literal["mask"] = "mask"
    mask_asset_id: str
    invert: bool = False


class GroupLayer(BaseLayer):
    layer_type: Literal["group"] = "group"
    member_layer_ids: list[str] = Field(min_length=1)


Layer: TypeAlias = Annotated[
    Union[ImageLayer, TextLayer, VectorLayer, MaskLayer, GroupLayer], Field(discriminator="layer_type")
]


class Scene(StrictModel):
    id: str
    spread_id: str
    version: str
    parent_version: str | None = None
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    layers: list[Layer] = Field(default_factory=list)
    design_language_id: str
    created_at: datetime

    @model_validator(mode="after")
    def unique_layer_ids(self):
        ids = [layer.id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate layer id")
        return self


class ScenePatch(StrictModel):
    patch_id: str
    parent_version: str
    target_scene_id: str
    operations: list[RegistryOperation] = Field(min_length=1)
    created_layer_ids: list[str] = Field(default_factory=list)
    modified_layer_ids: list[str] = Field(default_factory=list)
    declared_dependencies: list[str] = Field(default_factory=list)
    snapshot_asset_id: str | None = None

    @model_validator(mode="after")
    def no_duplicate_create_modify(self):
        if set(self.created_layer_ids) & set(self.modified_layer_ids):
            raise ValueError("layer cannot be both created and modified")
        return self


class PaletteToken(StrictModel):
    name: str
    hex_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class IssuePhaseDirection(StrictModel):
    phase_name: str
    emotional_role: str
    visual_behavior: str


class ArtDirectionBible(StrictModel):
    id: str
    version: str
    approval_state: Literal["provisional", "final", "revision_required"]
    conceptual_identity: str
    font_pairing_id: str
    palette: list[PaletteToken]
    photographic_character: list[str]
    signature_behaviors: list[str]
    narrative_progression: list[IssuePhaseDirection]
    recurring_motifs: list[str]
    artistic_boundaries: list[str]
    approved_visual_examples: list[str]
    provisional_proof_spread_ids: list[str] = Field(default_factory=list)
    final_proof_spread_ids: list[str] = Field(default_factory=list)


class ConceptBrief(StrictModel):
    id: str
    project_id: str
    spread_id: str
    visual_metaphor: str
    compositional_structure: str
    photography_treatment: str
    narrative_expression: str


class ConceptNode(StrictModel):
    id: str
    role: Literal["image", "text", "subject", "vector", "mask", "texture", "group"]
    source_asset_id: str | None = None
    derived_text_id: str | None = None
    target_region: NormalizedRegion | None = None
    z_order_hint: int | None = None


class ConceptRelationship(StrictModel):
    source_id: str
    target_id: str
    relation: Literal[
        "behind", "above", "overlaps", "avoids", "aligns_to",
        "flows_around", "spans_gutter", "follows_path", "clips_to"
    ]
    rationale: str


class SpatialConceptGraph(StrictModel):
    nodes: list[ConceptNode]
    relationships: list[ConceptRelationship]

    @model_validator(mode="after")
    def valid_edges(self):
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("duplicate concept node ID")
        for rel in self.relationships:
            if rel.source_id not in ids or rel.target_id not in ids:
                raise ValueError("relationship references unknown node")
        return self


class ConceptSketch(StrictModel):
    asset_id: str
    concept_brief_id: str
    aspect_ratio: float = Field(gt=0)
    source_photo_ids: list[str]


class UnsupportedFeature(StrictModel):
    feature: str
    reason: str
    proposed_fallback: str | None = None


class ExtractedVisualElement(StrictModel):
    id: str
    concept_node_id: str
    mapped_layer_id: str | None = None
    mapped_asset_id: str | None = None
    mapping_confidence: float = Field(ge=0, le=1)


class SourceSpan(StrictModel):
    source_block_id: str
    source_revision_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_char <= self.start_char:
            raise ValueError("end_char must exceed start_char")
        return self


class DerivedText(StrictModel):
    id: str
    text: str
    edit_type: EditType
    derived_from: list[SourceSpan] = Field(default_factory=list)
    placed_layer_ids: list[str] = Field(default_factory=list)


class CoverageAssignment(StrictModel):
    span: SourceSpan
    status: CoverageStatus
    assigned_spread_id: str | None = None
    approval_actor: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def omission_approved(self):
        if self.status == CoverageStatus.OMITTED_APPROVED and not self.approval_actor:
            raise ValueError("omission requires approval_actor")
        return self


class TypographyFinding(StrictModel):
    code: Literal[
        "UNSUPPORTED_SCRIPT", "FONT_FALLBACK", "PATH_OVERFLOW", "TEXT_OVERFLOW",
        "UNREADABLE_ORIENTATION", "SHAPE_COLLISION", "UNSATISFIED_WIDOW_ORPHAN",
        "NARROW_LINE_REGION", "GLYPH_MAPPING_FAILURE"
    ]
    severity: Severity
    detail: str


class ShapedGlyphPlacement(StrictModel):
    glyph_index: int = Field(ge=0)
    cluster_start: int = Field(ge=0)
    cluster_end: int = Field(ge=0)
    position: PointMM
    tangent_deg: float = 0.0
    advance_mm: float = Field(ge=0)


class TextLayoutResult(StrictModel):
    text_layer_id: str
    font_hash: str
    ink_bounds: BoundsMM
    logical_bounds: BoundsMM
    writing_direction: Literal["ltr", "rtl", "vertical"]
    consumed_end_char: int = Field(ge=0)
    overflow_start_char: int | None = Field(default=None, ge=0)
    line_count: int = Field(ge=0)
    glyphs: list[ShapedGlyphPlacement] = Field(default_factory=list)
    findings: list[TypographyFinding] = Field(default_factory=list)


class ContentBlock(StrictModel):
    id: str
    source_revision_id: str
    source_text: str
    attached_image_ids: list[str]
    derived_texts: list[DerivedText] = Field(default_factory=list)
    coverage: list[CoverageAssignment] = Field(default_factory=list)


class SpreadBrief(StrictModel):
    project_id: str
    spread_id: str
    composition_unit: CompositionUnit
    assigned_story_ids: list[str]
    assigned_photo_ids: list[str]
    narrative_role: str
    physical_page_numbers: list[int] = Field(min_length=1)
    art_direction_bible_id: str
    reference_ids: list[str] = Field(default_factory=list)
    previous_spread_thumbnail_asset_id: str | None = None
    next_spread_thumbnail_asset_id: str | None = None


class RuleBreakJustification(StrictModel):
    rule: str
    justification: str


class AnchorRelationship(StrictModel):
    source_layer_id: str
    target_layer_id: str
    relationship_type: Literal[
        "behind", "above", "align_left", "align_center", "overlaps", "wrap_around", "avoid"
    ]
    offset_mm: float = 0.0


class SpatialIntent(StrictModel):
    mode: SpatialMode
    primary_solver: str | None = None
    anchor_relationships: list[AnchorRelationship] = Field(default_factory=list)
    custom_paths: list[PathGeometry] = Field(default_factory=list)
    rule_breaks: list[RuleBreakJustification] = Field(default_factory=list)


class SkillSlot(StrictModel):
    name: str
    value_kind: Literal["asset", "layer", "text", "number", "boolean", "point", "path", "region", "color"]
    asset_type: AssetType | None = None
    required: bool = True


class RecipeValueString(StrictModel):
    kind: Literal["string"] = "string"
    value: str


class RecipeValueNumber(StrictModel):
    kind: Literal["number"] = "number"
    value: float


class RecipeValueBoolean(StrictModel):
    kind: Literal["boolean"] = "boolean"
    value: bool


class RecipeValuePoint(StrictModel):
    kind: Literal["point"] = "point"
    value: PointMM


class RecipeValuePath(StrictModel):
    kind: Literal["path"] = "path"
    value: PathGeometry


class RecipeValueSlot(StrictModel):
    kind: Literal["slot_ref"] = "slot_ref"
    slot_name: str


RecipeValue: TypeAlias = Annotated[Union[
    RecipeValueString, RecipeValueNumber, RecipeValueBoolean,
    RecipeValuePoint, RecipeValuePath, RecipeValueSlot,
], Field(discriminator="kind")]


class RecipeArgument(StrictModel):
    parameter_name: str
    value: RecipeValue


# Names are checked against the operation registry at skill-publish time.
OperationName: TypeAlias = Literal[
    "add_image", "add_text", "transform_layer", "clip_to_path", "set_z_index",
    "apply_mask", "add_path", "edit_path", "boolean_path", "text_on_path",
    "set_glyph_transforms", "flow_text_into_shape", "set_blend_mode", "create_group",
    "set_clip_stack", "color_adjust", "gradient_mask", "displacement_map",
    "apply_filter", "bind_asset", "set_opacity",
]


class RecipeStep(StrictModel):
    id: str
    operation_name: OperationName
    arguments: list[RecipeArgument]
    depends_on_step_ids: list[str] = Field(default_factory=list)


class SkillManifest(StrictModel):
    id: str
    version: str
    category: str
    intent: str
    composition_units: list[CompositionUnit]
    suitable_conditions: list[str]
    required_capabilities: list[str]
    parameters: list[SkillSlot]
    inputs: list[SkillSlot]
    outputs: list[SkillSlot]
    dependencies: list[str]
    compatible_skill_ids: list[str]
    incompatible_skill_ids: list[str]
    recipe: list[RecipeStep]
    evaluation_checks: list[str]
    fallbacks: list[str]


class RasterOutputSpec(StrictModel):
    kind: Literal["raster"] = "raster"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    alpha_required: bool = False


class VectorOutputSpec(StrictModel):
    kind: Literal["vector"] = "vector"
    format: Literal["svg"] = "svg"
    editable_paths_required: bool = True


class MaskOutputSpec(StrictModel):
    kind: Literal["mask"] = "mask"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)


class TextPathOutputSpec(StrictModel):
    kind: Literal["text_path"] = "text_path"
    format: Literal["svg"] = "svg"


class CompositeOutputSpec(StrictModel):
    kind: Literal["composite"] = "composite"
    editable_layer_ids: list[str] = Field(min_length=1)


ArtifactOutputSpec: TypeAlias = Annotated[
    Union[RasterOutputSpec, VectorOutputSpec, MaskOutputSpec, TextPathOutputSpec, CompositeOutputSpec],
    Field(discriminator="kind"),
]


class ArtifactRequest(StrictModel):
    id: str
    asset_type: AssetType
    visual_role: str
    generation_spec: str
    target_region: NormalizedRegion
    color_constraints: list[str]
    preferred_generation_method: str
    # This may refer to a symbolic scene slot before an actual layer is created.
    target_layer_dependency_id: str
    integration_method: Literal["clipping", "masking", "blending", "direct"]
    output: ArtifactOutputSpec
    provenance_notes: str
    visual_acceptance_checks: list[str] = Field(default_factory=list)


class HybridConceptOutput(StrictModel):
    concept_brief: ConceptBrief
    spatial_concept_graph: SpatialConceptGraph
    sketch: ConceptSketch
    artifact_requirements: list[ArtifactRequest]
    required_capabilities: list[str]


class ConceptCompilerOutput(StrictModel):
    concept_brief_id: str
    target_scene_skeleton: Scene
    extracted_visual_elements: list[ExtractedVisualElement]
    unsupported_features: list[UnsupportedFeature]


class PhysicalPage(StrictModel):
    number: int = Field(ge=1)
    side: PageSide
    spread_id: str | None = None
    folio_text: str | None = None
    is_cover: bool = False


class PageMap(StrictModel):
    project_id: str
    pages: list[PhysicalPage] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_page_numbers(self):
        nums = [p.number for p in self.pages]
        if len(nums) != len(set(nums)):
            raise ValueError("duplicate physical page number")
        return self


class CritiqueFinding(StrictModel):
    category: str
    severity: Severity
    description: str
    actionable_fix: str
    target_layer_ids: list[str] = Field(default_factory=list)


class RuleBreakEvaluation(StrictModel):
    rule: str
    accepted: bool
    reason: str


class ReviewDecision(StrictModel):
    verdict: CriticVerdict
    execution_findings: list[CritiqueFinding]
    artistic_findings: list[CritiqueFinding]
    concept_fidelity_findings: list[CritiqueFinding]
    rule_break_evaluations: list[RuleBreakEvaluation]
    target_edit_instructions: str | None = None
    stagnation_detected: bool = False


class AttemptRecord(StrictModel):
    attempt_id: str
    call_id: str
    request_hash: str
    state: AttemptState
    provider_request_id: str | None = None
    model_snapshot: str
    reconciliation_status: str
    submitted_at: datetime | None = None
    ended_at: datetime | None = None
    possible_charge_usd: float | None = Field(default=None, ge=0)


class UsageRecord(StrictModel):
    # Usage values that are not reported by a provider remain null, not zero.
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    text_input_tokens: int | None = Field(default=None, ge=0)
    image_input_tokens: int | None = Field(default=None, ge=0)
    image_output_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def nested_counts(self):
        if self.input_tokens is not None and self.cached_input_tokens is not None:
            if self.cached_input_tokens > self.input_tokens:
                raise ValueError("cached input token count cannot exceed input tokens")
        if self.output_tokens is not None and self.reasoning_tokens is not None:
            if self.reasoning_tokens > self.output_tokens:
                raise ValueError("reasoning token count cannot exceed output tokens")
        return self


class CostRecord(StrictModel):
    certainty: CostCertainty
    pricing_version: str
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    reported_cost_usd: float | None = Field(default=None, ge=0)
    billing_uncertain: bool = False
    rate_breakdown_asset_id: str | None = None


class ProviderCallRecord(StrictModel):
    call_id: str
    project_id: str
    run_id: str
    spread_id: str | None = None
    parent_call_id: str | None = None
    agent_name: str
    stage: str
    provider: str
    api_operation: str
    model_requested: str
    model_snapshot: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    image_complexity: str | None = None
    image_quality: str | None = None
    prompt_version: str
    schema_version: str
    request_hash: str
    request_payload_asset_id: str | None = None
    response_payload_asset_id: str | None = None
    visible_decision_summary: str | None = None
    attempt_ids: list[str]
    status: Literal["queued", "streaming", "completed", "failed", "ambiguous", "cancelled"]
    started_at: datetime
    ended_at: datetime | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    usage: UsageRecord | None = None
    cost: CostRecord
    generated_artifact_ids: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    error_summary: str | None = None
    cache_hit: bool = False


class ToolExecutionRecord(StrictModel):
    tool_call_id: str
    project_id: str
    run_id: str
    spread_id: str | None = None
    parent_call_id: str | None = None
    tool_name: str
    input_asset_id: str | None = None
    output_asset_ids: list[str] = Field(default_factory=list)
    status: Literal["started", "completed", "failed", "cancelled"]
    elapsed_ms: float | None = Field(default=None, ge=0)
    error_summary: str | None = None


class StageEvent(StrictModel):
    kind: Literal["stage"] = "stage"
    from_stage: str
    to_stage: str
    reason: str | None = None


class CallEvent(StrictModel):
    kind: Literal["call"] = "call"
    call_id: str
    attempt_id: str | None = None
    new_status: str


class ArtifactEvent(StrictModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: str
    action: Literal["created", "replaced", "validated", "rejected"]


class SceneEvent(StrictModel):
    kind: Literal["scene"] = "scene"
    scene_id: str
    scene_version: str
    patch_id: str | None = None


class DecisionEvent(StrictModel):
    kind: Literal["decision"] = "decision"
    decision_id: str
    verdict: CriticVerdict


EventPayload: TypeAlias = Annotated[
    Union[StageEvent, CallEvent, ArtifactEvent, SceneEvent, DecisionEvent],
    Field(discriminator="kind"),
]


class WorkflowEvent(StrictModel):
    event_id: str
    project_id: str
    run_id: str
    spread_id: str | None = None
    parent_event_id: str | None = None
    timestamp: datetime
    payload: EventPayload


# Agent-specific outputs can wrap the contracts above (for example:
# Editor -> SpreadBrief; Art Director -> ConceptBrief/ArtDirectionBible;
# Composer -> HybridConceptOutput/ScenePatch; Critic -> ReviewDecision).
# Tool validation is separate from model-level validation. At runtime the
# executor resolves bindings, validates every RegistryOperation, then enforces
# read/write sets, layer ownership, asset existence and scene-version checks.
