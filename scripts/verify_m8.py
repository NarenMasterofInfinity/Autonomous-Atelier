"""Live M8 acceptance, using approved public imagery and the durable gateway."""

import argparse
import base64

import yaml

from editorial_studio.art_direction.service import build_identity
from editorial_studio.canvas.typography.fonts import FontConfiguration
from editorial_studio.contracts import models as m
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store, identifier, utcnow
from editorial_studio.creative.tournament import build_tournament
from editorial_studio.creative.tournament_models import MilestoneAcceptance
from editorial_studio.design_system.models import FontPairing, PairingCatalog
from editorial_studio.design_system.system import DesignSystem
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


def setup(store, context):
    cfg = yaml.safe_load((ROOT / "config/flagship.yaml").read_text())
    verify_assets(cfg)
    default = yaml.safe_load((ROOT / "config/fonts.yaml").read_text())
    typography = FontConfiguration(fonts=default["fonts"] + cfg["fonts"], styles=default["styles"])
    pairing = FontPairing(
        id="portrait-editorial",
        name="Anton / Newsreader",
        headline_font_id="Anton",
        body_font_id="Newsreader",
        detail_font_id="DejaVuSans",
        intent="Photographic presence, strong display type, intimate reading.",
    )
    system = DesignSystem(
        font_configuration=typography, pairing_catalog=PairingCatalog(pairings=[pairing])
    )
    palette = {"paper": cfg["paper"], "ink": "#202b35", "muted": "#68645b", "accent": "#d94a23"}
    system.tokens.palette = [
        m.PaletteToken(name=key, hex_color=color) for key, color in palette.items()
    ]
    identity = build_identity(
        store,
        context.model_copy(update={"run_id": context.run_id + "-identity"}),
        pairing_id=pairing.id,
        system=system,
        dpi=72,
    )
    identity.bible.conceptual_identity = "The human scale of monumental subjects: photographic presence, forceful display type, intimate reading."
    identity.bible.signature_behaviors = [
        "Oversized condensed display words balanced by measured serif reading columns.",
        "Photography and typography share one spatial idea; restrained overlap keeps words and faces readable.",
    ]
    identity.bible.photographic_character = [
        "Natural source color and texture.",
        "Deliberate cropping and registered silhouettes; no floating photographic thumbnails or obligatory effects.",
    ]
    identity.bible.artistic_boundaries = [
        "Never hide a complete headline word for an effect.",
        "Keep reading type >=11pt and preserve all source characters.",
        "Avoid detached rectangular image/text allocations when the story permits stronger integration.",
    ]
    store.put_records(("identity", identity.id, context.project_id, identity))
    source = next(row for row in assets(cfg) if row["filename"] == "collins-original.jpg")
    story = ingest_story(
        store,
        context,
        StoryInput(
            id="human-scale-m8",
            title=cfg["story"]["title"],
            deck="Before the mission, a person. A portrait study of Eileen Collins. Photograph: NASA.",
            body="\n\n".join(cfg["story"]["paragraphs"]),
            author=cfg["story"]["author"],
            photos=[
                PhotoInput(
                    filename=source["filename"],
                    data_base64=base64.b64encode(
                        (ROOT / "data/flagship" / source["filename"]).read_bytes()
                    ).decode(),
                    source_uri=source["url"],
                    credit=source["credit"],
                )
            ],
        ),
    )
    photo = store.get("photo", story.photo_assessment_ids[0], PhotoAssessment)
    segment(
        store,
        context,
        SegmentPrompt(
            source_asset_id=photo.source_asset_id,
            box=m.NormalizedRegion(x=0.01, y=0.07, width=0.98, height=0.93),
            points=[
                m.NormalizedPoint(x=x, y=y)
                for x, y in [
                    (0.43, 0.34),
                    (0.38, 0.65),
                    (0.79, 0.77),
                    (0.68, 0.73),
                    (0.82, 0.68),
                    (0.88, 0.81),
                    (0.76, 0.89),
                    (0.86, 0.45),
                ]
            ],
            labels=[1, 1, 1, 1, 1, 1, 1, 0],
            fill_enclosed_holes=True,
            keep_largest_component=True,
        ),
    )
    return identity, story


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="m8-live-v1")
    parser.add_argument("--resume-policy", action="store_true")
    args = parser.parse_args()
    identifier(args.run)
    settings = load_settings()
    store = Store(settings.data_root)
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    context = CallContext(
        project_id="m8-proof",
        run_id=args.run,
        agent_name="TournamentAcceptance",
        stage="M8",
        prompt_version="m8-v1",
    )
    with worker_lock(store):
        if not store.get("milestone_acceptance", "m7-owner-acceptance", MilestoneAcceptance):
            approval = MilestoneAcceptance(
                id="m7-owner-acceptance",
                project_id="flagship-proof",
                milestone="M7",
                actor="user",
                note="M7 looks good. let us go and takle m8, m9, m10",
                evidence_ids=["portrait-06"],
                recorded_at=utcnow(),
            )
            store.put_records(("milestone_acceptance", approval.id, approval.project_id, approval))
        identity, story = setup(store, context)
        print("Building six candidates and visual tournament", flush=True)
        result = build_tournament(
            gateway,
            context,
            story.id,
            identity.id,
            mandate="Keep the accepted flagship's level of intention, but invent six layouts from the actual story and portrait. Do not copy its authored coordinates. Make the image belong to each composition. Preserve natural color; no filler effects. Use native >=300 PPI photograph placement for future print export.",
            continuation_configuration=__import__(
                "editorial_studio.creative.tournament", fromlist=["configuration"]
            ).configuration()
            if args.resume_policy
            else None,
        )
        target = ROOT / "data/exports/m8-proof" / args.run
        target.mkdir(parents=True, exist_ok=True)
        for name, asset in [
            ("contact-sheet.png", result.contact_sheet_asset_id),
            ("candidates.pdf", result.proof_book_asset_id),
        ]:
            (target / name).write_bytes(store.read_blob(context.project_id, asset))
        (target / "tournament.json").write_text(result.model_dump_json(indent=2))
        for candidate in result.candidates:
            folder = target / candidate.slot_id
            folder.mkdir(exist_ok=True)
            for name, asset in [
                ("spread.png", candidate.png_asset_id),
                ("spread.pdf", candidate.pdf_asset_id),
                ("scene.json", candidate.document_asset_id),
                ("metadata.json", candidate.metadata_asset_id),
            ]:
                (folder / name).write_bytes(store.read_blob(context.project_id, asset))
        print(result.model_dump_json(indent=2), flush=True)


if __name__ == "__main__":
    main()
