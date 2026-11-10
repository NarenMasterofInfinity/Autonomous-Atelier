from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from editorial_studio.contracts.models import StrictModel


class PreflightFinding(StrictModel):
    code: str
    severity: Literal["error", "warning"]
    description: str
    scene_id: str | None = None
    layer_id: str | None = None
    page_number: int | None = None


class ImageSampling(StrictModel):
    scene_id: str
    layer_id: str
    asset_id: str
    native_source_asset_id: str
    effective_ppi: float = Field(gt=0)
    native_ppi: float = Field(gt=0)


class ProductionPreflight(StrictModel):
    id: str
    project_id: str
    issue_id: str
    issue_evidence_fingerprint: str
    source_issue_hash: str
    lineage_fingerprint: str
    configuration_json: str
    findings: list[PreflightFinding]
    sampling: list[ImageSampling]
    checked_scene_versions: list[str]
    embedded_font_count: int = Field(ge=0)
    passed: bool

    @model_validator(mode="after")
    def consistent_verdict(self):
        if self.passed == any(f.severity == "error" for f in self.findings):
            raise ValueError("preflight verdict contradicts its hard findings")
        return self


class ProductionExport(StrictModel):
    id: str
    project_id: str
    issue_id: str
    issue_evidence_fingerprint: str
    source_issue_hash: str
    lineage_fingerprint: str
    issue_snapshot_asset_id: str
    preflight_asset_id: str
    pdf_asset_id: str | None = None
    page_count: int = Field(ge=0)
    trim_width_mm: float
    trim_height_mm: float
    bleed_mm: float
    state: Literal["blocked", "proof"]
    human_approval: bool = False
    created_at: datetime

    @model_validator(mode="after")
    def consistent_output(self):
        if self.state == "proof" and (self.pdf_asset_id is None or self.page_count != 12):
            raise ValueError("a production proof requires twelve PDF pages")
        if self.state == "blocked" and (self.pdf_asset_id is not None or self.page_count != 0):
            raise ValueError("blocked preflight cannot publish a PDF")
        return self
