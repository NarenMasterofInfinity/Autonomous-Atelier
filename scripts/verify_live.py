"""Explicit live acceptance run; preserves historical ambiguous calls without replaying them."""

from uuid import uuid4

from editorial_studio.contracts.models import ConceptBrief, ProviderCallRecord
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import CallContext, ImageRequest, TextRequest
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    settings = load_settings()
    store = Store(settings.data_root)
    with worker_lock(store):
        gateway = Gateway(
            store,
            OpenAIProvider(settings),
            PricingTable.load(settings.pricing_path),
            Redactor([settings.api_key.get_secret_value()]),
        )
        context = CallContext(
            project_id="m0-live",
            run_id=uuid4().hex,
            agent_name="AcceptanceVerifier",
            stage="M0",
            prompt_version="m0-live-v1",
        )
        text_request = TextRequest(
            model=settings.text_model,
            reasoning_effort=settings.reasoning_effort,
            max_output_tokens=1024,
            prompt=(
                "Create a concise ConceptBrief for project m0-live, spread proof-spread. "
                "Story: Quiet rooms and afternoon light reveal the beauty of ordinary spaces. "
                "Use restrained typography and an architectural photograph. Return the requested JSON."
            ),
        )
        text = gateway.invoke(context, text_request, output_model=ConceptBrief)
        print("Reasoning call:", text.call_id, "cache_hit:", text.cache_hit, flush=True)
        image_request = ImageRequest(
            model=settings.image_model,
            quality=settings.image_quality,
            size=settings.image_size,
            prompt=(
                "An editorial architectural photograph of an empty ivory plaster room, "
                "one arched doorway, afternoon sunlight forming a diagonal shadow, "
                "warm neutral colors, quiet atmosphere. No text, no people."
            ),
        )
        image = gateway.invoke(context, image_request)
        print("Image call:", image.call_id, "assets:", image.generated_artifact_ids, flush=True)
        reuse = gateway.invoke(context, text_request, output_model=ConceptBrief)
        assert reuse.cache_hit
        for call_id in [text.call_id, image.call_id, reuse.call_id]:
            call = store.get("call", call_id, ProviderCallRecord)
            print(call.model_dump_json(exclude={"visible_decision_summary"}), flush=True)
        print("LIVE_ACCEPTANCE_PASSED", flush=True)


if __name__ == "__main__":
    main()
