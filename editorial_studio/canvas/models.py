"""Typed M1 companion state; the normative v6 scene remains editable and unchanged."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from editorial_studio.canvas.typography.advanced_models import (
    OutlineGlyph,
    PathTextSpec,
    ShapeFlowSpec,
)
from editorial_studio.canvas.typography.fonts import FontConfiguration
from editorial_studio.contracts.models import (
    BoundsMM,
    ColorAdjustOp,
    DisplacementMapOp,
    FilterSpec,
    GlyphTransform,
    GradientMaskOp,
    PathGeometry,
    Scene,
    StrictModel,
    TextLayoutResult,
)


class AffineMM(StrictModel):
    a: float = 1
    b: float = 0
    c: float = 0
    d: float = 1
    e_mm: float = 0
    f_mm: float = 0

    @model_validator(mode="after")
    def invertible(self):
        if abs(self.a * self.d - self.b * self.c) < 1e-12:
            raise ValueError("singular layer transform")
        return self


class LayerPresentation(StrictModel):
    layer_id: str
    source_bounds: BoundsMM
    transform: AffineMM = Field(default_factory=AffineMM)
    clips: list[PathGeometry] = Field(default_factory=list)
    clip_layer_ids: list[str] = Field(default_factory=list)
    mask_asset_id: str | None = None
    invert_mask: bool = False
    stroke_width_mm: float = Field(default=0.5, ge=0)
    path_text: PathTextSpec | None = None
    shape_flow: ShapeFlowSpec | None = None
    glyph_transforms: list[GlyphTransform] = Field(default_factory=list)
    outline_text: bool = False
    gradient: GradientMaskOp | None = None
    color_adjustments: list[ColorAdjustOp] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    displacements: list[DisplacementMapOp] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_layout_mode(self):
        if self.path_text and self.shape_flow:
            raise ValueError("text cannot use path and shape layout simultaneously")
        return self


class CanvasDocument(StrictModel):
    scene: Scene
    presentations: list[LayerPresentation] = Field(default_factory=list)
    background_color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    typography: FontConfiguration | None = None
    enforce_text_provenance: bool = False

    @model_validator(mode="after")
    def complete_presentations(self):
        ids = [p.layer_id for p in self.presentations]
        layers = {layer.id for layer in self.scene.layers}
        if len(ids) != len(set(ids)) or set(ids) != layers:
            raise ValueError("every scene layer needs exactly one presentation")
        for p in self.presentations:
            if not set(p.clip_layer_ids) <= layers:
                raise ValueError("missing clip layer")
        return self

    @classmethod
    def from_scene(cls, scene: Scene):
        return cls(
            scene=scene,
            presentations=[
                LayerPresentation(layer_id=layer.id, source_bounds=layer.bounds)
                for layer in scene.layers
            ],
        )


class GlyphDetail(StrictModel):
    index: int = Field(ge=0)
    glyph_id: int | None = None
    cluster_start: int = Field(ge=0)
    cluster_end: int = Field(ge=0)
    x_mm: float
    y_mm: float
    advance_mm: float = Field(ge=0)


class ShapedRun(StrictModel):
    font_family: str
    font_hash: str
    direction: Literal["ltr", "rtl"]
    glyphs: list[GlyphDetail]


class TextLine(StrictModel):
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    baseline_mm: float
    logical_bounds: BoundsMM
    paragraph_start: bool


class ParagraphLayout(StrictModel):
    result: TextLayoutResult
    lines: list[TextLine]
    runs: list[ShapedRun]
    visible_line_count: int = Field(ge=0)
    copyfit_actions: list[
        Literal["editorial_edit", "adjust_frame", "alternate_style", "repaginate"]
    ] = Field(default_factory=list)


class RenderMetadata(StrictModel):
    document_hash: str
    cairo_version: str
    pango_version: str
    font_hashes: list[str]
    native_library_hashes: dict[str, str]
    dpi: float = Field(gt=0)
    canvas_width_mm: float = Field(gt=0)
    canvas_height_mm: float = Field(gt=0)
    text_layouts: list[ParagraphLayout]
    glyph_outlines: list[OutlineGlyph] = Field(default_factory=list)


class RenderOutput(StrictModel):
    png: bytes
    pdf: bytes
    metadata: RenderMetadata


class SceneVersion(StrictModel):
    id: str
    project_id: str
    run_id: str | None = None
    scene_id: str
    version: str
    parent_version: str | None
    document_asset_id: str
    png_asset_id: str
    pdf_asset_id: str
    metadata_asset_id: str
    snapshot_asset_id: str | None = None
    patch_id: str | None = None
    created_at: datetime
