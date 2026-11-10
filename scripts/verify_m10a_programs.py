"""Run/export reference-program composition; optional two-call model selection/review."""

import argparse
import base64
import hashlib
import json

from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.compiler import story_sources
from editorial_studio.creative.models import CompiledConcept
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.photos.models import IngestedStory, PhotoAssessment, PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story
from editorial_studio.reference_studio.catalog import references
from editorial_studio.reference_studio.service import build_compositions
from editorial_studio.segmentation.models import SegmentationResult
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


class LocalOnly:
    namespace = "reference-program-local"

    def execute(self, *args):
        raise AssertionError("Local reference-program run must not invoke a provider")


def export(store, result):
    root = ROOT / "data/exports/m10a" / result.id
    root.mkdir(parents=True, exist_ok=True)
    (root / "result.json").write_text(result.model_dump_json(indent=2))
    for name, asset in (
        ("compositions.pdf", result.proof_book_asset_id),
        ("contact-sheet.png", result.contact_sheet_asset_id),
    ):
        if asset:
            (root / name).write_bytes(store.read_blob(result.project_id, asset))
    (root / "programs.json").write_text(
        json.dumps(
            [json.loads(store.read_blob(result.project_id, a)) for a in result.program_asset_ids],
            indent=2,
        )
    )
    for candidate in result.candidates:
        folder = root / (candidate.family_id + "-" + candidate.program_id[-8:])
        folder.mkdir(exist_ok=True)
        spread = candidate.spread
        for name, asset in (
            ("spread.png", spread.png_asset_id),
            ("spread.pdf", spread.pdf_asset_id),
            ("scene.json", spread.document_asset_id),
            ("metadata.json", spread.metadata_asset_id),
        ):
            (folder / name).write_bytes(store.read_blob(result.project_id, asset))
        (folder / "quality.json").write_text(candidate.quality.model_dump_json(indent=2))
        concept = store.get("concept", spread.concept_id, CompiledConcept)
        assert (
            concept.authorship == "reference_adapted"
            and concept.reference_program_id == candidate.program_id
        )
        (folder / "concept.json").write_text(concept.model_dump_json(indent=2))
        if candidate.native_views:
            (folder / "native-views.json").write_text(
                candidate.native_views.model_dump_json(indent=2)
            )
            for name, asset in candidate.native_views.assets.items():
                (folder / (name + ".png")).write_bytes(store.read_blob(result.project_id, asset))
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument(
        "--story", choices=["portrait", "moon", "launch", "closing"], default="portrait"
    )
    parser.add_argument("--title")
    parser.add_argument("--live-choice", action="store_true")
    parser.add_argument("--references", nargs="*")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    context = CallContext(
        project_id="m10a-references",
        run_id=args.run,
        stage="M10A",
        agent_name="ReferenceProgramAcceptance",
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings) if args.live_choice else LocalOnly(),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    with worker_lock(store):
        refs = references(store)
        key = {
            "portrait": "01-depth-portrait",
            "moon": "04-serif-earthrise",
            "launch": "02-photo-overlay",
            "closing": "09-reversed-light",
        }[args.story]
        reference = next(r for r in refs if r.design_id == key)
        story = store.get("story", reference.story_id, IngestedStory)
        if args.title:
            sources = dict(story_sources(store, context.project_id, story))
            photo = store.get("photo", story.photo_assessment_ids[0], PhotoAssessment)
            old_source = photo.source_asset_id
            story = ingest_story(
                store,
                context,
                StoryInput(
                    id=args.run + "-copy-variation",
                    title=args.title,
                    deck=sources["deck"].text,
                    body=sources["body"].text,
                    author="Original validation variant; selected source photograph and body retained",
                    photos=[
                        PhotoInput(
                            filename="selected-source.png",
                            data_base64=base64.b64encode(
                                store.read_blob(context.project_id, old_source)
                            ).decode(),
                            source_uri=photo.source_uri,
                            credit=photo.credit,
                        )
                    ],
                ),
            )
            new_photo = store.get("photo", story.photo_assessment_ids[0], PhotoAssessment)
            if new_photo.source_asset_id != old_source:
                from io import BytesIO

                from PIL import Image, ImageChops

                old_image = Image.open(
                    BytesIO(store.read_blob(context.project_id, old_source))
                ).convert("RGB")
                new_image = Image.open(
                    BytesIO(store.read_blob(context.project_id, new_photo.source_asset_id))
                ).convert("RGB")
                assert (
                    old_image.size == new_image.size
                    and ImageChops.difference(old_image, new_image).getbbox() is None
                )
                for seg in store.list("segmentation", SegmentationResult, context.project_id):
                    if seg.source_asset_id == old_source and seg.quality.passed:
                        new_id = hashlib.sha256((args.run + seg.id).encode()).hexdigest()
                        clone = seg.model_copy(
                            update={"id": new_id, "source_asset_id": new_photo.source_asset_id}
                        )
                        store.put_records(("segmentation", new_id, context.project_id, clone))
        selected = [r.id for r in refs if args.references is None or r.design_id in args.references]
        result = build_compositions(
            gateway,
            context,
            story.id,
            "m10a-studio-identity",
            selected,
            art_director=args.live_choice,
        )
        root = export(store, result)
        print(
            json.dumps(
                {
                    "run": result.id,
                    "state": result.state,
                    "admitted": sum(c.quality.passed for c in result.candidates),
                    "rejections": len(result.rejections),
                    "selected": result.selected_program_id,
                    "export": str(root),
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
