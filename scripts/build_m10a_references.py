"""Build authored real-photo references locally through the production compiler."""

import argparse
import base64
import hashlib
import json
from io import BytesIO

import pymupdf
import yaml
from PIL import Image, ImageDraw

from editorial_studio.art_direction.service import build_identity
from editorial_studio.canvas.typography.fonts import FontConfiguration
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.compiler import story_sources
from editorial_studio.creative.issue_models import IssueResult
from editorial_studio.creative.models import CreativeReview
from editorial_studio.creative.planning import prepare_proposal
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.creative.tournament import configuration, material
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.photos.models import IngestedStory, PhotoAssessment, PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story
from editorial_studio.reference_studio.authoring import STUDIES, Author, compose, fonts
from editorial_studio.reference_studio.models import (
    AuthoredReference,
    EditorialFamily,
    ReferenceAtlas,
)
from editorial_studio.segmentation.models import SegmentationResult
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable


class LocalOnly:
    namespace = "m10a-local-authoring"

    def execute(self, *args):
        raise AssertionError("reference authoring never calls a provider")


def setup(store, ctx):
    issue = store.get("issue", "m9-live-v6", IssueResult)
    identity = build_identity(store, ctx.model_copy(update={"run_id": "m10a-foundation"}), dpi=72)
    keys = ["cover", "portrait", "launch", "moon", "mars", "closing"]
    out = {}
    for key, entry in zip(keys, issue.spreads, strict=True):
        old = store.get("story", entry.spread.story_id, IngestedStory)
        source = dict(story_sources(store, "m8-proof", old))
        photo = store.get("photo", old.photo_assessment_ids[0], PhotoAssessment)
        # The terrain study uses a native crop from the existing original photo,
        # not a new image selection or a generated photograph.
        raw = store.read_blob("m8-proof", photo.source_asset_id)
        if key == "mars":
            im = Image.open(ROOT / "data/issue-sources/prepared-PIA18409.png").convert("RGB")
            im = im.crop((1400, 190, 4550, 900))
            buf = BytesIO()
            im.save(buf, format="PNG")
            raw = buf.getvalue()
        story = ingest_story(
            store,
            ctx,
            StoryInput(
                id="m10a-" + key,
                title=source["headline"].text,
                deck=source["deck"].text,
                body=source["body"].text,
                author=old.author,
                photos=[
                    PhotoInput(
                        filename=key + ".png",
                        data_base64=base64.b64encode(raw).decode(),
                        source_uri=photo.source_uri,
                        credit=photo.credit,
                    )
                ],
            ),
        )
        new_photo = store.get("photo", story.photo_assessment_ids[0], PhotoAssessment)
        cut = None
        for project in ("flagship-proof", "m8-proof"):
            matches = [
                r
                for r in store.list("segmentation", SegmentationResult, project)
                if r.source_asset_id == new_photo.source_asset_id and r.quality.passed
            ]
            if matches:
                seg = matches[-1]
                for asset in [
                    seg.source_asset_id,
                    seg.mask_asset_id,
                    seg.alpha_asset_id,
                    seg.cutout_asset_id,
                ]:
                    store.put_blob(
                        ctx.project_id,
                        store.read_blob(project, asset),
                        store.asset(project, asset).media_type,
                    )
                copied = seg.model_copy(
                    update={"id": "m10a-" + seg.id, "project_id": ctx.project_id}
                )
                store.put_records(("segmentation", copied.id, ctx.project_id, copied))
                cut = copied.cutout_asset_id
                break
        out[key] = (story, new_photo.source_asset_id, cut)
    return identity, out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="m10a-v1")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    ctx = CallContext(
        project_id="m10a-references",
        run_id=args.run,
        agent_name="AuthoredReferenceStudio",
        stage="M10A",
    )
    families = {
        r["id"]: EditorialFamily.model_validate(r)
        for r in yaml.safe_load((ROOT / "config/editorial_families.yaml").read_text())["families"]
    }
    gateway = Gateway(store, LocalOnly(), PricingTable.load(settings.pricing_path))
    with worker_lock(store):
        identity, inputs = setup(store, ctx)
        root = ROOT / "data/exports/m10a" / args.run
        root.mkdir(parents=True, exist_ok=True)
        records = []
        for key, family_key, story_key in STUDIES:
            if args.only and key not in args.only:
                continue
            story, photo, cutout = inputs[story_key]
            family = families[family_key]
            effective = identity.model_copy(deep=True)
            effective.typography = FontConfiguration(
                fonts=fonts(), styles=effective.typography.styles
            )
            author = compose(key, Author(store, ctx.project_id, story, photo, cutout))
            effective.guidelines.palette_roles["paper"] = author.paper
            run = args.run + "-" + key
            context = ctx.model_copy(update={"run_id": run, "spread_id": run})
            proposal = author.finish(family.principle, family.capability_ids)
            mat, _ = material(
                store,
                ctx.project_id,
                story,
                effective,
                {**configuration(), "quality_reference": None},
            )
            proposal = prepare_proposal(store, context, proposal, mat)
            authoring_fingerprint = hashlib.sha256(
                b"".join(
                    (ROOT / path).read_bytes()
                    for path in [
                        "editorial_studio/reference_studio/authoring.py",
                        "editorial_studio/segmentation/geometry.py",
                        "editorial_studio/canvas/typography/engine.py",
                        "editorial_studio/canvas/renderer.py",
                    ]
                )
            ).hexdigest()
            binding = authoring_fingerprint + (
                proposal.model_dump_json() + effective.model_dump_json() + family.model_dump_json()
            )
            run += "-" + hashlib.sha256(binding.encode()).hexdigest()[:10]
            context = context.model_copy(update={"run_id": run, "spread_id": run})
            proof = store.get("authored_reference", run, AuthoredReference)
            if proof is None:
                spread = build_creative_spread(
                    gateway,
                    context,
                    story.id,
                    effective.id,
                    proposal=proposal,
                    identity_snapshot=effective,
                    with_visual_critics=False,
                )
                review = store.get("creative_review", spread.review_id, CreativeReview)
                if review.execution.verdict.value != "ACCEPT":
                    raise ValueError(review.execution.model_dump_json())
                proof = AuthoredReference(
                    id=run,
                    design_id=key,
                    authoring_fingerprint=authoring_fingerprint,
                    project_id=ctx.project_id,
                    family_id=family.id,
                    family_version=family.version,
                    title=family.name,
                    story_id=story.id,
                    spread=spread,
                    brief=family.principle,
                    reference_ids=family.reference_ids,
                    family_snapshot_json=family.model_dump_json(),
                )
                store.put_records(("authored_reference", proof.id, ctx.project_id, proof))
            folder = root / key
            folder.mkdir(exist_ok=True)
            for name, asset in [
                ("spread.png", proof.spread.png_asset_id),
                ("spread.pdf", proof.spread.pdf_asset_id),
                ("scene.json", proof.spread.document_asset_id),
                ("metadata.json", proof.spread.metadata_asset_id),
            ]:
                (folder / name).write_bytes(store.read_blob(ctx.project_id, asset))
            (folder / "reference.json").write_text(proof.model_dump_json(indent=2))
            records.append(proof)
            print("Rendered", key, flush=True)
        # Rebuild the atlas only from the explicitly bound authored proof set.
        book = pymupdf.open()
        sheet = Image.new("RGB", (2400, 4 * 450), "#d9d6cf")
        draw = ImageDraw.Draw(sheet)
        for index, proof in enumerate(records):
            im = Image.open(
                BytesIO(store.read_blob(ctx.project_id, proof.spread.png_asset_id))
            ).convert("RGB")
            im.thumbnail((780, 410))
            x, y = index % 3 * 800 + 10, index // 3 * 450 + 29
            sheet.paste(im, (x, y))
            draw.text(
                (x, y - 20),
                proof.id.removeprefix(args.run + "-") + " | " + proof.family_id,
                fill="#22211f",
            )
            with pymupdf.open(
                stream=store.read_blob(ctx.project_id, proof.spread.pdf_asset_id), filetype="pdf"
            ) as pdf:
                book.insert_pdf(pdf)
        pdf_bytes = book.tobytes(garbage=4, deflate=True)
        (root / "references.pdf").write_bytes(pdf_bytes)
        book.close()
        sheet.save(root / "contact-sheet.png")
        buf = BytesIO()
        sheet.save(buf, format="PNG")
        atlas = ReferenceAtlas(
            id=args.run,
            project_id=ctx.project_id,
            reference_ids=[r.id for r in records],
            pdf_asset_id=store.put_blob(ctx.project_id, pdf_bytes, "application/pdf").id,
            contact_sheet_asset_id=store.put_blob(ctx.project_id, buf.getvalue(), "image/png").id,
        )
        store.put_records(("reference_atlas", atlas.id, ctx.project_id, atlas))
        (root / "atlas.json").write_text(
            json.dumps([r.model_dump(mode="json") for r in records], indent=2)
        )
        print(
            "Atlas:",
            len(records),
            "authored studies;",
            len({r.family_id for r in records}),
            "families; owner review pending",
            flush=True,
        )


if __name__ == "__main__":
    main()
