"""Durable advanced typography settings and source-to-outline glyph evidence."""

from pydantic import Field

from editorial_studio.contracts.models import PathGeometry, StrictModel


class PathTextSpec(StrictModel):
    path: PathGeometry
    side: str = Field(default="left", pattern="^(left|right)$")
    start_offset_mm: float = Field(default=0, ge=0)


class ShapeFlowSpec(StrictModel):
    boundary: PathGeometry
    exclusion_paths: list[PathGeometry] = Field(default_factory=list)
    minimum_line_width_mm: float = Field(default=15, gt=0)


class OutlineGlyph(StrictModel):
    text_layer_id: str = ""
    glyph_index: int
    glyph_id: int
    font_hash: str
    cluster_start: int
    cluster_end: int
    path: PathGeometry | None
    x_mm: float
    y_mm: float
    tangent_deg: float
