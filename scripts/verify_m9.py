"""Live twelve-page issue using a completed M8 selection and five public-photo stories."""

import argparse
import base64
import json

import yaml

from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store, identifier
from editorial_studio.creative.issue import build_issue
from editorial_studio.creative.tournament_models import TournamentResult
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor
from scripts.install_issue_sources import main as verify_sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="m9-live-v1")
    parser.add_argument("--tournament", default="m8-live-v3")
    args = parser.parse_args()
    identifier(args.run)
    verify_sources()
    settings = load_settings()
    store = Store(settings.data_root)
    context = CallContext(
        project_id="m8-proof",
        run_id=args.run,
        agent_name="IssueAcceptance",
        stage="M9",
        prompt_version="m9-v1",
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    tournament = store.get("tournament", args.tournament, TournamentResult)
    if tournament is None:
        raise ValueError("M8 acceptance tournament is not complete")
    sources = {
        row["id"]: row for row in json.loads((ROOT / "config/issue_sources.json").read_text())
    }
    with worker_lock(store):
        story_ids = [tournament.story_id]
        for row in yaml.safe_load((ROOT / "config/issue_stories.yaml").read_text())["stories"]:
            photo = sources[row["photo_id"]]
            story = ingest_story(
                store,
                context,
                StoryInput(
                    id=row["id"],
                    title=row["title"],
                    deck=row["deck"],
                    body="\n\n".join(row["paragraphs"]),
                    author="Original studio acceptance essay; not an interview",
                    photos=[
                        PhotoInput(
                            filename=photo["filename"],
                            data_base64=base64.b64encode(
                                (ROOT / "data/issue-sources" / photo["filename"]).read_bytes()
                            ).decode(),
                            source_uri=photo["metadata_url"],
                            credit=photo["credit"],
                        )
                    ],
                ),
            )
            story_ids.append(story.id)
        print("Planning and composing twelve physical pages", flush=True)
        result = build_issue(
            gateway, context, story_ids, tournament.identity_id, tournament_ids=[tournament.id]
        )
        target = ROOT / "data/exports/m9-proof" / args.run
        target.mkdir(parents=True, exist_ok=True)
        for name, asset in [
            ("issue.pdf", result.reader_pdf_asset_id),
            ("contact-sheet.png", result.contact_sheet_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(context.project_id, asset))
        (target / "issue.json").write_text(result.model_dump_json(indent=2))
        (target / "page-map.json").write_text(result.page_map.model_dump_json(indent=2))
        for index, entry in enumerate(result.spreads):
            folder = target / f"spread-{index + 1}"
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
                    "coherence": result.coherence.verdict.value,
                    "state": result.state,
                    "folder": str(target),
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
