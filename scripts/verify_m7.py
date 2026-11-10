"""Three representative concept-led spreads, real critics and a pending final identity package."""

import argparse
import base64
from pathlib import Path

from editorial_studio.art_direction.service import build_identity
from editorial_studio.contracts import models as m
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.identity import package_identity
from editorial_studio.creative.models import CompiledConcept, CreativeReview
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story
from editorial_studio.segmentation.models import SegmentPrompt
from editorial_studio.segmentation.service import segment
from editorial_studio.settings import load_settings
from editorial_studio.spatial.proofs import build_capability_proofs
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-prefix", default="m7-v4")
    parser.add_argument("--portrait-run", default="m7-v4-case-1")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    project = "m7-proof"
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    context = CallContext(
        project_id=project,
        run_id="m7-identity",
        agent_name="IdentityProof",
        stage="M7",
        prompt_version="m7-v1",
    )
    target = Path("data/exports/m7-proof")
    target.mkdir(parents=True, exist_ok=True)
    mandates = [
        "Case A: a restrained portrait feature with depth typography. Use the provided astronaut image and actual isolated cutout if depth helps. Reserve a clearly readable region for all body copy. Apply grain or halftone to both low-PPI image layers. Make the title legible around the subject rather than hiding most of it.",
        "Case B: a typographic essay. Let a gentle, generously long Bezier headline path carry the rhythm; keep the complete body in a readable rectangular or irregular region. Use the coffee photograph as a smaller counterweight. Make this composition structurally different from a portrait feature.",
        "Case C: a graphic interview with two photographs and a simple geometric vector motif. Compose an asymmetric collage with deliberate cropping and restrained blending. Avoid the same image-left/body-right structure as a standard feature. Keep the full source interview readable.",
    ]
    photos = [["astronaut.png"], ["coffee.png"], ["rocket.jpg", "moon.png"]]
    with worker_lock(store):
        identity = build_identity(store, context, dpi=144)
        caps = build_capability_proofs(
            store, context.model_copy(update={"run_id": "m7-techniques"})
        )
        spreads = []
        import yaml

        from editorial_studio.design_system.models import BaselineStory

        fixtures = [
            BaselineStory.model_validate(row)
            for row in yaml.safe_load(Path("config/m7_stories.yaml").read_text())["stories"]
        ]
        for index, fixture in enumerate(fixtures):
            rows = []
            for filename in photos[index]:
                path = Path("data/fixtures/photos") / filename
                if not path.exists():
                    path = path.with_suffix(".png")
                rows.append(
                    PhotoInput(
                        filename=path.name,
                        data_base64=base64.b64encode(path.read_bytes()).decode(),
                        source_uri="https://github.com/scikit-image/scikit-image/tree/v0.25.2/skimage/data/"
                        + path.name,
                        credit="scikit-image attributed sample data",
                    )
                )
            story = ingest_story(
                store,
                context,
                StoryInput(
                    id="m7-" + fixture.id,
                    title=fixture.title,
                    deck=fixture.deck,
                    body=fixture.body,
                    author="Studio acceptance fixture",
                    photos=rows,
                ),
            )
            if index == 0:
                from editorial_studio.photos.models import PhotoAssessment

                photo = store.get("photo", story.photo_assessment_ids[0], PhotoAssessment)
                segment(
                    store,
                    context.model_copy(update={"stage": "M4", "agent_name": "SubjectSegmenter"}),
                    SegmentPrompt(
                        source_asset_id=photo.source_asset_id,
                        box=m.NormalizedRegion(x=0.05, y=0.02, width=0.9, height=0.98),
                        points=[m.NormalizedPoint(x=0.42, y=0.4)],
                        labels=[1],
                    ),
                )
            run = context.model_copy(
                update={
                    "run_id": args.portrait_run
                    if index == 0
                    else f"{args.run_prefix}-case-{index + 1}",
                    "agent_name": "CreativeWorkflow",
                }
            )
            print("Building", run.run_id, flush=True)
            spread = build_creative_spread(
                gateway, run, story.id, identity.id, mandate=mandates[index]
            )
            spreads.append(spread)
            folder = target / f"case-{index + 1}"
            folder.mkdir(exist_ok=True)
            for name, asset in [
                ("spread.png", spread.png_asset_id),
                ("spread.pdf", spread.pdf_asset_id),
                ("scene.json", spread.document_asset_id),
                ("metadata.json", spread.metadata_asset_id),
            ]:
                (folder / name).write_bytes(store.read_blob(project, asset))
            compiled = store.get("concept", spread.concept_id, CompiledConcept)
            review = store.get("creative_review", spread.review_id, CreativeReview)
            (folder / "concept.json").write_text(compiled.model_dump_json(indent=2))
            (folder / "review.json").write_text(review.model_dump_json(indent=2))
            (folder / "sketch.png").write_bytes(
                store.read_blob(project, compiled.hybrid.sketch.asset_id)
            )
            print(
                "Rendered",
                run.run_id,
                spread.state,
                "critics:",
                review.decision.verdict.value,
                flush=True,
            )
        package = package_identity(
            store,
            context.model_copy(update={"run_id": args.run_prefix + "-final-package"}),
            identity.id,
            [s.id for s in spreads],
            [p.id for p in caps],
        )
        for name, asset in [
            ("representative-spreads.pdf", package.proof_book_asset_id),
            ("contact-sheet.png", package.contact_sheet_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(project, asset))
        (target / "final-review-package.json").write_text(package.model_dump_json(indent=2))
        (target / "candidate-bible.json").write_text(package.bible.model_dump_json(indent=2))
        print(
            "M7 final package:",
            package.id,
            "human approval:",
            package.review_verdict,
            "structural distances:",
            package.structural_distances,
        )


if __name__ == "__main__":
    main()
