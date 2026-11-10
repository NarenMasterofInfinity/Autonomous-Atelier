"""Frozen concept families, candidate slots, and visual tournament evidence."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from editorial_studio.contracts.models import StrictModel
from editorial_studio.creative.models import ComparativeAssessment, CreativeSpread


class MilestoneAcceptance(StrictModel):
    id: str
    project_id: str
    milestone: str
    actor: str
    note: str
    evidence_ids: list[str]
    recorded_at: datetime


class ConceptDirection(StrictModel):
    name: str = Field(min_length=1)
    visual_metaphor: str = Field(min_length=1)
    photography_role: str = Field(min_length=1)
    narrative_expression: str = Field(min_length=1)


class ConceptDirections(StrictModel):
    concepts: list[ConceptDirection] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def distinct(self):
        for field in ("name", "visual_metaphor"):
            values = [" ".join(getattr(c, field).casefold().split()) for c in self.concepts]
            if len(set(values)) != 2:
                raise ValueError("two distinct concept directions are required")
        return self


class TournamentBuild(StrictModel):
    id: str
    project_id: str
    story_id: str
    identity_id: str
    identity_snapshot_json: str
    mandate: str
    configuration_json: str
    model: str
    directions: ConceptDirections | None = None
    directions_call_id: str | None = None
    materials_json: str | None = None
    photo_ids: list[str] = Field(default_factory=list)
    continuation_configuration_json: str | None = None


class CandidateAttempt(StrictModel):
    id: str
    project_id: str
    tournament_id: str
    concept_index: int = Field(ge=0, le=1)
    variation_index: int = Field(ge=0, le=2)
    attempt_index: int = Field(ge=0)
    proposal_json: str | None = None
    provider_call_id: str | None = None
    spread: CreativeSpread | None = None
    error: str | None = None
    resolution_version: str | None = None


class TournamentMatch(StrictModel):
    id: str
    project_id: str
    tournament_id: str
    candidate_a: str
    candidate_b: str
    winner_id: str
    assessment: ComparativeAssessment
    provider_call_id: str
    tie_break: str | None = None


class CandidateBinding(StrictModel):
    slot_id: str
    concept_index: int
    variation_index: int
    spread_id: str
    scene_id: str
    scene_version: str
    concept_id: str
    review_id: str
    png_asset_id: str
    pdf_asset_id: str
    document_asset_id: str
    metadata_asset_id: str


class TournamentResult(StrictModel):
    id: str
    project_id: str
    story_id: str
    identity_id: str
    directions: ConceptDirections
    candidates: list[CandidateBinding] = Field(min_length=6, max_length=6)
    matches: list[TournamentMatch] = Field(min_length=5, max_length=5)
    winner_id: str
    contact_sheet_asset_id: str
    proof_book_asset_id: str
    minimum_structural_distance: float
    state: Literal["selected", "revision_required"]
    human_approval: bool = False

    @model_validator(mode="after")
    def complete(self):
        ids = {c.slot_id for c in self.candidates}
        if len(ids) != 6 or self.winner_id not in ids:
            raise ValueError("tournament needs six unique slots and a bound winner")
        if {(c.concept_index, c.variation_index) for c in self.candidates} != {
            (c, v) for c in range(2) for v in range(3)
        }:
            raise ValueError("tournament must contain two concepts by three variations")
        if any(
            m.candidate_a not in ids
            or m.candidate_b not in ids
            or m.winner_id not in (m.candidate_a, m.candidate_b)
            for m in self.matches
        ):
            raise ValueError("match refers to an unknown candidate")
        return self
