"""Exercise the real SDK against independent HTTP/SSE fixtures, without paid requests."""

import base64
import json

import httpx
import pytest
from openai import OpenAI

from editorial_studio.llm.contracts import ImageRequest, ProviderFailure, TextRequest
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import Settings


def provider(handler):
    adapter = OpenAIProvider(Settings(api_key="unit-test-key"))
    adapter.client = OpenAI(
        api_key="unit-test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return adapter


def text_request():
    return TextRequest(
        model="gpt-6-luna", prompt="Test", reasoning_effort="medium", max_output_tokens=512
    )


@pytest.mark.parametrize(
    "error_type,ambiguous",
    [
        (httpx.ConnectError, False),
        (httpx.ConnectTimeout, False),
        (httpx.ReadTimeout, True),
        (httpx.ReadError, True),
    ],
)
def test_transport_failures_distinguish_presubmit_from_uncertain(error_type, ambiguous):
    def handler(request):
        raise error_type("transport failure", request=request)

    adapter = provider(handler)
    with pytest.raises(ProviderFailure) as caught:
        adapter.execute(text_request(), lambda update: None)
    assert caught.value.ambiguous == ambiguous


def test_sdk_does_not_silently_retry_5xx():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, json={"error": {"message": "server failure"}})

    with pytest.raises(ProviderFailure) as caught:
        provider(handler).execute(text_request(), lambda update: None)
    assert caught.value.ambiguous and len(calls) == 1


def test_real_sdk_stream_normalizes_usage_and_captures_request_id():
    response = {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6-luna",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_fixture",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Quiet.", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 3},
            "total_tokens": 15,
        },
    }
    events = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {**response, "status": "in_progress", "output": [], "usage": None},
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_fixture",
            "delta": "Quiet.",
        },
        {"type": "response.completed", "sequence_number": 2, "response": response},
    ]
    stream = "".join("data: " + json.dumps(e) + "\n\n" for e in events)

    def handler(request):
        body = json.loads(request.content)
        assert body["reasoning"]["effort"] == "medium"
        assert body["stream"] is True and body["model"] == "gpt-6-luna"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "x-request-id": "req_fixture"},
            text=stream,
        )

    updates = []
    result = provider(handler).execute(text_request(), updates.append)
    assert result.visible_text == "Quiet." and result.request_id == "req_fixture"
    assert result.usage.reasoning_tokens == 3 and result.usage.cached_input_tokens == 0
    assert (
        updates[0].response_id == "resp_fixture" and updates[0].provider_request_id == "req_fixture"
    )
    assert any(update.text_delta == "Quiet." for update in updates)


def test_real_sdk_image_response_is_decoded_and_usage_preserved():
    def handler(request):
        body = json.loads(request.content)
        assert body["quality"] == "medium" and "complexity" not in body
        return httpx.Response(
            200,
            headers={"x-request-id": "req_image"},
            json={
                "created": 1,
                "data": [{"b64_json": base64.b64encode(b"image fixture").decode()}],
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 10,
                    "total_tokens": 13,
                    "input_tokens_details": {"text_tokens": 3, "image_tokens": 0},
                },
            },
        )

    result = provider(handler).execute(
        ImageRequest(model="gpt-image-2", prompt="Circle"), lambda u: None
    )
    assert result.images[0].data == b"image fixture" and result.request_id == "req_image"
    assert result.usage.image_output_tokens == 10 and result.usage.image_input_tokens == 0


def test_image_edit_uses_real_sdk_multipart_reference_bytes():
    from editorial_studio.llm.contracts import ImageInput

    raw = b"fixture reference bytes"

    def handler(request):
        assert request.url.path.endswith("/images/edits")
        assert "multipart/form-data" in request.headers["content-type"]
        assert raw in request.content and b"gpt-image-2" in request.content
        return httpx.Response(
            200,
            json={"created": 1, "data": [{"b64_json": base64.b64encode(b"edited image").decode()}]},
        )

    result = provider(handler).execute(
        ImageRequest(
            model="gpt-image-2",
            prompt="One motif",
            images=[ImageInput(asset_id="source", data_base64=base64.b64encode(raw).decode())],
        ),
        lambda update: None,
    )
    assert result.images[0].data == b"edited image"


def test_vision_inputs_use_responses_content_blocks():
    from editorial_studio.llm.contracts import ImageInput

    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        assert body["input"][0]["content"][1]["type"] == "input_image"
        assert body["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")
        response = {
            "id": "resp_vision",
            "object": "response",
            "created_at": 1,
            "model": "gpt-6-luna",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "A circle.", "annotations": []}],
                }
            ],
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="data: "
            + json.dumps({"type": "response.completed", "sequence_number": 0, "response": response})
            + "\n\n",
        )

    request = text_request()
    request.images = [
        ImageInput(asset_id="source", data_base64=base64.b64encode(b"image").decode())
    ]
    result = provider(handler).execute(request, lambda update: None)
    assert result.visible_text == "A circle." and len(captured) == 1
