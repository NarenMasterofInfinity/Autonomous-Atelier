"""Explicit, small live API checks. All calls pass through the durable gateway."""

import argparse
from uuid import uuid4

from editorial_studio.core.jobs import Command, ModelCommand, Queue, worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import ImageRequest, TextRequest
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor
from editorial_studio.worker import process_one


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["text", "image", "both"], default="text")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    queue = Queue(store)
    with worker_lock(store):
        gateway = Gateway(
            store,
            OpenAIProvider(settings),
            PricingTable.load(settings.pricing_path),
            Redactor([settings.api_key.get_secret_value()]),
        )
        gateway.recover_submitting()
        requests = []
        if args.kind in {"text", "both"}:
            requests.append(
                TextRequest(
                    model=settings.text_model,
                    prompt="Reply with one short sentence describing editorial restraint.",
                    reasoning_effort=settings.reasoning_effort,
                    max_output_tokens=settings.max_output_tokens,
                )
            )
        if args.kind in {"image", "both"}:
            requests.append(
                ImageRequest(
                    model=settings.image_model,
                    prompt="A single black circle on a warm ivory background. No text.",
                    quality=settings.image_quality,
                    size=settings.image_size,
                )
            )
        for request in requests:
            command = Command(project_id="m0-smoke", payload=ModelCommand(request=request))
            queue.submit(command)
            # Drain only while this command remains queued, using the normal worker path.
            while next(j for j in queue.list() if j.command.id == command.id).status == "queued":
                process_one(queue, gateway, uuid4().hex, settings)
            job = next(j for j in queue.list() if j.command.id == command.id)
            print(f"{request.kind}: {job.status}; job={command.id}", flush=True)
            if job.error:
                print(gateway.redactor.text(job.error), flush=True)
        if any(j.status != "completed" for j in queue.list("m0-smoke")):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
