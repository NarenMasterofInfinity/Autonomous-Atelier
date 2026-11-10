"""Backend-neutral point/box prompts, cutouts, and measurable edge diagnostics."""

from pydantic import Field, model_validator

from editorial_studio.contracts.models import NormalizedPoint, NormalizedRegion, StrictModel


class SegmentPrompt(StrictModel):
    source_asset_id: str
    points: list[NormalizedPoint] = Field(default_factory=list)
    labels: list[int] = Field(default_factory=list)
    box: NormalizedRegion | None = None
    fill_enclosed_holes: bool = False
    keep_largest_component: bool = False

    @model_validator(mode="after")
    def valid_prompt(self):
        if len(self.points) != len(self.labels) or any(n not in (0, 1) for n in self.labels):
            raise ValueError("one binary label per prompt point required")
        if not self.points and self.box is None:
            raise ValueError("a point or box prompt is required")
        return self


class EdgeQuality(StrictModel):
    foreground_fraction: float = Field(ge=0, le=1)
    soft_edge_fraction: float = Field(ge=0, le=1)
    edge_gradient: float = Field(ge=0, le=1)
    components: int = Field(ge=0)
    passed: bool
    findings: list[str]
    reference_iou: float | None = Field(default=None, ge=0, le=1)


class SegmentationResult(StrictModel):
    id: str
    project_id: str
    source_asset_id: str
    prompt: SegmentPrompt
    backend: str
    model_sha256: str
    predicted_iou: float = Field(ge=0, le=1)
    mask_asset_id: str
    alpha_asset_id: str
    cutout_asset_id: str
    quality: EdgeQuality
    human_review_required: bool = True
