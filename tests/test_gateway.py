import pytest

from editorial_studio.contracts.models import (
    AttemptRecord,
    AttemptState,
    ProviderCallRecord,
    StrictModel,
    UsageRecord,
)
from editorial_studio.llm.contracts import (
    GeneratedImage,
    ImageRequest,
    ProgressUpdate,
    ProviderFailure,
    ProviderResult,
    TextRequest,
)
from editorial_studio.llm.gateway import Gateway, InvalidModelOutput, UnreconciledCall
from editorial_studio.telemetry.redaction import Redactor


def request():
    return TextRequest(
        model="gpt-6-luna",
        prompt="Describe editorial restraint.",
        reasoning_effort="medium",
        max_output_tokens=512,
    )


def test_reasoning_call_is_logged_before_dispatch_and_usage_is_preserved(
    store, pricing, context, text_result, provider_factory
):
    provider = provider_factory([text_result])

    def check_before_dispatch(req, progress):
        attempts = store.list("attempt", AttemptRecord)
        assert len(attempts) == 1 and attempts[0].state == AttemptState.SUBMITTING
        calls = store.list("call", ProviderCallRecord)
        assert len(calls) == 1 and calls[0].status == "queued"

    provider.on_execute = check_before_dispatch
    result = Gateway(store, provider, pricing).invoke(context, request())
    call = store.get("call", result.call_id, ProviderCallRecord)
    assert call.usage == text_result.usage
    assert call.reasoning_effort == "medium"
    assert call.model_snapshot == "gpt-6-luna"
    assert call.cost.estimated_cost_usd == pytest.approx((80 * 0.1 + 20 * 0.01 + 50 * 0.5) / 1e6)
    assert call.latency_ms >= 0 and len(call.attempt_ids) == 1
    assert store.read_blob(context.project_id, call.request_payload_asset_id)
    assert store.read_blob(context.project_id, call.response_payload_asset_id)


def test_cache_reuse_does_not_rebill_or_recount_tokens(
    store, pricing, context, text_result, provider_factory
):
    provider = provider_factory([text_result])
    gateway = Gateway(store, provider, pricing)
    first = gateway.invoke(context, request())
    second = gateway.invoke(context, request())
    reuse = store.get("call", second.call_id, ProviderCallRecord)
    assert first.visible_text == second.visible_text
    assert second.cache_hit and provider.calls == 1
    assert reuse.parent_call_id == first.call_id
    assert reuse.usage is None and reuse.cost.estimated_cost_usd == 0
    assert reuse.attempt_ids == []


def test_cache_is_scoped_to_project_and_provider(
    store, pricing, context, text_result, provider_factory
):
    provider = provider_factory([text_result, text_result, text_result])
    gateway = Gateway(store, provider, pricing)
    gateway.invoke(context, request())
    gateway.invoke(context.model_copy(update={"project_id": "other"}), request())
    provider.namespace = "other-provider"
    gateway.invoke(context, request())
    assert provider.calls == 3


def test_image_call_records_artifact_and_available_usage(store, pricing, context, provider_factory):
    usage = UsageRecord(
        input_tokens=7,
        output_tokens=10,
        text_input_tokens=7,
        image_input_tokens=0,
        image_output_tokens=10,
    )
    provider = provider_factory(
        [
            ProviderResult(
                request_id="image_request",
                usage=usage,
                images=[GeneratedImage(data=b"image-bytes")],
            )
        ]
    )
    result = Gateway(store, provider, pricing).invoke(
        context, ImageRequest(model="gpt-image-2", prompt="A black circle.", quality="medium")
    )
    call = store.get("call", result.call_id, ProviderCallRecord)
    assert call.api_operation == "images.generate" and call.image_quality == "medium"
    assert call.usage == usage and call.cost.estimated_cost_usd is None
    assert store.read_blob(context.project_id, result.generated_artifact_ids[0]) == b"image-bytes"


def test_unknown_usage_remains_null(store, pricing, context, provider_factory):
    provider = provider_factory([ProviderResult(visible_text="done")])
    result = Gateway(store, provider, pricing).invoke(context, request())
    call = store.get("call", result.call_id, ProviderCallRecord)
    assert call.usage is None and call.cost.certainty.value == "unknown"
    assert call.cost.estimated_cost_usd is None


