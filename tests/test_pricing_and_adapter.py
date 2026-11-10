import pytest

from editorial_studio.contracts.models import UsageRecord
from editorial_studio.llm.provider import normalize_image_usage, normalize_text_usage
from editorial_studio.ui.telemetry import shown


def test_normalization_preserves_missing_data():
    assert normalize_text_usage(None) is None
    usage = normalize_text_usage({"input_tokens": 10, "output_tokens": 2})
    assert usage.cached_input_tokens is None and usage.reasoning_tokens is None
    assert shown(usage.reasoning_tokens) == "unknown"
    assert shown(0) == 0


def test_real_responses_usage_shape_is_normalized():
    raw = {
        "input_tokens": 100,
        "input_tokens_details": {"cached_tokens": 20},
        "output_tokens": 60,
        "output_tokens_details": {"reasoning_tokens": 40},
        "total_tokens": 160,
    }
    normalized = normalize_text_usage(raw)
    assert normalized.input_tokens == 100 and normalized.cached_input_tokens == 20
    assert normalized.output_tokens == 60 and normalized.reasoning_tokens == 40


def test_image_usage_is_split_without_total_overlap():
    normalized = normalize_image_usage(
        {
            "input_tokens": 15,
            "output_tokens": 20,
            "input_tokens_details": {"text_tokens": 10, "image_tokens": 5},
        }
    )
    assert normalized.text_input_tokens == 10 and normalized.image_input_tokens == 5
    assert normalized.image_output_tokens == 20 and normalized.cached_input_tokens is None


def test_subset_tokens_are_not_double_counted(pricing):
    usage = UsageRecord(
        input_tokens=1000, cached_input_tokens=400, output_tokens=200, reasoning_tokens=150
    )
    expected = (600 * 0.1 + 400 * 0.01 + 200 * 0.5) / 1e6
    assert pricing.estimate("gpt-6-luna", usage).estimated_cost_usd == pytest.approx(expected)


@pytest.mark.parametrize(
    "usage", [None, UsageRecord(input_tokens=5), UsageRecord(input_tokens=10, output_tokens=5)]
)
def test_missing_usage_cannot_manufacture_a_price(pricing, usage):
    assert pricing.estimate("gpt-6-luna", usage).estimated_cost_usd is None


def test_unknown_model_long_context_and_possible_charge_are_unknown(pricing):
    usage = UsageRecord(input_tokens=100, cached_input_tokens=0, output_tokens=20)
    assert pricing.estimate("unknown", usage).estimated_cost_usd is None
    assert pricing.estimate("gpt-6-luna", usage, uncertain=True).billing_uncertain
    long = UsageRecord(input_tokens=300000, cached_input_tokens=0, output_tokens=20)
    assert pricing.estimate("gpt-6-luna", long).estimated_cost_usd is None


def test_image_pricing_uses_only_nonoverlapping_modalities(pricing):
    usage = UsageRecord(
        input_tokens=100,
        cached_input_tokens=0,
        output_tokens=30,
        text_input_tokens=60,
        image_input_tokens=40,
        image_output_tokens=30,
    )
    cost = pricing.estimate("gpt-image-2", usage)
    assert cost.estimated_cost_usd == pytest.approx((60 * 2.5 + 40 * 4 + 30 * 15) / 1e6)


def test_cached_image_tokens_with_unknown_modality_split_have_unknown_price(pricing):
    usage = UsageRecord(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=30,
        text_input_tokens=60,
        image_input_tokens=40,
        image_output_tokens=30,
    )
    assert pricing.estimate("gpt-image-2", usage).estimated_cost_usd is None
