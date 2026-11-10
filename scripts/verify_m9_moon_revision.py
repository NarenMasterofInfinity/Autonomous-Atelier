"""Balance the lunar essay with source-bound facing columns."""

from editorial_studio.contracts.models import DerivedText
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.issue import revise_issue
from editorial_studio.creative.issue_models import IssueCorrection, IssueResult
from editorial_studio.creative.models import CompiledConcept, ConceptProposal
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    settings = load_settings()
    store = Store(settings.data_root)
    ctx = CallContext(
        project_id="m8-proof", run_id="m9-live-v5", agent_name="AuthoredIssueRepair", stage="M9"
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    with worker_lock(store):
        parent = store.get("issue", "m9-live-v4", IssueResult)
        entry = parent.spreads[3]
        raw = store.get("concept", entry.spread.concept_id, CompiledConcept).proposal.model_dump()
        node = next(n for n in raw["graph"]["nodes"] if n["id"] == "text-body")
        treatment = next(t for t in raw["treatments"] if t["node_id"] == "text-body")
        text = store.get("derived_text", node["derived_text_id"], DerivedText).text
        boundary = text.index("\n\n") + 2
        raw["graph"]["relationships"] = [
            r
            for r in raw["graph"]["relationships"]
            if r["source_id"] != "text-body" and r["target_id"] != "text-body"
        ]
        raw["graph"]["nodes"] = [n for n in raw["graph"]["nodes"] if n["id"] != "text-body"]
        raw["treatments"] = [t for t in raw["treatments"] if t["node_id"] != "text-body"]
        for key, x, start, end in [
            ("essay-left", 0.06, 0, boundary),
            ("essay-right", 0.55, boundary, len(text)),
        ]:
            raw["graph"]["nodes"].append(
                {**node, "id": key, "target_region": dict(x=x, y=0.80, width=0.27, height=0.16)}
            )
            raw["treatments"].append(
                {**treatment, "node_id": key, "text_range": dict(start_char=start, end_char=end)}
            )
        next(n for n in raw["graph"]["nodes"] if n["id"] == "text-deck")["target_region"] = dict(
            x=0.06, y=0.69, width=0.40, height=0.07
        )
        raw["spatial_intent"]["anchor_relationships"] = []
        proposal = ConceptProposal.model_validate(raw)
        result = revise_issue(
            gateway,
            ctx,
            parent.id,
            parent.evidence_fingerprint,
            [
                IssueCorrection(
                    slot_id=entry.slot.id,
                    instruction="Retain the lunar image and headline. Set the two original essay paragraphs in facing columns on a shared baseline beneath the horizon; the short deck introduces the left column. Preserve all source characters and generous margins.",
                    regenerate=False,
                    authored_proposal=proposal,
                )
            ],
        )
        target = ROOT / "data/exports/m9-proof" / ctx.run_id
        target.mkdir(parents=True, exist_ok=True)
        for name, asset in [
            ("issue.pdf", result.reader_pdf_asset_id),
            ("contact-sheet.png", result.contact_sheet_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(ctx.project_id, asset))
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
                (folder / name).write_bytes(store.read_blob(ctx.project_id, asset))
        print(result.coherence.model_dump_json(indent=2), flush=True)


if __name__ == "__main__":
    main()