def test_ambiguous_timeout_is_not_replayed(store, pricing, context, provider_factory):
    provider = provider_factory([ProviderFailure("lost response", ambiguous=True)])
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(ProviderFailure):
        gateway.invoke(context, request())
    with pytest.raises(UnreconciledCall):
        gateway.invoke(context, request())
    call = store.list("call", ProviderCallRecord)[0]
    assert call.status == "ambiguous" and call.cost.billing_uncertain
    assert call.cost.estimated_cost_usd is None and provider.calls == 1
    with pytest.raises(UnreconciledCall, match="manual provider reconciliation"):
        gateway.reconcile(call.call_id)


def test_known_response_is_retrieved_after_lost_stream(
    store, pricing, context, provider_factory, text_result
):
    provider = provider_factory([ProviderFailure("lost stream", ambiguous=True)])
    provider.on_execute = lambda req, progress: progress(ProgressUpdate(response_id="resp_1"))
    provider.recovered = text_result
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(ProviderFailure):
        gateway.invoke(context, request())
    call = store.list("call", ProviderCallRecord)[0]
    result = gateway.reconcile(call.call_id)
    recovered = store.get("call", result.call_id, ProviderCallRecord)
    assert provider.calls == 1 and provider.retrievals == 1
    assert recovered.status == "completed" and not recovered.cost.billing_uncertain
    assert recovered.usage == text_result.usage


def test_safe_retry_links_attempts_to_one_logical_call(
    store, pricing, context, provider_factory, text_result
):
    provider = provider_factory([ProviderFailure("rate limited", retryable=True), text_result])
    result = Gateway(store, provider, pricing).invoke(context, request())
    calls = store.list("call", ProviderCallRecord)
    attempts = store.list("attempt", AttemptRecord)
    assert len(calls) == 1 and calls[0].call_id == result.call_id
    assert len(attempts) == 2 and len(calls[0].attempt_ids) == 2
    assert {a.state for a in attempts} == {AttemptState.FAILED, AttemptState.COMPLETED}


def test_streaming_is_provisional_until_authoritative_usage(
    store, pricing, context, provider_factory, text_result
):
    from editorial_studio.llm.gateway import ProvisionalText

    provider = provider_factory([text_result])

    def stream(req, progress):
        progress(ProgressUpdate(response_id="resp_1"))
        progress(ProgressUpdate(text_delta="Restraint "))
        progress(ProgressUpdate(text_delta="creates emphasis."))
        call = store.list("call", ProviderCallRecord)[0]
        assert call.status == "streaming" and call.usage is None
        assert call.cost.estimated_cost_usd is None
        assert store.get("partial", call.call_id, ProvisionalText).provisional

    provider.on_execute = stream
    result = Gateway(store, provider, pricing).invoke(context, request())
    final = store.get("call", result.call_id, ProviderCallRecord)
    assert final.status == "completed" and final.usage == text_result.usage
    assert len(store.list("call", ProviderCallRecord)) == 1


def test_recovery_marks_submitting_ambiguous_without_a_new_call(
    store, pricing, context, provider_factory, text_result
):
    provider = provider_factory([text_result])

    def kill(req, progress):
        raise KeyboardInterrupt()

    provider.on_execute = kill
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(KeyboardInterrupt):
        gateway.invoke(context, request())
    attempt = store.list("attempt", AttemptRecord)[0]
    attempt.state = AttemptState.SUBMITTING  # emulate SIGKILL before the exception handler
    store.put_records(("attempt", attempt.attempt_id, context.project_id, attempt))
    assert gateway.recover_submitting() == 1
    assert gateway.recover_submitting() == 0
    with pytest.raises(UnreconciledCall):
        gateway.invoke(context, request())
    assert provider.calls == 1


def test_secrets_are_redacted_in_payloads_and_error_metadata(
    store, pricing, context, provider_factory
):
    secret = "private-test-secret-1234"
    provider = provider_factory(
        [
            ProviderResult(
                visible_text=f"Result {secret}",
                raw_usage={
                    "api_key": secret,
                    "authorization": f"Bearer {secret}",
                    "nested": {"note": secret},
                    "chain_of_thought": "hidden",
                },
            )
        ]
    )
    gateway = Gateway(store, provider, pricing, Redactor([secret]))
    result = gateway.invoke(context, request().model_copy(update={"prompt": f"Prompt {secret}"}))
    call = store.get("call", result.call_id, ProviderCallRecord)
    assert secret not in result.visible_text
    for asset_id in [call.request_payload_asset_id, call.response_payload_asset_id]:
        data = store.read_blob(context.project_id, asset_id).decode()
        assert secret not in data and "hidden" not in data
        assert "[REDACTED]" in data


