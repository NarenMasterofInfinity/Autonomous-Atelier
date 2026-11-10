"""M2 provisional identity and proof-review contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from editorial_studio.canvas.typography.fonts import FontConfiguration
from editorial_studio.contracts.capability_matrix import CapabilityCoverage
from editorial_studio.contracts.models import ArtDirectionBible, StrictModel
from editorial_studio.design_system.models import (
    BaselineLayoutReport,
    BaselineStory,
    DesignTokens,
    FontPairing,
)


class LayoutGuidelines(StrictModel):
    font_pairing_id: str
    body_size_pt: float
    headline_size_pt: float
    baseline_step_mm: float
    fold_safe_mm: float
    columns_per_page: int
    palette_roles: dict[str, str]
    photographic_character: list[str]
    composition_rules: list[str]
    copyfit_actions: list[str]
    reference_ids: list[str]
    identity_stage: Literal["provisional"] = "provisional"


class IdentityProof(StrictModel):
    story_id: str
    scene_id: str
    scene_version: str
    document_asset_id: str
    png_asset_id: str
    pdf_asset_id: str
    metadata_asset_id: str
    report: BaselineLayoutReport


class IdentityReview(StrictModel):
    id: str
    actor: str = Field(min_length=1)
    verdict: Literal["approved", "revision_required"]
    note: str = Field(min_length=1)
    reviewed_at: datetime
    reviewed_proof_versions: list[str] = Field(min_length=3)

    @model_validator(mode="after")
    def meaningful_review(self):
        if not self.actor.strip() or not self.note.strip():
            raise ValueError("reviewer and note must not be blank")
        return self


class ProvisionalIdentity(StrictModel):
    id: str
    project_id: str
    run_id: str
    bible: ArtDirectionBible
    pairing: FontPairing
    revision: int = Field(default=0, ge=0)
    tokens: DesignTokens
    guidelines: LayoutGuidelines
    proofs: list[IdentityProof] = Field(min_length=3, max_length=3)
    capabilities: list[CapabilityCoverage]
    proof_book_asset_id: str | None = None
    contact_sheet_asset_id: str | None = None
    review: IdentityReview | None = None
    created_at: datetime
    typography: FontConfiguration | None = None

    @model_validator(mode="after")
    def proof_bindings(self):
        scene_ids = [proof.scene_id for proof in self.proofs]
        if (
            self.bible.font_pairing_id != self.pairing.id
            or self.guidelines.font_pairing_id != self.pairing.id
        ):
            raise ValueError("Bible and executable font pairing disagree")
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("duplicate identity proof")
        if any(
            p.report.scene_id != p.scene_id
            or p.report.story_id != p.story_id
            or p.report.unplaced_body_start is not None
            or p.report.unplaced_fields
            for p in self.proofs
        ):
            raise ValueError("proof layout is incomplete or bound to another story")
        if set(self.bible.provisional_proof_spread_ids) != set(scene_ids):
            raise ValueError("Bible proof links do not match rendered proofs")
        if self.bible.approval_state == "final":
            raise ValueError("M2 cannot authorize final creative identity")
        if self.review and sorted(self.review.reviewed_proof_versions) != sorted(
            p.scene_version for p in self.proofs
        ):
            raise ValueError("review does not bind the exact proof versions")
        return self


class IdentityBuildCheckpoint(StrictModel):
    id: str
    project_id: str
    run_id: str
    bible: ArtDirectionBible
    tokens: DesignTokens
    pairing: FontPairing
    font_configuration: FontConfiguration
    stories: list[BaselineStory]
    guidelines: LayoutGuidelines
    created_at: datetime
    render_dpi: float = Field(default=144, gt=0, le=1200)
