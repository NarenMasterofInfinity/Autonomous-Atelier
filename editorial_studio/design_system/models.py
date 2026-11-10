"""Typed M2 design tokens and measured baseline-layout inputs."""

from typing import Literal

from pydantic import Field, model_validator

from editorial_studio.contracts.models import BoundsMM, PaletteToken, StrictModel


class GridSpec(StrictModel):
    width_mm: float = Field(default=420, gt=0)
    height_mm: float = Field(default=297, gt=0)
    page_width_mm: float = Field(default=210, gt=0)
    outer_margin_mm: float = Field(default=20, ge=0)
    top_margin_mm: float = Field(default=20, ge=0)
    bottom_margin_mm: float = Field(default=20, ge=0)
    fold_safe_mm: float = Field(default=10, ge=0)
    columns_per_page: int = Field(default=3, ge=1, le=12)
    column_gap_mm: float = Field(default=6, ge=0)
    baseline_step_mm: float = Field(default=5, gt=0)
    baseline_tolerance_mm: float = Field(default=0.01, gt=0, le=0.05)
    baseline_origin_mm: float = Field(default=20, ge=0)

    @model_validator(mode="after")
    def feasible(self):
        if abs(self.width_mm - 2 * self.page_width_mm) > 1e-6:
            raise ValueError("facing grid must contain two equal pages")
        if (
            self.page_width_mm
            - self.outer_margin_mm
            - self.fold_safe_mm
            - (self.columns_per_page - 1) * self.column_gap_mm
            <= 0
        ):
            raise ValueError("columns and gaps do not fit the page")
        if self.top_margin_mm + self.bottom_margin_mm >= self.height_mm:
            raise ValueError("vertical margins consume the canvas")
        return self


class ModularTypeScale(StrictModel):
    id: str
    body_pt: float = Field(ge=9, le=16)
    ratio: float = Field(gt=1, le=2)
    role_steps: dict[str, int]

    @model_validator(mode="after")
    def complete(self):
        if not {"headline", "deck", "body", "caption"} <= set(self.role_steps):
            raise ValueError("type scale must define all baseline text roles")
        if self.role_steps["body"] != 0:
            raise ValueError("body is the modular scale anchor")
        return self

    def size(self, role: str) -> float:
        return round(self.body_pt * self.ratio ** self.role_steps[role], 3)


class FontPairing(StrictModel):
    id: str
    name: str
    headline_font_id: str
    body_font_id: str
    detail_font_id: str
    intent: str


class PairingCatalog(StrictModel):
    pairings: list[FontPairing] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self):
        ids = [p.id for p in self.pairings]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate font pairing")
        return self


class DesignTokens(StrictModel):
    id: str
    version: str
    grid: GridSpec
    type_scale: ModularTypeScale
    palette: list[PaletteToken]
    rule_width_mm: float = Field(gt=0, le=2)
    minimum_body_pt: float = Field(ge=9, le=16)
    body_span_columns: int = Field(default=2, ge=1)
    prefer_paragraph_breaks: bool = False

    @model_validator(mode="after")
    def valid_palette(self):
        names = [p.name for p in self.palette]
        if len(names) != len(set(names)) or not {"paper", "ink", "muted", "accent"} <= set(names):
            raise ValueError("palette needs unique paper, ink, muted, and accent tokens")
        if self.type_scale.body_pt < self.minimum_body_pt:
            raise ValueError("body size is below the copyfit floor")
        if self.body_span_columns > self.grid.columns_per_page:
            raise ValueError("reading measure does not fit one page")
        return self


class GridColumn(StrictModel):
    index: int = Field(ge=0)
    side: Literal["left", "right"]
    bounds: BoundsMM


class BaselineStory(StrictModel):
    id: str
    title: str = Field(min_length=1)
    deck: str = Field(min_length=1)
    paragraphs: list[str] = Field(min_length=1)
    author: str = Field(min_length=1)
    section: str = Field(min_length=1)
    layout: Literal["feature", "essay", "interview"]
    photo_asset_id: str | None = None

    @model_validator(mode="after")
    def no_empty_copy(self):
        if any(not p.strip() for p in self.paragraphs):
            raise ValueError("paragraphs cannot be empty")
        return self

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)


class TextPlacement(StrictModel):
    field: Literal["title", "deck", "body"]
    layer_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_char < self.start_char:
            raise ValueError("placement range is reversed")
        return self


class TextFitEvidence(StrictModel):
    field: Literal["title", "deck", "body"]
    layer_id: str
    source_char_count: int = Field(ge=0)
    consumed_end_char: int = Field(ge=0)
    overflow_start_char: int | None = Field(default=None, ge=0)


class BaselineLayoutReport(StrictModel):
    story_id: str
    scene_id: str
    placements: list[TextPlacement]
    unplaced_body_start: int | None = Field(default=None, ge=0)
    baseline_step_mm: float = Field(gt=0)
    baseline_origin_mm: float
    baseline_tolerance_mm: float = 0.01
    body_baselines_mm: list[float]
    text_fit: list[TextFitEvidence] = Field(default_factory=list)
    unplaced_fields: list[Literal["title", "deck", "body"]] = Field(default_factory=list)