def test_invalid_structured_agent_output_is_logged_and_never_acted_on(
    store, pricing, context, provider_factory
):
    class Plan(StrictModel):
        title: str

    provider = provider_factory([ProviderResult(visible_text='{"title":"ok","arbitrary":"bad"}')])
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(InvalidModelOutput):
        gateway.invoke(context, request(), output_model=Plan)
    call = store.list("call", ProviderCallRecord)[0]
    assert call.status == "failed" and call.validation_errors
    assert store.list("attempt", AttemptRecord)[0].state == AttemptState.COMPLETED


def test_incomplete_response_is_not_cached(store, pricing, context, provider_factory):
    provider = provider_factory([ProviderResult(visible_text="unfinished", status="incomplete")])
    with pytest.raises(InvalidModelOutput):
        Gateway(store, provider, pricing).invoke(context, request())
    assert store.list("call", ProviderCallRecord)[0].status == "failed"


def test_reconciliation_revalidates_persisted_agent_schema(
    store, pricing, context, provider_factory
):
    class Plan(StrictModel):
        title: str

    provider = provider_factory([ProviderFailure("lost stream", ambiguous=True)])
    provider.on_execute = lambda req, progress: progress(ProgressUpdate(response_id="resp_1"))
    provider.recovered = ProviderResult(visible_text='{"other":"invalid"}')
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(ProviderFailure):
        gateway.invoke(context, request(), output_model=Plan)
    call = store.list("call", ProviderCallRecord)[0]
    with pytest.raises(InvalidModelOutput):
        gateway.reconcile(call.call_id)
    assert store.get("call", call.call_id, ProviderCallRecord).validation_errors
    assert provider.calls == 1 and provider.retrievals == 1


def test_reconciliation_cannot_cross_project_boundary(store, pricing, context, provider_factory):
    provider = provider_factory([ProviderFailure("lost stream", ambiguous=True)])
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(ProviderFailure):
        gateway.invoke(context, request())
    call = store.list("call", ProviderCallRecord)[0]
    with pytest.raises(PermissionError):
        gateway.reconcile(call.call_id, project_id="other")
    assert provider.retrievals == 0


def test_streamed_secret_is_redacted_across_chunk_boundaries(
    store, pricing, context, provider_factory
):
    from editorial_studio.llm.contracts import ProvisionalText

    secret = "private-secret-1234567"
    provider = provider_factory([ProviderResult(visible_text=secret)])

    def stream(req, progress):
        progress(ProgressUpdate(text_delta=secret[:8]))
        call = store.list("call", ProviderCallRecord)[0]
        assert secret[:8] not in store.get("partial", call.call_id, ProvisionalText).text
        progress(ProgressUpdate(text_delta=secret[8:]))
        assert secret not in store.get("partial", call.call_id, ProvisionalText).text

    provider.on_execute = stream
    Gateway(store, provider, pricing, Redactor([secret])).invoke(context, request())


def test_recovered_normative_output_uses_pydantic_cross_field_validators(
    store, pricing, context, provider_factory
):
    from editorial_studio.contracts.models import SourceSpan

    provider = provider_factory([ProviderFailure("lost stream", ambiguous=True)])
    provider.on_execute = lambda req, progress: progress(ProgressUpdate(response_id="resp_1"))
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(ProviderFailure):
        gateway.invoke(context, request(), output_model=SourceSpan)
    call = store.list("call", ProviderCallRecord)[0]
    provider.recovered = ProviderResult(
        visible_text=(
            '{"source_block_id":"b","source_revision_id":"r","start_char":4,"end_char":2}'
        )
    )
    # New gateway emulates process restart; no Python class from the original call is retained.
    restarted = Gateway(store, provider, pricing)
    with pytest.raises(InvalidModelOutput):
        restarted.reconcile(call.call_id)
    assert store.get("call", call.call_id, ProviderCallRecord).validation_errors
    assert provider.calls == provider.retrievals == 1
