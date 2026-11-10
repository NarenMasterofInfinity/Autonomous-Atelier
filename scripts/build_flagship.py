"""Reproduce one authored benchmark through the same compiler and creative service.

Local rendering is the default. --review explicitly enables the existing visual
critic calls through the instrumented gateway. No concept-generation call is used.
"""

import argparse
import base64
import json

import yaml

from editorial_studio.art_direction.service import build_identity
from editorial_studio.canvas.typography.fonts import FontConfiguration, FontSpec, TypeStyle
from editorial_studio.contracts import models as m
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store, identifier
from editorial_studio.creative.compiler import story_sources
from editorial_studio.creative.models import (
    CompiledConcept,
    ConceptProposal,
    ConceptTypography,
    CreativeReview,
    NodeTreatment,
    TextRange,
)
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.photos.models import PhotoAssessment, PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story
from editorial_studio.segmentation.models import SegmentPrompt
from editorial_studio.segmentation.service import segment
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor
from scripts.install_flagship_assets import assets, verify_assets


def region(bounds):
    x, y, width, height = bounds
    return m.NormalizedRegion(x=x / 420, y=y / 297, width=width / 420, height=height / 297)


def proposal_for(store, context, story, photo, cutout, cfg):
    source = dict(story_sources(store, context.project_id, story))
    nodes, treatments = [], []
    cursors = dict.fromkeys(source, 0)
    for frame in cfg["text_frames"]:
        role = frame["role"]
        text = frame.get("text")
        if text is None:
            parts = cfg["story"]["paragraphs"]
            index = frame["paragraph"]
            text = parts[index] + ("\n\n" if index < len(parts) - 1 else "")
        start = cursors[role]
        end = start + len(text)
        if source[role].text[start:end] != text:
            raise ValueError(f"Authored frame {frame['id']} does not match its source range")
        cursors[role] = end
        nodes.append(
            m.ConceptNode(
                id=frame["id"],
                role="text",
                derived_text_id=source[role].id,
                target_region=region(frame["bounds"]),
                z_order_hint=frame["z"],
            )
        )
        treatments.append(
            NodeTreatment(
                node_id=frame["id"],
                style_role=role,
                style_name=frame["style"],
                text_range=TextRange(start_char=start, end_char=end),
            )
        )
    for key, asset, role, z in [
        ("portrait-atmosphere", photo, "image", 0),
        ("portrait-person", cutout, "subject", 3),
    ]:
        nodes.append(
            m.ConceptNode(
                id=key,
                role=role,
                source_asset_id=asset,
                target_region=region(cfg["photo_bounds"]),
                z_order_hint=z,
            )
        )
        gradient = None
        if role == "image":
            gradient = m.GradientMaskOp(
                target_layer_id=key,
                gradient_type="linear",
                start=m.PointMM(x_mm=cfg["fade_start_mm"], y_mm=0),
                end=m.PointMM(x_mm=cfg["fade_end_mm"], y_mm=0),
                stops=[m.GradientStop(offset=0, opacity=1), m.GradientStop(offset=1, opacity=0)],
            )
        treatments.append(NodeTreatment(node_id=key, gradient=gradient))
    base = yaml.safe_load((ROOT / "config/fonts.yaml").read_text())
    typography = FontConfiguration(
        fonts=[FontSpec.model_validate(f) for f in base["fonts"] + cfg["fonts"]],
        styles=[TypeStyle.model_validate(s) for s in cfg["styles"]],
    )
    return ConceptProposal(
        visual_metaphor="The person interrupts the monumental scale of space.",
        compositional_structure="A portrait enters from the left and the bottom bleed. Oversized condensed lettering bridges its atmosphere and the open right page; two narrow reading columns slow the eye after the display type.",
        photography_treatment="High-resolution NASA original, natural color. A softly receding photographic atmosphere and an exactly registered foreground silhouette share one crop; there is no framed image edge or floating thumbnail.",
        narrative_expression="The orange suit sets the accent; the face remains completely unobstructed. Only a small edge of the first display word passes behind the subject. The rest of the title and all reading copy remain legible.",
        graph=m.SpatialConceptGraph(
            nodes=nodes,
            relationships=[
                m.ConceptRelationship(
                    source_id="title-human",
                    target_id="portrait-person",
                    relation="behind",
                    rationale="The person occupies the same space as the monumental word, without obscuring its reading.",
                )
            ],
        ),
        treatments=treatments,
        typography=ConceptTypography.from_configuration(typography),
        required_capabilities=["CAP_01"],
        inspection_crop=m.BoundsMM(x_mm=192, y_mm=172, width_mm=220, height_mm=123),
        spatial_intent=m.SpatialIntent(mode="guided"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run", required=True, help="Fresh immutable run ID for each authored revision"
    )
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()
    identifier(args.run)
    cfg = yaml.safe_load((ROOT / "config/flagship.yaml").read_text())
    verify_assets(cfg)
    settings = load_settings()
    store = Store(settings.data_root)
    project = cfg["project"]
    context = CallContext(
        project_id=project,
        run_id=args.run,
        agent_name="AuthoredBenchmark",
        stage="Flagship",
        prompt_version="flagship-1",
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    with worker_lock(store):
        identity = build_identity(
            store, context.model_copy(update={"run_id": "flagship-foundation"}), dpi=72
        )
        # A benchmark direction is provisional. The old M7 identity and its review
        # evidence are left intact in their own project.
        identity.bible.conceptual_identity = "The human scale of monumental subjects: photographic presence, forceful type, intimate reading."
        identity.bible.photographic_character = [
            "Natural-color NASA portrait; registered foreground silhouette and receding background."
        ]
        identity.bible.signature_behaviors = [
            "Oversized Anton display words balanced by Newsreader reading copy.",
            "One controlled interruption of type by the person; unobstructed face and readable words.",
        ]
        identity.bible.artistic_boundaries = [
            "Never hide a title word for a depth effect.",
            "No arbitrary texture, floating photo cards or ornamental shapes.",
            "Keep reading type at least 11pt and preserve all source characters.",
        ]
        style_colors = {style["name"]: style["color"] for style in cfg["styles"]}
        palette = {
            "paper": cfg["paper"],
            "ink": style_colors["flagship.body"],
            "muted": style_colors["flagship.section"],
            "accent": style_colors["flagship.space"],
        }
        identity.guidelines.palette_roles = palette
        identity.bible.palette = [
            token.model_copy(update={"hex_color": palette[token.name]})
            for token in identity.bible.palette
        ]
        identity.tokens.palette = list(identity.bible.palette)
        # Save the authored direction under its own ID, without altering the
        # foundation checkpoint used to reproduce the baseline identity proofs.
        identity.id = "flagship-direction"
        store.put_records(("identity", identity.id, project, identity))
        body = "\n\n".join(cfg["story"]["paragraphs"])
        source = next(row for row in assets(cfg) if row["filename"] == "collins-original.jpg")
        story = ingest_story(
            store,
            context,
            StoryInput(
                id=cfg["story"]["id"],
                title=cfg["story"]["title"],
                deck=cfg["story"]["deck"],
                body=body,
                author=cfg["story"]["author"],
                photos=[
                    PhotoInput(
                        filename="collins-original.jpg",
                        data_base64=base64.b64encode(
                            (ROOT / "data/flagship/collins-original.jpg").read_bytes()
                        ).decode(),
                        source_uri=source["url"],
                        credit="NASA / S99-00858",
                    )
                ],
            ),
        )
        photo = store.get("photo", story.photo_assessment_ids[0], PhotoAssessment)
        print("Segmenting high-resolution portrait", flush=True)
        segmentation = segment(
            store,
            context,
            SegmentPrompt(
                source_asset_id=photo.source_asset_id,
                box=m.NormalizedRegion(x=0.01, y=0.07, width=0.98, height=0.93),
                points=[
                    m.NormalizedPoint(x=0.43, y=0.34),
                    m.NormalizedPoint(x=0.38, y=0.65),
                    m.NormalizedPoint(x=0.79, y=0.77),
                    m.NormalizedPoint(x=0.68, y=0.73),
                    m.NormalizedPoint(x=0.82, y=0.68),
                    m.NormalizedPoint(x=0.88, y=0.81),
                    m.NormalizedPoint(x=0.76, y=0.89),
                    m.NormalizedPoint(x=0.86, y=0.45),
                ],
                labels=[1, 1, 1, 1, 1, 1, 1, 0],
                fill_enclosed_holes=True,
                keep_largest_component=True,
            ),
        )
        proposal = proposal_for(
            store, context, story, photo.source_asset_id, segmentation.cutout_asset_id, cfg
        )
        print("Building or loading the authored spread", flush=True)
        spread = build_creative_spread(
            gateway,
            context,
            story.id,
            identity.id,
            proposal=proposal,
            with_visual_critics=args.review,
        )
        target = ROOT / "data/exports/flagship" / args.run
        target.mkdir(parents=True, exist_ok=True)
        for name, asset in [
            ("spread.png", spread.png_asset_id),
            ("spread.pdf", spread.pdf_asset_id),
            ("scene.json", spread.document_asset_id),
            ("metadata.json", spread.metadata_asset_id),
            ("cutout.png", segmentation.cutout_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(project, asset))
        compiled = store.get("concept", spread.concept_id, CompiledConcept)
        review = store.get("creative_review", spread.review_id, CreativeReview)
        for name, asset in [
            ("thumbnail.png", review.inspection.thumbnail_asset_id),
            ("native-crop.png", review.inspection.crop_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(project, asset))
        (target / "concept.json").write_text(compiled.model_dump_json(indent=2))
        (target / "review.json").write_text(review.model_dump_json(indent=2))
        (target / "sketch.png").write_bytes(
            store.read_blob(project, compiled.hybrid.sketch.asset_id)
        )
        (target / "authored-config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
        print(
            json.dumps(
                {
                    "folder": str(target),
                    "execution": review.execution.verdict.value,
                    "findings": [f.description for f in review.execution.findings],
                    "artistic": review.artistic.verdict.value
                    if review.artistic
                    else "not requested",
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
