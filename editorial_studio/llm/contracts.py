from typing import Annotated, Literal

from pydantic import Field, JsonValue

from editorial_studio.contracts.models import StrictModel, UsageRecord


class CallContext(StrictModel):
    project_id: str
    run_id: str
    agent_name: str
    stage: str
    spread_id: str | None = None
    parent_call_id: str | None = None
    prompt_version: str = "m0-v1"
    schema_version: str = "v6"


class ImageInput(StrictModel):
    asset_id: str
    data_base64: str = Field(min_length=1)
    media_type: Literal["image/png", "image/jpeg", "image/webp"] = "image/png"
    detail: Literal["auto", "low", "high"] = "high"


class TextRequest(StrictModel):
    kind: Literal["text"] = "text"
    model: str
    prompt: str
    reasoning_effort: Literal["low", "medium", "high", "xhigh"]
    max_output_tokens: int = Field(gt=0)
    output_schema: JsonValue | None = None
    output_contract: str | None = None
    images: list[ImageInput] = Field(default_factory=list, max_length=12)


class ImageRequest(StrictModel):
    kind: Literal["image"] = "image"
    model: str
    prompt: str
    quality: Literal["low", "medium", "high", "auto"] = "medium"
    size: str = "1024x1024"
    images: list[ImageInput] = Field(default_factory=list, max_length=8)
    # No provider 'complexity' parameter exists in the verified SDK.


ModelRequest = Annotated[TextRequest | ImageRequest, Field(discriminator="kind")]


class GeneratedImage(StrictModel):
    data: bytes
    media_type: str = "image/png"


class ProviderResult(StrictModel):
    response_id: str | None = None
    request_id: str | None = None
    model_snapshot: str | None = None
    visible_text: str = ""
    usage: UsageRecord | None = None
    images: list[GeneratedImage] = Field(default_factory=list)
    raw_usage: JsonValue | None = None
    # Only visible output and explicitly returned summaries, never encrypted reasoning.
    visible_summary: str | None = None
    status: Literal["completed", "incomplete", "failed"] = "completed"


class ProgressUpdate(StrictModel):
    response_id: str | None = None
    provider_request_id: str | None = None
    text_delta: str = ""


class ProviderCheckpoint(StrictModel):
    response_id: str
    call_id: str
    attempt_id: str


class ProvisionalText(StrictModel):
    call_id: str
    text: str = ""
    provisional: bool = True


class StoredResponse(StrictModel):
    result: ProviderResult
    generated_artifact_ids: list[str] = Field(default_factory=list)


class GatewayResult(StrictModel):
    call_id: str
    visible_text: str
    generated_artifact_ids: list[str]
    cache_hit: bool


class ProviderFailure(Exception):
    def __init__(
        self,
        message: str,
        *,
        ambiguous: bool = False,
        retryable: bool = False,
        request_id: str | None = None,
    ):
        super().__init__(message)
        self.ambiguous = ambiguous
        self.retryable = retryable
        self.request_id = request_id
