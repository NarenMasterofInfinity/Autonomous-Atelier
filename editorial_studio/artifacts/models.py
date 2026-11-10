"""Generated/derived assets retain integration intent and source call provenance."""

from pydantic import Field

from editorial_studio.contracts.models import ArtifactRequest, PathGeometry, StrictModel


class TracedVector(StrictModel):
    source_asset_id: str
    svg_asset_id: str
    path: PathGeometry
    source_width_px: int
    source_height_px: int
    potrace_version: str
    threshold: int
    source_foreground_fraction: float = Field(ge=0, le=1)
    reconstructed_iou: float = Field(ge=0, le=1)


class ArtifactBuild(StrictModel):
    id: str
    project_id: str
    request: ArtifactRequest
    reference_asset_ids: list[str]
    provider_call_id: str | None = None
    raster_asset_id: str
    output_asset_id: str
    traced: TracedVector | None = None
    classification: str
    status: str = "awaiting_visual_review"
    placed_scene_id: str | None = None
    placed_version: str | None = None
