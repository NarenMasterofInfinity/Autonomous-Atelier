"""Durable logical calls, explicit attempts, scoped cache and reconciliation."""

from __future__ import annotations

import base64
import hashlib
import json
from time import monotonic
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from editorial_studio.contracts import models
from editorial_studio.contracts.models import (
    AttemptRecord,
    AttemptState,
    CallEvent,
    ProviderCallRecord,
    WorkflowEvent,
)
from editorial_studio.core.storage import Store, utcnow
from editorial_studio.llm.contracts import (
    CallContext,
    GatewayResult,
    ImageRequest,
    ModelRequest,
    ProgressUpdate,
    ProviderCheckpoint,
    ProviderFailure,
    ProviderResult,
    ProvisionalText,
    StoredResponse,
    TextRequest,
)
from editorial_studio.llm.provider import Provider
from editorial_studio.llm.schema import strict_schema
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


class UnreconciledCall(RuntimeError):
    pass


class InvalidModelOutput(ValueError):
    pass


class Gateway:
    def __init__(
        self,
        store: Store,
        provider: Provider,
        pricing: PricingTable,
        redactor: Redactor | None = None,
    ):
        self.store, self.provider, self.pricing = store, provider, pricing
        self.redactor = redactor or Redactor()
        from editorial_studio.creative import issue_models, tournament_models
        from editorial_studio.creative import models as creative_models

        self.output_contracts = {
            f"{cls.__module__}.{cls.__qualname__}": cls
            for module in (models, creative_models, tournament_models, issue_models)
            for cls in vars(module).values()
            if isinstance(cls, type)
            and issubclass(cls, BaseModel)
            and cls.__module__ == module.__name__
        }

    def event(self, call: ProviderCallRecord, status: str, attempt_id: str | None = None):
        return WorkflowEvent(
            event_id=uuid4().hex,
            project_id=call.project_id,
            run_id=call.run_id,
            spread_id=call.spread_id,
            timestamp=utcnow(),
            payload=CallEvent(call_id=call.call_id, attempt_id=attempt_id, new_status=status),
        )

    def persist(self, call: ProviderCallRecord, attempt: AttemptRecord | None = None):
        call = ProviderCallRecord.model_validate(self.redactor.clean(call.model_dump(mode="json")))
        if attempt:
            attempt = AttemptRecord.model_validate(
                self.redactor.clean(attempt.model_dump(mode="json"))
            )
        event = self.event(call, call.status, attempt.attempt_id if attempt else None)
        entries = [
            ("call", call.call_id, call.project_id, call),
            ("event", event.event_id, call.project_id, event),
        ]
        if attempt:
            entries.append(("attempt", attempt.attempt_id, call.project_id, attempt))
        self.store.put_records(*entries)

    def payload(self, project_id: str, model: BaseModel) -> str:
        value = self.redactor.clean(model.model_dump(mode="json"))
        return self.store.put_blob(
            project_id, json.dumps(value, sort_keys=True).encode(), "application/json"
        ).id

    def invoke(
        self,
        context: CallContext,
        request: ModelRequest,
        *,
        output_model: type[BaseModel] | None = None,
        max_attempts: int = 2,
    ) -> GatewayResult:
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        for image in request.images:
            asset = self.store.asset(context.project_id, image.asset_id)
            data = base64.b64decode(image.data_base64, validate=True)
            if (
                asset.sha256 != hashlib.sha256(data).hexdigest()
                or asset.media_type != image.media_type
            ):
                raise ValueError(
                    "model image input differs from its project-scoped immutable asset"
                )
        if output_model:
            if not isinstance(request, TextRequest):
                raise ValueError("structured output requires a text request")
            contract_id = f"{output_model.__module__}.{output_model.__qualname__}"
            self.output_contracts[contract_id] = output_model
            request = request.model_copy(
                update={
                    "output_schema": strict_schema(output_model),
                    "output_contract": contract_id,
                }
            )
        elif isinstance(request, TextRequest) and request.output_schema is not None:
            # A raw JSON Schema is not sufficient for Pydantic cross-field validators.
            if request.output_contract not in self.output_contracts:
                raise ValueError("structured output must name a registered Pydantic contract")
            output_model = self.output_contracts[request.output_contract]
            if request.output_schema != strict_schema(output_model):
                raise ValueError("output schema differs from the registered contract")
        # Hash original content; redaction collisions must never share a cache entry.
        material = json.dumps(
            {
                "provider": self.provider.namespace,
                "project": context.project_id,
                "request": request.model_dump(mode="json"),
                "prompt_version": context.prompt_version,
                "schema_version": context.schema_version,
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(material.encode()).hexdigest()
        prior = [
            c
            for c in self.store.list("call", ProviderCallRecord, context.project_id)
            if c.request_hash == digest and not c.cache_hit
        ]
        pending = [
            c for c in prior if c.status in {"ambiguous", "streaming", "queued", "cancelled"}
        ]
        if pending:
            raise UnreconciledCall(
                f"Call {pending[-1].call_id} requires reconciliation; not replayed"
            )
        call = ProviderCallRecord(
            call_id=uuid4().hex,
            **context.model_dump(exclude={"parent_call_id"}),
            parent_call_id=context.parent_call_id,
            provider="openai",
            api_operation="responses.create"
            if isinstance(request, TextRequest)
            else "images.edit"
            if request.images
            else "images.generate",
            model_requested=request.model,
            reasoning_effort=request.reasoning_effort if isinstance(request, TextRequest) else None,
            image_quality=request.quality if isinstance(request, ImageRequest) else None,
            request_hash=digest,
            attempt_ids=[],
            status="queued",
            started_at=utcnow(),
            cost=self.pricing.estimate(request.model, None),
        )
        call.request_payload_asset_id = self.payload(context.project_id, request)
        completed = [c for c in prior if c.status == "completed"]
        if completed:
            original = completed[-1]
            # Verify response and images exist before reuse. A missing blob never causes a paid replay.
            stored = StoredResponse.model_validate_json(
                self.store.read_blob(context.project_id, original.response_payload_asset_id)
            )
            for asset_id in original.generated_artifact_ids:
                self.store.read_blob(context.project_id, asset_id)
            call.cache_hit, call.parent_call_id = True, original.call_id
            call.response_payload_asset_id = original.response_payload_asset_id
            call.generated_artifact_ids = original.generated_artifact_ids
            call.model_snapshot = original.model_snapshot
            call.status, call.ended_at, call.latency_ms = "completed", utcnow(), 0
            call.cost = self.pricing.estimate(request.model, None, reuse=True)
            self.persist(call)
            return GatewayResult(
                call_id=call.call_id,
                visible_text=stored.result.visible_text,
                generated_artifact_ids=call.generated_artifact_ids,
                cache_hit=True,
            )
        started = monotonic()
        for _ in range(max_attempts):
            attempt = AttemptRecord(
                attempt_id=uuid4().hex,
                call_id=call.call_id,
                request_hash=digest,
                state=AttemptState.SUBMITTING,
                model_snapshot=request.model,
                reconciliation_status="pending",
                submitted_at=utcnow(),
            )
            call.attempt_ids.append(attempt.attempt_id)
            # Atomic call+attempt+event write BEFORE any SDK action.
            self.persist(call, attempt)

            partial = ProvisionalText(call_id=call.call_id)
            raw_chunks = []

            def progress(
                update: ProgressUpdate, attempt=attempt, partial=partial, raw_chunks=raw_chunks
            ):
                if update.provider_request_id:
                    attempt.provider_request_id = self.redactor.text(update.provider_request_id)
                if update.response_id:
                    # Responses IDs are retrievable; HTTP request IDs are metadata only.
                    checkpoint = ProviderCheckpoint(
                        response_id=update.response_id,
                        call_id=call.call_id,
                        attempt_id=attempt.attempt_id,
                    )
                    self.store.put_records(
                        ("checkpoint", attempt.attempt_id, context.project_id, checkpoint)
                    )
                call.status = "streaming"
                # Partial text remains explicitly provisional, with no usage/cost.
                if update.text_delta:
                    raw_chunks.append(update.text_delta)
                    partial.text = self.redactor.provisional("".join(raw_chunks))
                    self.store.put_records(("partial", call.call_id, call.project_id, partial))
                self.persist(call, attempt)

            try:
                result = self.provider.execute(request, progress)
                self.finish(call, attempt, result, started, output_model=output_model)
                if result.status != "completed":
                    raise InvalidModelOutput(f"Provider response is {result.status}; not usable")
                return GatewayResult(
                    call_id=call.call_id,
                    visible_text=self.redactor.text(result.visible_text),
                    generated_artifact_ids=call.generated_artifact_ids,
                    cache_hit=False,
                )
            except InvalidModelOutput:
                raise
            except BaseException as error:
                ambiguous = not isinstance(error, ProviderFailure) or error.ambiguous
                attempt.state = (
                    AttemptState.CANCELLED_AFTER_SUBMIT
                    if isinstance(error, (KeyboardInterrupt, SystemExit))
                    else AttemptState.AMBIGUOUS
                    if ambiguous
                    else AttemptState.FAILED
                )
                attempt.ended_at = utcnow()
                attempt.provider_request_id = (
                    self.redactor.text(getattr(error, "request_id", "") or "") or None
                )
                attempt.reconciliation_status = "required" if ambiguous else "not_needed"
                call.status = "ambiguous" if ambiguous else "failed"
                call.ended_at, call.latency_ms = utcnow(), (monotonic() - started) * 1000
                call.error_summary = self.redactor.text(str(error))
                call.cost = self.pricing.estimate(request.model, None, uncertain=ambiguous)
                self.persist(call, attempt)
                if isinstance(error, ProviderFailure) and error.retryable and not ambiguous:
                    if len(call.attempt_ids) < max_attempts:
                        call.status, call.error_summary, call.ended_at = "queued", None, None
                        continue
                raise
        raise RuntimeError("unreachable")

    def finish(
        self,
        call: ProviderCallRecord,
        attempt: AttemptRecord,
        result: ProviderResult,
        started: float | None,
        *,
        output_model: type[BaseModel] | None = None,
    ):
        attempt.state, attempt.ended_at = AttemptState.COMPLETED, utcnow()
        attempt.provider_request_id = result.request_id
        attempt.reconciliation_status = "reconciled"
        attempt.model_snapshot = result.model_snapshot or call.model_requested
        call.model_snapshot, call.usage = result.model_snapshot, result.usage
        call.visible_decision_summary = self.redactor.text(result.visible_summary or "") or None
        call.cost = self.pricing.estimate(call.model_requested, result.usage)
        # Unknown image cache semantics must not be presented as an exact estimate.
        call.generated_artifact_ids = [
            self.store.put_blob(call.project_id, img.data, img.media_type).id
            for img in result.images
        ]
        safe_result = result.model_copy(update={"images": []})
        call.response_payload_asset_id = self.payload(
            call.project_id,
            StoredResponse(result=safe_result, generated_artifact_ids=call.generated_artifact_ids),
        )
        if output_model:
            try:
                output_model.model_validate_json(result.visible_text)
            except ValidationError as error:
                # Do not log ValidationError input values; they can contain secrets.
                call.validation_errors = [
                    f"{'.'.join(map(str, e['loc']))}: {e['type']}"
                    for e in error.errors(include_input=False)
                ]
        else:
            # Recovery cannot rely on an in-memory Python class surviving a
            # worker restart. Revalidate the persisted declared JSON Schema.
            request_data = json.loads(
                self.store.read_blob(call.project_id, call.request_payload_asset_id)
            )
            schema = request_data.get("output_schema")
            if schema is not None:
                try:
                    value = json.loads(result.visible_text)
                    call.validation_errors = [
                        f"{'/'.join(map(str, error.path))}: {error.validator}"
                        for error in Draft202012Validator(schema).iter_errors(value)
                    ]
                    contract = self.output_contracts.get(request_data.get("output_contract"))
                    if not call.validation_errors:
                        if contract is None:
                            call.validation_errors = ["response: unavailable_output_contract"]
                        else:
                            try:
                                contract.model_validate_json(result.visible_text)
                            except ValidationError as error:
                                call.validation_errors = [
                                    f"{'.'.join(map(str, e['loc']))}: {e['type']}"
                                    for e in error.errors(include_input=False)
                                ]
                except (ValueError, TypeError):
                    call.validation_errors = ["response: invalid_json"]
        call.status = (
            "completed" if result.status == "completed" and not call.validation_errors else "failed"
        )
        call.ended_at = utcnow()
        call.latency_ms = (
            (monotonic() - started) * 1000
            if started is not None
            else max(0, (call.ended_at - call.started_at).total_seconds() * 1000)
        )
        if result.status != "completed":
            call.error_summary = f"Provider returned {result.status}"
        self.persist(call, attempt)
        if call.validation_errors:
            raise InvalidModelOutput("Agent response failed declared output schema")

    def recover_submitting(self) -> int:
        count = 0
        for attempt in self.store.list("attempt", AttemptRecord):
            if attempt.state != AttemptState.SUBMITTING:
                continue
            call = self.store.get("call", attempt.call_id, ProviderCallRecord)
            attempt.state, attempt.reconciliation_status = AttemptState.AMBIGUOUS, "required"
            call.status = "ambiguous"
            call.cost = self.pricing.estimate(call.model_requested, None, uncertain=True)
            call.error_summary = "Worker ended before authoritative completion was persisted"
            self.persist(call, attempt)
            count += 1
        return count

    def reconcile(self, call_id: str, *, project_id: str | None = None) -> GatewayResult:
        call = self.store.get("call", call_id, ProviderCallRecord)
        if call is not None and project_id is not None and call.project_id != project_id:
            raise PermissionError("call does not belong to this project")
        if call is None or call.status not in {"ambiguous", "cancelled"}:
            raise ValueError("call is not awaiting reconciliation")
        attempt = self.store.get("attempt", call.attempt_ids[-1], AttemptRecord)
        checkpoint = self.store.get("checkpoint", attempt.attempt_id, ProviderCheckpoint)
        if checkpoint is None:
            raise UnreconciledCall(
                "No retrievable response ID; manual provider reconciliation required"
            )
        result = self.provider.retrieve(checkpoint.response_id)
        if result.status != "completed":
            raise UnreconciledCall("Provider response is not completed; no new submission was made")
        self.finish(call, attempt, result, None)
        return GatewayResult(
            call_id=call_id,
            visible_text=self.redactor.text(result.visible_text),
            generated_artifact_ids=call.generated_artifact_ids,
            cache_hit=False,
        )
