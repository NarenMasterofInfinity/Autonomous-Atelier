"""Configuration is explicit; importing modules never dispatches provider calls."""

from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import Field, SecretStr

from editorial_studio.contracts.models import StrictModel

ROOT = Path(__file__).resolve().parent.parent


class FeatureFlags(StrictModel):
    reference_ingestion: bool = False
    automated_skill_generator: bool = False


class Settings(StrictModel):
    data_root: Path = ROOT / "data/projects"
    pricing_path: Path = ROOT / "config/pricing.yaml"
    text_model: str = "gpt-6-luna"
    image_model: str = "gpt-image-2"
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
    creative_reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "high"
    max_output_tokens: int = Field(default=512, gt=0)
    timeout_seconds: float = Field(default=120, gt=0)
    image_timeout_seconds: float = Field(default=240, gt=0)
    image_quality: Literal["low", "medium", "high", "auto"] = "medium"
    image_size: str = "1024x1024"
    lease_seconds: int = Field(default=60, ge=10)
    heartbeat_seconds: int = Field(default=10, ge=1)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    api_key: SecretStr = SecretStr("")
    base_url: str | None = None


def load_settings(path: Path = ROOT / "config.yaml") -> Settings:
    import os

    values = yaml.safe_load(path.read_text()) or {}
    local = {**dotenv_values(ROOT / ".env"), **os.environ}
    values["api_key"] = local.get("OPENAI_API_KEY") or local.get("OPENAI_KEY") or ""
    values["base_url"] = local.get("OPENAI_BASE_URL") or None
    for key in ("data_root", "pricing_path"):
        if key in values:
            values[key] = (path.parent / values[key]).resolve()
    settings = Settings.model_validate(values)
    if settings.heartbeat_seconds * 2 >= settings.lease_seconds:
        raise ValueError("heartbeat must be less than half the lease duration")
    return settings
