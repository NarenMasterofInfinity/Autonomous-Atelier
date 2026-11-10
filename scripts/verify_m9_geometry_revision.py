"""Explicitly authored geometric repairs of two model-generated issue spreads."""

import argparse

from editorial_studio.contracts import models as m
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.issue import revise_issue
from editorial_studio.creative.issue_models import IssueCorrection, IssueResult
from editorial_studio.creative.models import CompiledConcept
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="m9-live-v3")
    parser.add_argument("--parent", default="m9-live-v2")
    parser.add_argument("--refine", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    ctx = CallContext(
        project_id="m8-proof", run_id=args.run, agent_name="AuthoredIssueRepair", stage="M9"
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    with worker_lock(store):
        parent = store.get("issue", args.parent, IssueResult)
        corrections = []
        for index in (2, 4):
            entry = parent.spreads[index]
            proposal = store.get(
                "concept", entry.spread.concept_id, CompiledConcept
            ).proposal.model_copy(deep=True)
            # Contradictory anchors had translated distinct display words together.
            proposal.spatial_intent.anchor_relationships = []
            if index == 2:
                photo = next(n for n in proposal.graph.nodes if n.role == "image")
                photo.target_region = m.NormalizedRegion(x=0, y=0.14, width=200 / 420, height=0.68)
                note = "Contain launch on left page with a 10mm paper margin to fold; remove the accidental page5 photo sliver. Preserve title and both reading columns on right."
            else:
                positions = {
                    "title-a": (0.06, 0.08, 0.40, 0.10),
                    "title-b": (0.53, 0.08, 0.40, 0.10),
                    "body-left": (0.06, 0.49, 0.31, 0.42),
                    "body-right": (0.55, 0.49, 0.31, 0.42),
                }
                for node in proposal.graph.nodes:
                    if node.id in positions:
                        x, y, w, h = positions[node.id]
                        node.target_region = m.NormalizedRegion(x=x, y=y, width=w, height=h)
                note = "Keep THE LONG and LOOK readable at separate positions; remove align_center constraint that overprinted words. Align two wider reading columns under panorama."
            if args.refine:
                if index == 2:
                    positions = {
                        "photo": (100 / 420, 50 / 297, 254 / 420, 190 / 297),
                        "headline": (25 / 420, 8 / 297, 370 / 420, 35 / 297),
                        "deck": (25 / 420, 84 / 297, 65 / 420, 28 / 297),
                        "body-a": (25 / 420, 119 / 297, 65 / 420, 150 / 297),
                        "body-b": (231 / 420, 249 / 297, 150 / 420, 42 / 297),
                    }
                    next(
                        t for t in proposal.treatments if t.node_id == "headline"
                    ).style_name = "studio.display"
                    note = "Let the launch image form one continuous photograph across the fold at its native 300ppi. The complete headline spans above it; one reading column sits beside the image at left and the second below it at right. Keep every supplied word and the open paper around the plume."
                else:
                    proposal.graph.relationships = [
                        r
                        for r in proposal.graph.relationships
                        if r.source_id != "title-b" and r.target_id != "title-b"
                    ]
                    proposal.graph.nodes = [n for n in proposal.graph.nodes if n.id != "title-b"]
                    proposal.treatments = [t for t in proposal.treatments if t.node_id != "title-b"]
                    title = next(t for t in proposal.treatments if t.node_id == "title-a")
                    title.text_range = title.text_range.model_copy(
                        update={"start_char": 0, "end_char": 13}
                    )
                    title.style_name = "studio.display"
                    positions = {
                        "title-a": (0.06, 0.08, 0.40, 0.14),
                        "deck": (0.06, 0.26, 0.40, 0.07),
                        "body-left": (0.06, 0.50, 0.34, 0.42),
                        "body-right": (0.55, 0.50, 0.34, 0.42),
                    }
                    note = "Present the complete THE LONG LOOK title as one left-page headline. A deliberate thin native panorama continues across both pages as a quiet horizon, followed by aligned facing reading columns, read left then right. Its 18mm height is intentional: preserve native resolution and use it as the low-energy pause between larger photographic gestures."
                for node in proposal.graph.nodes:
                    if node.id in positions:
                        x, y, w, h = positions[node.id]
                        node.target_region = m.NormalizedRegion(x=x, y=y, width=w, height=h)
            corrections.append(
                IssueCorrection(
                    slot_id=entry.slot.id,
                    instruction=note,
                    regenerate=False,
                    authored_proposal=proposal,
                )
            )
        result = revise_issue(gateway, ctx, parent.id, parent.evidence_fingerprint, corrections)
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
