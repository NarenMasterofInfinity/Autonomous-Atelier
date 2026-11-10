"""Live studio trial conditioned on reviewed authored references, without their coordinates."""

import argparse
import json
from io import BytesIO

import pymupdf
from PIL import Image

from editorial_studio.art_direction.service import build_identity
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.typography.fonts import FontConfiguration
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.compiler import source_partitions
from editorial_studio.creative.models import CompiledConcept, CreativeReview
from editorial_studio.creative.tournament import build_tournament
from editorial_studio.design_system.models import FontPairing, PairingCatalog
from editorial_studio.design_system.system import DesignSystem
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.photos.models import IngestedStory
from editorial_studio.reference_studio.authoring import fonts
from editorial_studio.reference_studio.catalog import references
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="m10a-studio-v2")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    ctx = CallContext(
        project_id="m10a-references",
        run_id=args.run,
        agent_name="M10AStudioTrial",
        stage="M10A",
    )
    gateway = Gateway(
        store,
        OpenAIProvider(settings),
        PricingTable.load(settings.pricing_path),
        Redactor([settings.api_key.get_secret_value()]),
    )
    with worker_lock(store):
        refs = references(store, ctx.project_id, reviewed_only=True)
        selected = [
            next(r for r in refs if r.design_id == key)
            for key in [
                "01-depth-portrait",
                "02-photo-overlay",
                "05-outline-globe",
                "11-serif-portrait",
            ]
        ]
        pairing = FontPairing(
            id="m10a-editorial",
            name="Anton / Newsreader editorial",
            headline_font_id="Anton",
            body_font_id="Newsreader",
            detail_font_id="DejaVuSans",
            intent="Photographic depth and expressive large display, with native serif reading.",
        )
        system = DesignSystem(
            pairing_catalog=PairingCatalog(pairings=[pairing]),
            font_configuration=FontConfiguration(fonts=fonts(), styles=[]),
        )
        identity = build_identity(
            store,
            ctx.model_copy(update={"run_id": "m10a-studio-identity"}),
            pairing_id=pairing.id,
            system=system,
            dpi=72,
        )
        story_id = selected[0].story_id
        from editorial_studio.reference_studio.generation import (
            configuration as atlas_configuration,
        )

        cfg = atlas_configuration([r.id for r in selected], ctx.project_id, version=args.run)
        result = build_tournament(
            gateway,
            ctx,
            story_id,
            identity.id,
            mandate="Improve the visual sophistication of the current portrait spread using the authored reference atlas. Keep the same copy and photo source. This is a generation trial, not owner or professional approval.",
            continuation_configuration=cfg,
        )
        root = ROOT / "data/exports/m10a" / args.run
        root.mkdir(parents=True, exist_ok=True)
        for name, asset in [
            ("candidates.pdf", result.proof_book_asset_id),
            ("contact-sheet.png", result.contact_sheet_asset_id),
        ]:
            (root / name).write_bytes(store.read_blob(ctx.project_id, asset))
        (root / "tournament.json").write_text(result.model_dump_json(indent=2))
        checks = []
        story = store.get("story", story_id, IngestedStory)
        for c in result.candidates:
            p = store.get("concept", c.concept_id, CompiledConcept)
            source_partitions(store, ctx.project_id, story, p.proposal)
            folder = root / c.slot_id
            folder.mkdir(exist_ok=True)
            for name, asset in [
                ("spread.png", c.png_asset_id),
                ("spread.pdf", c.pdf_asset_id),
                ("scene.json", c.document_asset_id),
                ("metadata.json", c.metadata_asset_id),
            ]:
                (folder / name).write_bytes(store.read_blob(ctx.project_id, asset))
            (folder / "concept.json").write_text(p.model_dump_json(indent=2))
            review = store.get("creative_review", c.review_id, CreativeReview)
            (folder / "review.json").write_text(review.model_dump_json(indent=2))
            document = CanvasDocument.model_validate_json((folder / "scene.json").read_bytes())
            sampling = []
            for layer in document.scene.layers:
                if layer.layer_type == "image":
                    image = Image.open(BytesIO(store.read_blob(ctx.project_id, layer.asset_id)))
                    sampling.append(
                        min(
                            image.width / layer.bounds.width_mm,
                            image.height / layer.bounds.height_mm,
                        )
                        * 25.4
                    )
            assert min(sampling) >= 299.99
            with pymupdf.open(folder / "spread.pdf") as pdf:
                assert len(pdf) == 1
                page = pdf[0]
                assert abs(page.rect.width * 25.4 / 72 - 420) < 0.001
                assert abs(page.rect.height * 25.4 / 72 - 297) < 0.001
                for font in page.get_fonts(full=True):
                    assert font[0] and pdf.extract_font(font[0])[3]
            checks.append(
                {
                    "candidate": c.slot_id,
                    "source_partitions": "exact",
                    "minimum_source_ppi": min(sampling),
                    "pdf_mm": [420, 297],
                    "execution": review.execution.verdict.value,
                    "artistic": review.artistic.verdict.value,
                    "decision": review.decision.verdict.value,
                    "human_approval": False,
                }
            )
        (root / "verification.json").write_text(
            json.dumps(
                {
                    "candidates": checks,
                    "scope": "Source, native sampling, dimensions and font embedding; not aesthetic approval.",
                },
                indent=2,
            )
        )
        print(
            json.dumps(
                {
                    "tournament": result.id,
                    "winner": result.winner_id,
                    "state": result.state,
                    "references": [r.id for r in selected],
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
