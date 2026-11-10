"""The only module allowed to invoke the external model SDK."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Protocol

import httpx
from openai import APIConnectionError, APIStatusError, OpenAI

from editorial_studio.contracts.models import UsageRecord
from editorial_studio.llm.contracts import (
    GeneratedImage,
    ImageRequest,
    ModelRequest,
    ProgressUpdate,
    ProviderFailure,
    ProviderResult,
    TextRequest,
)
from editorial_studio.settings import Settings

ProgressCallback = Callable[[ProgressUpdate], None]


class Provider(Protocol):
    namespace: str

    def execute(self, request: ModelRequest, progress: ProgressCallback) -> ProviderResult: ...
    def retrieve(self, response_id: str) -> ProviderResult: ...


def normalize_text_usage(raw: dict | None) -> UsageRecord | None:
    if raw is None:
        return None
    return UsageRecord(
        input_tokens=raw.get("input_tokens"),
        output_tokens=raw.get("output_tokens"),
        cached_input_tokens=(raw.get("input_tokens_details") or {}).get("cached_tokens"),
        cache_write_tokens=raw.get("cache_write_tokens"),
        reasoning_tokens=(raw.get("output_tokens_details") or {}).get("reasoning_tokens"),
    )


def normalize_image_usage(raw: dict | None) -> UsageRecord | None:
    if raw is None:
        return None
    details = raw.get("input_tokens_details") or {}
    return UsageRecord(
        input_tokens=raw.get("input_tokens"),
        output_tokens=raw.get("output_tokens"),
        text_input_tokens=details.get("text_tokens"),
        image_input_tokens=details.get("image_tokens"),
        image_output_tokens=raw.get("output_tokens"),
        cached_input_tokens=details.get("cached_tokens"),
    )


def response_result(response) -> ProviderResult:
    raw = response.model_dump(mode="json")
    summaries = [
        part["text"]
        for item in raw.get("output", [])
        if item.get("type") == "reasoning"
        for part in item.get("summary", [])
        if part.get("type") == "summary_text"
    ]
    return ProviderResult(
        response_id=response.id,
        request_id=getattr(response, "_request_id", None),
        model_snapshot=response.model,
        visible_text=response.output_text,
        usage=normalize_text_usage(raw.get("usage")),
        raw_usage=raw.get("usage"),
        visible_summary="\n".join(summaries) or None,
        status="completed" if raw.get("status") == "completed" else "incomplete",
    )


class OpenAIProvider:
    def __init__(self, settings: Settings):
        if not settings.api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY or OPENAI_KEY is required")
        self.client = OpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            max_retries=0,
            timeout=settings.timeout_seconds,
        )
        # Scope caches to endpoint AND account, without storing credentials.
        import hashlib

        identity = str(self.client.base_url) + settings.api_key.get_secret_value()
        self.namespace = hashlib.sha256(identity.encode()).hexdigest()
        self.image_timeout = settings.image_timeout_seconds

    def execute(self, request: ModelRequest, progress: ProgressCallback) -> ProviderResult:
        try:
            if isinstance(request, TextRequest):
                model_input = request.prompt
                if request.images:
                    model_input = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": request.prompt},
                                *[
                                    {
                                        "type": "input_image",
                                        "image_url": f"data:{item.media_type};base64,{item.data_base64}",
                                        "detail": item.detail,
                                    }
                                    for item in request.images
                                ],
                            ],
                        }
                    ]
                text_settings = {}
                if request.output_schema is not None:
                    text_settings = {
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": "agent_output",
                                "strict": True,
                                "schema": request.output_schema,
                            }
                        }
                    }
                terminal = None
                with self.client.responses.create(
                    model=request.model,
                    input=model_input,
                    reasoning={"effort": request.reasoning_effort},
                    max_output_tokens=request.max_output_tokens,
                    stream=True,
                    store=True,
                    **text_settings,
                ) as stream:
                    for event in stream:
                        if event.type == "response.created":
                            progress(
                                ProgressUpdate(
                                    response_id=event.response.id,
                                    provider_request_id=stream.response.headers.get("x-request-id"),
                                )
                            )
                        elif event.type == "response.output_text.delta":
                            progress(ProgressUpdate(text_delta=event.delta))
                        elif event.type in {
                            "response.completed",
                            "response.incomplete",
                            "response.failed",
                        }:
                            terminal = event.response
                if terminal is None:
                    raise ProviderFailure(
                        "Stream ended without an authoritative response", ambiguous=True
                    )
                result = response_result(terminal)
                result.request_id = stream.response.headers.get("x-request-id")
                return result
            if isinstance(request, ImageRequest):
                method = self.client.images.edit if request.images else self.client.images.generate
                image_args = (
                    {
                        "image": [
                            (
                                f"reference-{n}.png",
                                base64.b64decode(item.data_base64, validate=True),
                                item.media_type,
                            )
                            for n, item in enumerate(request.images)
                        ]
                    }
                    if request.images
                    else {}
                )
                response = method(
                    model=request.model,
                    prompt=request.prompt,
                    quality=request.quality,
                    size=request.size,
                    n=1,
                    output_format="png",
                    timeout=self.image_timeout,
                    **image_args,
                )
                raw = response.model_dump(mode="json")
                images = []
                for item in response.data or []:
                    if not item.b64_json:
                        raise ProviderFailure(
                            "Provider returned no base64 image; no URL fallback",
                            ambiguous=True,
                            request_id=getattr(response, "_request_id", None),
                        )
                    images.append(
                        GeneratedImage(data=base64.b64decode(item.b64_json, validate=True))
                    )
                if not images:
                    raise ProviderFailure("Image response contained no images", ambiguous=True)
                return ProviderResult(
                    request_id=getattr(response, "_request_id", None),
                    images=images,
                    usage=normalize_image_usage(raw.get("usage")),
                    raw_usage=raw.get("usage"),
                )
            raise ValueError("unsupported request type")
        except APIConnectionError as error:
            # Connect failures precede HTTP submission. Read/write failures can
            # follow it, so only those remain potentially billable.
            not_submitted = isinstance(error.__cause__, (httpx.ConnectError, httpx.ConnectTimeout))
            raise ProviderFailure(str(error), ambiguous=not not_submitted) from error
        except APIStatusError as error:
            # Only rate limiting is safely retryable here. 5xx may follow submission.
            raise ProviderFailure(
                str(error),
                ambiguous=error.status_code >= 500,
                retryable=error.status_code == 429,
                request_id=error.request_id,
            ) from error

    def retrieve(self, response_id: str) -> ProviderResult:
        try:
            return response_result(self.client.responses.retrieve(response_id))
        except (APIConnectionError, APIStatusError) as error:
            raise ProviderFailure(
                str(error), ambiguous=True, request_id=getattr(error, "request_id", None)
            ) from error
