"""Verify a saved issue against its source stories, admitted scenes and reader PDF."""

import argparse
import json

import pymupdf

from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.core.storage import Store
from editorial_studio.creative.issue import issue_assets
from editorial_studio.creative.issue_models import IssueBuild, IssueResult
from editorial_studio.creative.models import CompiledConcept
from editorial_studio.reference_studio.models import ReferenceComposition
from editorial_studio.settings import ROOT, load_settings
from scripts.verify_m10a_program_outputs import check_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="program-issue-v2")
    args = parser.parse_args()
    store = Store(load_settings().data_root, readonly=True)
    issue = store.get("issue", args.run, IssueResult)
    assert issue is not None
    issue_assets(store, issue)
    build = store.get("issue_build", issue.id, IssueBuild)
    studies = store.list("reference_composition", ReferenceComposition, issue.project_id)
    reports, families = [], []
    for entry in issue.spreads:
        compiled = store.get("concept", entry.spread.concept_id, CompiledConcept)
        assert entry.source == "reference_program"
        assert build.reference_selections[entry.slot.id] == compiled.reference_program_id
        study, candidate = next(
            (run, c)
            for run in studies
            for c in run.candidates
            if c.quality.passed and c.spread == entry.spread
        )
        assert study.story_id == entry.slot.story_id
        reports.append(
            check_result(
                store,
                study.model_copy(update={"candidates": [candidate]}),
                report_sampling_difference=True,
            )
        )
        families.append(candidate.family_id)
        if entry.slot.phase == "cover":
            assert study.page_role == "cover"
            document = CanvasDocument.model_validate_json(
                store.read_blob(issue.project_id, entry.spread.document_asset_id)
            )
            metadata = RenderMetadata.model_validate_json(
                store.read_blob(issue.project_id, entry.spread.metadata_asset_id)
            )
            bounds = {x.result.text_layer_id: x.result.ink_bounds for x in metadata.text_layouts}
            treatments = {t.node_id: t for t in compiled.proposal.treatments}
            for node in compiled.proposal.graph.nodes:
                if node.role != "text":
                    continue
                ink = bounds[node.id]
                if treatments[node.id].style_role == "headline":
                    assert ink.x_mm >= 209 and ink.x_mm + ink.width_mm <= 421
                else:
                    assert ink.x_mm + ink.width_mm <= 210
            assert document.scene.layers
    with pymupdf.open(
        stream=store.read_blob(issue.project_id, issue.reader_pdf_asset_id), filetype="pdf"
    ) as pdf:
        assert len(pdf) == 12
        for page in pdf:
            assert abs(page.rect.width * 25.4 / 72 - 210) < 0.001
            assert abs(page.rect.height * 25.4 / 72 - 297) < 0.001
    parent = store.get("issue", build.revision_of, IssueResult) if build.revision_of else None
    if parent:
        assert [
            (s.story_id, s.phase, s.left_page, s.right_page, s.narrative_goal)
            for s in parent.blueprint.slots
        ] == [
            (s.story_id, s.phase, s.left_page, s.right_page, s.narrative_goal)
            for s in issue.blueprint.slots
        ]
    report = {
        "issue": issue.id,
        "physical_pages": 12,
        "families": families,
        "distinct_families": len(set(families)),
        "adjacent_family_repeats": sum(
            a == b for a, b in zip(families, families[1:], strict=False)
        ),
        "original_story_sequence_preserved": bool(parent),
        "selected_scenes_preserved": True,
        "cover_front_back": "verified",
        "raster_review_items": [
            {
                "pages": f"{entry.slot.left_page}/{entry.slot.right_page}",
                "family": item["family"],
                "detail": item["raster_review"],
            }
            for entry, spread in zip(issue.spreads, reports, strict=True)
            for item in spread["admitted"]
            if not item["strict_raster_match"]
        ],
        "spreads": reports,
        "provider_calls": 0,
        "scope": "Source/export regression checks; not an independent aesthetic benchmark.",
    }
    path = ROOT / "data/exports/m10a" / args.run / "verification.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "spreads"}, indent=2))


if __name__ == "__main__":
    main()
