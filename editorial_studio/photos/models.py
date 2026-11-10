"""Photo analysis, ingestion and conditional enhancement boundaries."""

from typing import Literal

from pydantic import Field

from editorial_studio.contracts.models import BoundsMM, NormalizedRegion, StrictModel


class PhotoInput(StrictModel):
    filename: str = Field(min_length=1)
    data_base64: str = Field(min_length=1, max_length=50000000)
    source_uri: str = Field(min_length=1)
    credit: str = Field(min_length=1)


class StoryInput(StrictModel):
    id: str
    title: str = Field(min_length=1)
    deck: str = Field(min_length=1)
    body: str = Field(min_length=1)
    author: str = Field(min_length=1)
    photos: list[PhotoInput] = Field(min_length=1, max_length=20)


class PhotoAssessment(StrictModel):
    id: str
    project_id: str
    source_asset_id: str
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    sharpness: float = Field(ge=0)
    noise: float = Field(ge=0)
    contrast: float = Field(ge=0)
    faces: list[NormalizedRegion]
    saliency_asset_id: str
    negative_space_asset_id: str
    suggested_negative_space: list[NormalizedRegion]
    findings: list[str]
    source_uri: str
    credit: str


class PlacementAssessment(StrictModel):
    source_asset_id: str
    frame: BoundsMM
    effective_ppi: float = Field(gt=0)
    visible_source_fraction: float = Field(gt=0, le=1)
    status: Literal["native", "inspect_crop", "stylize_or_reduce"]
    upscale_eligible: bool
    original_ppi: float = Field(gt=0)
    requires_visual_review: bool


class UpscaleResult(StrictModel):
    source_asset_id: str
    output_asset_id: str
    backend: str
    model_sha256: str
    scale: int
    placement: PlacementAssessment
    review_required: bool = True


class IngestedStory(StrictModel):
    id: str
    project_id: str
    source_revision_id: str
    title_block_id: str
    deck_block_id: str
    body_block_id: str
    photo_assessment_ids: list[str]
    author: str
    run_id: str
