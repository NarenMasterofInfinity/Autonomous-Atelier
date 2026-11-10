"""Reconcile the selected opening mandate and review physical facing-page evidence."""

from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.issue import revise_issue
from editorial_studio.creative.issue_models import IssueCorrection, IssueResult
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    settings = load_settings()
    store = Store(settings.data_root)
    context = CallContext(
        project_id="m8-proof", run_id="m9-live-v6", agent_name="IssueFinalReview", stage="M9"
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    with worker_lock(store):
        parent = store.get("issue", "m9-live-v5", IssueResult)
        correction = IssueCorrection(
            slot_id=parent.spreads[1].slot.id,
            regenerate=False,
            instruction="Keep the actual M8-selected opening intentionally: portrait on page2, complete title and reading matter on page3. This page assignment supersedes the initial architect request to reverse it. Retain the complete selected photograph and measured native reading type.",
        )
        result = revise_issue(
            gateway, context, parent.id, parent.evidence_fingerprint, [correction]
        )
        target = ROOT / "data/exports/m9-proof" / context.run_id
        target.mkdir(parents=True, exist_ok=True)
        for name, asset in [
            ("issue.pdf", result.reader_pdf_asset_id),
            ("contact-sheet.png", result.contact_sheet_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(context.project_id, asset))
        (target / "issue.json").write_text(result.model_dump_json(indent=2))
        (target / "page-map.json").write_text(result.page_map.model_dump_json(indent=2))
        for i, e in enumerate(result.spreads):
            folder = target / f"spread-{i + 1}"
            folder.mkdir(exist_ok=True)
            for name, asset in [
                ("spread.png", e.spread.png_asset_id),
                ("spread.pdf", e.spread.pdf_asset_id),
                ("scene.json", e.spread.document_asset_id),
                ("metadata.json", e.spread.metadata_asset_id),
            ]:
                (folder / name).write_bytes(store.read_blob(context.project_id, asset))
        print(result.coherence.model_dump_json(indent=2), flush=True)


if __name__ == "__main__":
    main()
