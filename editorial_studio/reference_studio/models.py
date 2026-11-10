"""Versioned visual-family definitions and exact authored proof bindings."""

from typing import Literal

from pydantic import Field, model_validator

from editorial_studio.contracts.models import StrictModel
from editorial_studio.creative.models import ConceptProposal, CreativeSpread, CriticAssessment


class EditorialFamily(StrictModel):
    id: str
    version: int = Field(ge=1)
    name: str
    principle: str
    reference_ids: list[str] = Field(min_length=1)
    capability_ids: list[str]
    suitability: list[str] = Field(min_length=1)
    composition_rules: list[str] = Field(min_length=1)
    avoid: list[str] = Field(default_factory=list)


class AuthoredReference(StrictModel):
    id: str
    design_id: str = ""
    authoring_fingerprint: str = ""
    project_id: str
    family_id: str
    family_version: int = Field(ge=1)
    title: str
    story_id: str
    spread: CreativeSpread
    brief: str
    reference_ids: list[str]
    family_snapshot_json: str
    authorship: Literal["authored"] = "authored"
    status: Literal["authored_for_review", "visually_reviewed", "needs_rework"] = (
        "authored_for_review"
    )
    human_approval: bool = False
    reviewer: str | None = None
    review_note: str | None = None

    @model_validator(mode="after")
    def binding(self):
        if self.spread.project_id != self.project_id or self.spread.story_id != self.story_id:
            raise ValueError("reference proof inputs differ")
        return self


class ReferenceAtlas(StrictModel):
    id: str
    project_id: str
    reference_ids: list[str] = Field(min_length=1)
    pdf_asset_id: str
    contact_sheet_asset_id: str
    human_approval: bool = False


class CompositionSlot(StrictModel):
    node_id: str
    role: Literal["headline", "deck", "body", "photo", "alpha"]
    source_order: int = 0
    source_fraction: float = Field(default=1, gt=0, le=1)
    source_aspect_ratio: float | None = None
    reference_crop_fraction: float | None = None
    minimum_face_visibility: float = 0
    photo_index: int = Field(default=0, ge=0)
    display_line_count: int | None = Field(default=None, ge=1)
    display_ink_overhang_mm: tuple[float, float, float, float] | None = None


class LayoutCharacteristics(StrictModel):
    background_color: str
    display_sizes_pt: list[float]
    display_fonts: list[str]
    paint_modes: list[str]
    rotations_deg: list[float]
    photographic_area_fraction: float
    mechanisms: list[str]
    layer_order: list[str]
    reading_regions: list[list[float]]
    source_metrics: dict[str, float] = Field(default_factory=dict)


class CompositionProgram(StrictModel):
    id: str
    version: str = "reference-program-v1"
    reference_id: str
    source_project: str
    family_id: str
    name: str
    proposal: ConceptProposal
    slots: list[CompositionSlot]
    photo_fill_groups: list[list[str]] = Field(default_factory=list)
    characteristics: LayoutCharacteristics
    minimum_display_ratio: float = Field(default=0.72, gt=0, le=1)
    maximum_display_ratio: float = Field(default=1.08, ge=1, le=1.5)


class LayoutFinding(StrictModel):
    code: str
    layers: list[str]
    detail: str
    severity: Literal["error", "review"] = "error"


class TextVisibility(StrictModel):
    layer_id: str
    role: str
    visible_fraction: float
    contrast_fraction: float


class LayoutQuality(StrictModel):
    passed: bool
    text: list[TextVisibility]
    findings: list[LayoutFinding]
    display_ink_fraction: float = 0
    display_photo_overlap_fraction: float = 0
    background_fraction: float = 0
    scope: str = (
        "Rendered visibility, contrast and ink collisions; not aesthetic or professional approval."
    )


class NativeViews(StrictModel):
    source_png_asset_id: str
    dpi: float
    assets: dict[str, str]
    boxes_px: dict[str, tuple[int, int, int, int]]


class ReferenceChoice(StrictModel):
    program_id: str
    rationale: str = Field(min_length=1)


class ProgramCandidate(StrictModel):
    program_id: str
    family_id: str
    reference_id: str
    spread: CreativeSpread
    quality: LayoutQuality
    minimum_display_ratio: float
    native_views: NativeViews | None = None


class ProgramRejection(StrictModel):
    program_id: str
    reason: str


class ReferenceComposition(StrictModel):
    id: str
    project_id: str
    story_id: str
    identity_id: str
    reference_project: str = "m10a-references"
    art_director_requested: bool = False
    page_role: Literal["spread", "cover"] = "spread"
    reference_ids: list[str]
    program_asset_ids: list[str] = Field(default_factory=list)
    input_fingerprint: str = ""
    candidates: list[ProgramCandidate]
    rejections: list[ProgramRejection]
    selected_program_id: str | None = None
    state: Literal["ready_for_visual_review", "no_admissible_candidate"]
    proof_book_asset_id: str | None = None
    contact_sheet_asset_id: str | None = None
    human_approval: bool = False
    art_direction_rationale: str | None = None
    visual_review: CriticAssessment | None = None
    review_mode: Literal["not_run", "standalone", "reference_aware"] = "standalone"
