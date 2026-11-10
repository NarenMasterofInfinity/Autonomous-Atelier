"""Twelve physical pages, issue pacing, and versioned visual history."""

from typing import Literal

from pydantic import Field, model_validator

from editorial_studio.contracts import models as m
from editorial_studio.creative.models import ConceptProposal, CreativeSpread, CriticAssessment


class IssueSlot(m.StrictModel):
    id: str
    story_id: str
    phase: Literal["cover", "opening", "feature", "essay", "interlude", "closing"]
    left_page: int = Field(ge=1, le=12)
    right_page: int = Field(ge=1, le=12)
    visual_energy: int = Field(ge=1, le=5)
    visual_metaphor: str = Field(min_length=1)
    narrative_goal: str = Field(min_length=1)
    composition_mandate: str = Field(min_length=1)


class IssueBlueprint(m.StrictModel):
    title: str = Field(min_length=1)
    throughline: str = Field(min_length=1)
    slots: list[IssueSlot] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def physical_sequence(self):
        if (
            len({slot.id for slot in self.slots}) != 6
            or len({slot.story_id for slot in self.slots}) != 6
        ):
            raise ValueError("issue needs six unique slots and six unique stories")
        expected = [(12, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11)]
        if [(slot.left_page, slot.right_page) for slot in self.slots] != expected:
            raise ValueError("issue must map covers 12/1 then five facing pairs 2/3 through 10/11")
        if self.slots[0].phase != "cover":
            raise ValueError("first scene must contain both covers")
        return self


class PrinterSheet(m.StrictModel):
    sheet: int = Field(ge=1)
    front_left: int
    front_right: int
    back_left: int
    back_right: int


class IssueCorrection(m.StrictModel):
    slot_id: str
    instruction: str = Field(min_length=1)
    replacement_story_id: str | None = None
    regenerate: bool = True
    authored_proposal: ConceptProposal | None = None

    @model_validator(mode="after")
    def source_change_needs_composition(self):
        if self.replacement_story_id and not self.regenerate:
            raise ValueError("a replacement story needs source-aware recomposition")
        return self


class IssueBuild(m.StrictModel):
    id: str
    project_id: str
    identity_id: str
    story_ids: list[str]
    tournament_ids: list[str]
    reference_ids: list[str] = Field(default_factory=list)
    reference_project: str = "m10a-references"
    reference_art_director: bool = True
    prepared_composition_ids: list[str] = Field(default_factory=list)
    reference_selections: dict[str, str] = Field(default_factory=dict)
    identity_snapshot_json: str
    configuration_json: str
    model: str
    blueprint: IssueBlueprint | None = None
    architect_call_id: str | None = None
    reference_asset_id: str | None = None
    revision_of: str | None = None
    corrections: list[IssueCorrection] = Field(default_factory=list)


class IssueComposeAttempt(m.StrictModel):
    id: str
    project_id: str
    issue_id: str
    slot_index: int = Field(ge=0, le=5)
    proposal_json: str | None = None
    provider_call_id: str | None = None
    error: str | None = None
    preparation_version: str = "native-issue-fit-v1"


class IssueSpread(m.StrictModel):
    id: str
    project_id: str
    issue_id: str
    slot: IssueSlot
    spread: CreativeSpread
    bible_before: m.ArtDirectionBible
    bible_after: m.ArtDirectionBible
    thumbnail_asset_id: str
    contact_sheet_asset_id: str
    image_area_fraction: float = Field(ge=0, le=1)
    headline_ink_fraction: float = Field(ge=0, le=1)
    source: Literal[
        "tournament",
        "composer",
        "retained",
        "native_repair",
        "authored_revision",
        "reference_program",
    ]


class IssueResult(m.StrictModel):
    id: str
    project_id: str
    identity_id: str
    blueprint: IssueBlueprint
    page_map: m.PageMap
    printer_sheets: list[PrinterSheet] = Field(min_length=3, max_length=3)
    spreads: list[IssueSpread] = Field(min_length=6, max_length=6)
    coherence: CriticAssessment
    coherence_call_id: str
    reader_pdf_asset_id: str
    contact_sheet_asset_id: str
    evidence_fingerprint: str
    state: Literal["review", "revision_required"]
    human_approval: bool = False

    @model_validator(mode="after")
    def complete(self):
        pages = self.page_map.pages
        if {page.number for page in pages} != set(range(1, 13)) or len(pages) != 12:
            raise ValueError("issue must contain physical pages 1 through 12 exactly once")
        if self.page_map.project_id != self.project_id:
            raise ValueError("page map project mismatch")
        planned = [slot.id for slot in self.blueprint.slots]
        if [spread.slot.id for spread in self.spreads] != planned:
            raise ValueError("issue spreads differ from plan")
        by_number = {page.number: page for page in pages}
        for entry in self.spreads:
            if (
                entry.project_id != self.project_id
                or entry.issue_id != self.id
                or entry.spread.project_id != self.project_id
            ):
                raise ValueError("issue history project mismatch")
            for number, side in [
                (entry.slot.left_page, m.PageSide.LEFT),
                (entry.slot.right_page, m.PageSide.RIGHT),
            ]:
                page = by_number[number]
                if (
                    page.side != side
                    or page.spread_id != entry.spread.scene_id
                    or page.is_cover != (number in (1, 12))
                ):
                    raise ValueError("physical page differs from its selected scene and side")
        numbers = [
            getattr(sheet, key)
            for sheet in self.printer_sheets
            for key in ("front_left", "front_right", "back_left", "back_right")
        ]
        if sorted(numbers) != list(range(1, 13)):
            raise ValueError("printer sheets must account for all physical pages")
        return self
