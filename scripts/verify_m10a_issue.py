"""Build a real twelve-page visual proof through the reference-program issue path."""

import argparse
import hashlib
import json

import yaml

from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.compiler import story_sources
from editorial_studio.creative.issue import build_issue, issue_assets
from editorial_studio.creative.issue_models import IssueCorrection, IssueResult
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.photos.models import IngestedStory, PhotoAssessment
from editorial_studio.reference_studio.catalog import references
from editorial_studio.reference_studio.models import ReferenceComposition
from editorial_studio.reference_studio.service import build_compositions
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="program-issue-v1")
    parser.add_argument("--revision-of")
    parser.add_argument("--reuse-studies")
    parser.add_argument("--verify-inputs-only", action="store_true")
    parser.add_argument("--polish-selected", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    context = CallContext(
        project_id="m10a-references",
        run_id=args.run,
        stage="M10A",
        agent_name="IssueAcceptance",
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    with worker_lock(store):
        refs = references(store)
        order = [
            "05-outline-globe",
            "01-depth-portrait",
            "02-photo-overlay",
            "04-serif-earthrise",
            "06-terrain-lettering",
            "09-reversed-light",
        ]
        stories = [next(r.story_id for r in refs if r.design_id == key) for key in order]
        # Only the previously authorized public-photo / generated-essay fixtures.
        inputs = yaml.safe_load((ROOT / "config/issue_stories.yaml").read_text())["stories"]
        portrait = yaml.safe_load((ROOT / "config/flagship.yaml").read_text())["story"]
        allowed_copy = {
            (row["title"], "\n\n".join(row["paragraphs"])) for row in [*inputs, portrait]
        }
        provenance = []
        for key in stories:
            story = store.get("story", key, IngestedStory)
            copy = dict(story_sources(store, context.project_id, story))
            assert (copy["headline"].text, copy["body"].text) in allowed_copy
            photos = [
                store.get("photo", photo, PhotoAssessment) for photo in story.photo_assessment_ids
            ]
            assert all(
                photo.source_uri.startswith(
                    ("https://images-api.nasa.gov/", "https://images-assets.nasa.gov/")
                )
                for photo in photos
            )
            provenance.append(
                {
                    "story_id": key,
                    "copy_fixture": "config/flagship.yaml"
                    if copy["headline"].text == portrait["title"]
                    else "config/issue_stories.yaml",
                    "photos": [
                        {
                            "url": photo.source_uri,
                            "sha256": hashlib.sha256(
                                store.read_blob(context.project_id, photo.source_asset_id)
                            ).hexdigest(),
                        }
                        for photo in photos
                    ],
                }
            )
        assert {ref.story_id for ref in refs} <= set(stories)
        (ROOT / ".runtime/program-issue-public-inputs.json").write_text(
            json.dumps(provenance, indent=2)
        )
        if args.verify_inputs_only:
            print(json.dumps(provenance, indent=2))
            return
        parent = store.get("issue", args.revision_of, IssueResult) if args.revision_of else None
        if args.revision_of and parent is None:
            raise ValueError("Missing parent issue")
        if parent:
            assert {s.story_id for s in parent.blueprint.slots} == set(stories)
            stories = [s.story_id for s in parent.blueprint.slots]
        prepared = (
            [f"{args.reuse_studies}-reference-{i}" for i in range(6)] if args.reuse_studies else []
        )
        if args.polish_selected:
            if parent is None:
                raise ValueError("Selected-scene polish requires a parent issue")
            studies = store.list("reference_composition", ReferenceComposition, context.project_id)
            prepared = []
            for index, entry in enumerate(parent.spreads):
                study, candidate = next(
                    (run, c)
                    for run in studies
                    for c in run.candidates
                    if c.spread == entry.spread and c.quality.passed
                )
                if entry.slot.phase in ("cover", "feature"):
                    study = build_compositions(
                        gateway,
                        context.model_copy(update={"run_id": args.run + f"-polish-{index}"}),
                        entry.slot.story_id,
                        parent.identity_id,
                        [candidate.reference_id],
                        page_role="cover" if entry.slot.phase == "cover" else "spread",
                    )
                prepared.append(study.id)
        result = build_issue(
            gateway,
            context,
            stories,
            "m10a-studio-identity",
            reference_ids=[r.id for r in refs],
            revision_of=args.revision_of,
            prepared_composition_ids=prepared,
            reference_art_director=not args.polish_selected,
            corrections=[
                IssueCorrection(
                    slot_id=s.id,
                    instruction="Preserve the story, selected photograph and narrative phase; select a varied sequence of admitted reference programs and put the complete cover title on front page 1.",
                )
                for s in parent.blueprint.slots
            ]
            if parent
            else [],
        )
        issue_assets(store, result)
        assert all(entry.source == "reference_program" for entry in result.spreads)
        root = ROOT / "data/exports/m10a" / args.run
        root.mkdir(parents=True, exist_ok=True)
        for name, asset in [
            ("magazine.pdf", result.reader_pdf_asset_id),
            ("contact-sheet.png", result.contact_sheet_asset_id),
        ]:
            (root / name).write_bytes(store.read_blob(context.project_id, asset))
        (root / "issue.json").write_text(result.model_dump_json(indent=2))
        for index, entry in enumerate(result.spreads):
            folder = root / f"spread-{index + 1}"
            folder.mkdir(exist_ok=True)
            for name, asset in [
                ("spread.png", entry.spread.png_asset_id),
                ("spread.pdf", entry.spread.pdf_asset_id),
                ("scene.json", entry.spread.document_asset_id),
                ("metadata.json", entry.spread.metadata_asset_id),
            ]:
                (folder / name).write_bytes(store.read_blob(context.project_id, asset))
        print(
            json.dumps(
                {
                    "issue": result.id,
                    "pages": len(result.page_map.pages),
                    "state": result.state,
                    "export": str(root),
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
