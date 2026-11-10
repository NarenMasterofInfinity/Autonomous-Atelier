"""Correct the negative issue proof without replacing its immutable evidence."""

import base64
import json

import yaml

from editorial_studio.contracts import models as m
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.issue import revise_issue
from editorial_studio.creative.issue_models import IssueCorrection, IssueResult
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.photos.models import IngestedStory, PhotoAssessment, PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story
from editorial_studio.segmentation.models import SegmentPrompt
from editorial_studio.segmentation.service import segment
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    settings = load_settings()
    store = Store(settings.data_root)
    ctx = CallContext(
        project_id="m8-proof", run_id="m9-live-v2", agent_name="IssueRevision", stage="M9"
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    parent = store.get("issue", "m9-live-v1", IssueResult)
    sources = {s["id"]: s for s in json.loads((ROOT / "config/issue_sources.json").read_text())}
    stories = yaml.safe_load((ROOT / "config/issue_stories.yaml").read_text())["stories"]
    with worker_lock(store):
        cover = store.get("story", parent.spreads[0].slot.story_id, IngestedStory)
        photo = store.get("photo", cover.photo_assessment_ids[0], PhotoAssessment)
        cutout = segment(
            store,
            ctx,
            SegmentPrompt(
                source_asset_id=photo.source_asset_id,
                box=m.NormalizedRegion(x=0.04, y=0.04, width=0.92, height=0.92),
                points=[m.NormalizedPoint(x=0.5, y=0.5), m.NormalizedPoint(x=0.02, y=0.02)],
                labels=[1, 0],
                fill_enclosed_holes=True,
                keep_largest_component=True,
            ),
        )
        print("Globe cutout", cutout.cutout_asset_id, cutout.quality.model_dump(), flush=True)
        replacements = {}
        for index in (1, 3):
            row = stories[index]
            photo = sources[row["photo_id"]]
            story = ingest_story(
                store,
                ctx,
                StoryInput(
                    id=row["id"] + "-corrected",
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
            replacements[index] = story.id
        corrections = [
            IssueCorrection(
                slot_id=parent.spreads[0].slot.id,
                instruction="Fix cover contrast. Use the isolated alpha globe (photo-2) integrated on cream paper; no black rectangular backing. Keep FROM HERE fully legible in clear paper above or beside globe, never dark letters crossing its black edges. Front cover is RIGHT half, page 1; title and principal globe must belong to right half. Back-cover essay on LEFT page12. All supplied text exactly once.",
            ),
            IssueCorrection(
                slot_id=parent.spreads[2].slot.id,
                replacement_story_id=replacements[1],
                instruction="Replace the incorrect buffet image with this visually verified actual shuttle launch. Make upward movement and plume integral to the typography and page composition. Respect native resolution: 3000x2400 at minimum300ppi means source frame at most254x203mm including bleed. Preserve whole title and all body.",
            ),
            IssueCorrection(
                slot_id=parent.spreads[3].slot.id,
                regenerate=False,
                instruction="Move reading column out of fold safe zone while retaining native typography and all copy.",
            ),
            IssueCorrection(
                slot_id=parent.spreads[4].slot.id,
                replacement_story_id=replacements[3],
                instruction="Use the clean 6000x240 native panorama strip at MAXIMUM18mm HEIGHT (300ppi), extending horizontally as a deliberate horizon gesture. All black mosaic grid edges and rover hardware are cropped out at source. Place body on BOTH facing pages, two source_range partitions exactly covering body without gaps or duplicates. Integrate the long title and thin photographic strip into an intentional quiet pause, rather than a pasted photo card. No invented quote or extra text.",
            ),
        ]
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
        for i, entry in enumerate(result.spreads):
            folder = target / f"spread-{i + 1}"
            folder.mkdir(exist_ok=True)
            for name, asset in [
                ("spread.png", entry.spread.png_asset_id),
                ("spread.pdf", entry.spread.pdf_asset_id),
                ("scene.json", entry.spread.document_asset_id),
                ("metadata.json", entry.spread.metadata_asset_id),
            ]:
                (folder / name).write_bytes(store.read_blob(ctx.project_id, asset))
        print(
            json.dumps(
                {
                    "id": result.id,
                    "state": result.state,
                    "coherence": result.coherence.model_dump(mode="json"),
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
