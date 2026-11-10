from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from editorial_studio.contracts.models import CostCertainty, CostRecord, StrictModel, UsageRecord


class ModelRates(StrictModel):
    modality: Literal["text", "image"]
    input: float | None = Field(default=None, ge=0)
    cached_input: float | None = Field(default=None, ge=0)
    output: float | None = Field(default=None, ge=0)
    cache_write: float | None = Field(default=None, ge=0)
    text_input: float | None = Field(default=None, ge=0)
    image_input: float | None = Field(default=None, ge=0)
    image_output: float | None = Field(default=None, ge=0)
    max_standard_input_tokens: int | None = None


class PricingTable(StrictModel):
    version: str
    verified_at: str
    source_urls: list[str]
    models: dict[str, ModelRates]

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(yaml.safe_load(path.read_text()))

    def estimate(
        self, model: str, usage: UsageRecord | None, *, reuse: bool = False, uncertain: bool = False
    ) -> CostRecord:
        unknown = CostRecord(
            certainty=CostCertainty.UNKNOWN,
            pricing_version=self.version,
            billing_uncertain=uncertain,
        )
        if reuse:
            return CostRecord(
                certainty=CostCertainty.ESTIMATED,
                pricing_version=self.version,
                estimated_cost_usd=0,
            )
        rate = self.models.get(model)
        if usage is None or rate is None or uncertain:
            return unknown
        parts = []
        if rate.modality == "text":
            if (
                usage.input_tokens is None
                or usage.output_tokens is None
                or usage.cached_input_tokens is None
            ):
                return unknown
            if (
                rate.max_standard_input_tokens
                and usage.input_tokens > rate.max_standard_input_tokens
            ):
                return unknown
            if rate.input is None or rate.output is None or rate.cached_input is None:
                return unknown
            parts.extend(
                [
                    (usage.input_tokens - usage.cached_input_tokens) * rate.input,
                    usage.cached_input_tokens * rate.cached_input,
                    usage.output_tokens * rate.output,
                ]
            )
        else:
            # Modality token counts are non-overlapping. Never also add total input/output.
            for count, price in [
                (usage.text_input_tokens, rate.text_input),
                (usage.image_input_tokens, rate.image_input),
                (usage.image_output_tokens, rate.image_output),
            ]:
                if count is None or price is None:
                    return unknown
                parts.append(count * price)
            if usage.cached_input_tokens is None or usage.cached_input_tokens:
                # Missing cache counts are unknown; v6 lacks per-modality cached subsets.
                return unknown
        if usage.cache_write_tokens:
            if rate.cache_write is None:
                return unknown
            parts.append(usage.cache_write_tokens * rate.cache_write)
        return CostRecord(
            certainty=CostCertainty.ESTIMATED,
            pricing_version=self.version,
            estimated_cost_usd=sum(parts) / 1_000_000,
        )
