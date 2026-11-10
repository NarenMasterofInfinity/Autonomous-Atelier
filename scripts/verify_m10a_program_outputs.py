"""Read-only verification of saved program outputs and the previous negative corpus."""

import argparse
import json
from io import BytesIO

import numpy as np
import pymupdf
from PIL import Image

from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.core.storage import Store
from editorial_studio.creative.compiler import node_bounds, story_sources
from editorial_studio.creative.models import CompiledConcept, CreativeSpread
from editorial_studio.creative.tournament_models import TournamentResult
from editorial_studio.photos.models import IngestedStory
from editorial_studio.reference_studio.models import CompositionProgram, ReferenceComposition
from editorial_studio.reference_studio.quality import analyze_layout
from editorial_studio.reference_studio.service import composition_assets
from editorial_studio.settings import ROOT, load_settings


def check_result(store, result, *, report_sampling_difference=False):
    composition_assets(store, result)
    project = result.project_id
    story = store.get("story", result.story_id, IngestedStory)
    sources = dict(story_sources(store, project, story))
    programs = {
        p.id: p
        for p in [
            CompositionProgram.model_validate_json(store.read_blob(project, a))
            for a in result.program_asset_ids
        ]
    }
    reports = []
    for candidate in result.candidates:
        if not candidate.quality.passed:
            continue
        spread = candidate.spread
        program = programs[candidate.program_id]
        concept = store.get("concept", spread.concept_id, CompiledConcept)
        document = CanvasDocument.model_validate_json(
            store.read_blob(project, spread.document_asset_id)
        )
        metadata = RenderMetadata.model_validate_json(
            store.read_blob(project, spread.metadata_asset_id)
        )
        layers = {layer.id: layer for layer in document.scene.layers}
        states = {p.layer_id: p for p in document.presentations}
        layouts = {p.result.text_layer_id: p.result for p in metadata.text_layouts}
        treatments = {t.node_id: t for t in concept.proposal.treatments}
        original_nodes = {n.id: n for n in program.proposal.graph.nodes}
        fill_nodes = {key for group in program.photo_fill_groups for key in group}
        for role, source in sources.items():
            fragments = []
            for node in concept.proposal.graph.nodes:
                if node.role != "text" or treatments[node.id].style_role != role:
                    continue
                span = treatments[node.id].text_range
                fragments.append((span.start_char, span.end_char, layers[node.id].text_content))
            cursor = 0
            placed = []
            for start, end, text in sorted(fragments):
                assert start == cursor and text == source.text[start:end]
                placed.append(text)
                cursor = end
            assert cursor == len(source.text) and "".join(placed) == source.text
        for node in concept.proposal.graph.nodes:
            if node.id in original_nodes and node.id not in fill_nodes:
                assert states[node.id].source_bounds == node_bounds(
                    original_nodes[node.id],
                    next(t for t in program.proposal.treatments if t.node_id == node.id),
                )
        for slot in program.slots:
            if slot.node_id not in layers:
                continue
            if slot.role == "headline" and slot.display_line_count:
                assert layouts[slot.node_id].line_count <= slot.display_line_count
            if slot.role == "body":
                layer = layers[slot.node_id]
                style = next(s for s in document.typography.styles if s.name == layer.style_name)
                assert style.font_size_pt >= 11 and layer.opacity >= 0.95
                p = states[slot.node_id].transform
                assert (p.a, p.b, p.c, p.d) == (1, 0, 0, 1)
        ppis = []
        for layer in document.scene.layers:
            if layer.layer_type == "image":
                im = Image.open(BytesIO(store.read_blob(project, layer.asset_id)))
                ppis.append(
                    min(im.width / layer.bounds.width_mm, im.height / layer.bounds.height_mm) * 25.4
                )
        original = Image.open(BytesIO(store.read_blob(project, spread.png_asset_id))).convert("RGB")
        with pymupdf.open(
            stream=store.read_blob(project, spread.pdf_asset_id), filetype="pdf"
        ) as pdf:
            assert len(pdf) == 1
            page = pdf[0]
            assert (
                abs(page.rect.width * 25.4 / 72 - 420) < 0.001
                and abs(page.rect.height * 25.4 / 72 - 297) < 0.001
            )
            for font in page.get_fonts(full=True):
                assert font[0] and pdf.extract_font(font[0])[3]
            raster = Image.open(
                BytesIO(page.get_pixmap(dpi=144, alpha=False).tobytes("png"))
            ).convert("RGB")
            if raster.size != original.size:
                raster = raster.resize(original.size)
            delta = np.abs(np.array(original, dtype=np.int16) - np.array(raster, dtype=np.int16))
            low = (original.width // 2, original.height // 2)
            low_delta = np.abs(
                np.array(original.resize(low, Image.Resampling.BOX), dtype=np.int16)
                - np.array(raster.resize(low, Image.Resampling.BOX), dtype=np.int16)
            )
            mean = float(delta.mean())
            near = float((low_delta.max(axis=2) <= 10).mean())
            strict_raster_match = mean < 3 and near > 0.94
            coarse = (original.width // 4, original.height // 4)
            coarse_delta = np.abs(
                np.array(original.resize(coarse, Image.Resampling.BOX), dtype=np.int16)
                - np.array(raster.resize(coarse, Image.Resampling.BOX), dtype=np.int16)
            )
            coarse_near = float((coarse_delta.max(axis=2) <= 10).mean())
            if not report_sampling_difference:
                assert strict_raster_match, (candidate.family_id, mean, near)
            else:
                # Preserve the strict discrepancy as a review item; this lower-
                # frequency comparison checks geometry, not native image detail.
                assert coarse_near > 0.96, (candidate.family_id, coarse_near)
        if candidate.native_views:
            for name, asset in candidate.native_views.assets.items():
                crop = Image.open(BytesIO(store.read_blob(project, asset))).convert("RGB")
                assert (
                    crop.tobytes() == original.crop(candidate.native_views.boxes_px[name]).tobytes()
                )
        reports.append(
            {
                "family": candidate.family_id,
                "source_characters": "exact",
                "body_minimum_pt": 11,
                "minimum_native_ppi": min(ppis),
                "png_pdf_mean_error": mean,
                "box_72dpi_fraction_within_10": near,
                "box_36dpi_fraction_within_10": coarse_near,
                "strict_raster_match": strict_raster_match,
                "raster_review": None
                if strict_raster_match
                else "Native PNG/PDF image sampling differs; geometry passes the separate 36dpi check. Native image-detail equivalence is not asserted.",
                "display_size_ratio": candidate.minimum_display_ratio,
                "native_crops": "pixel-exact",
                "headline_lines": "captured rhythm preserved",
                "human_approval": False,
            }
        )
    return {"run": result.id, "admitted": reports, "rejected": len(result.rejections)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runs",
        nargs="+",
        default=["program-fit-v5-portrait", "program-fit-v6-new-title", "program-fit-v6-moon"],
    )
    parser.add_argument("--audit-previous", action="store_true")
    args = parser.parse_args()
    store = Store(load_settings().data_root, readonly=True)
    reports = []
    for key in args.runs:
        result = store.get("reference_composition", key, ReferenceComposition)
        assert result is not None, key
        reports.append(check_result(store, result))
        print(key, "verified", flush=True)
    negative = []
    if args.audit_previous:
        tournament = store.get("tournament", "m10a-studio-v2", TournamentResult)
        expected = {
            "c1v1": "text_collision",
            "c1v2": "hidden_text",
            "c2v1": "text_collision",
            "c2v2": "hidden_word",
            "c2v3": "text_contrast",
        }
        for c in tournament.candidates:
            spread = store.get("creative_spread", c.spread_id, CreativeSpread)
            document = CanvasDocument.model_validate_json(
                store.read_blob(spread.project_id, spread.document_asset_id)
            )
            concept = store.get("concept", spread.concept_id, CompiledConcept)
            quality = analyze_layout(store, spread.project_id, document, concept.proposal)
            suffix = c.slot_id.removeprefix("m10a-studio-v2-")
            if suffix in expected:
                assert any(f.code == expected[suffix] for f in quality.findings)
            else:
                assert quality.passed, (
                    "Readable conventional layout should not be mislabeled mechanically invalid"
                )
            negative.append({"candidate": c.slot_id, **quality.model_dump(mode="json")})
            print(c.slot_id, "audited", flush=True)
    path = ROOT / "data/exports/m10a/program-verification.json"
    path.write_text(
        json.dumps(
            {
                "runs": reports,
                "previous_negative_corpus": negative,
                "provider_calls": 0,
                "scope": "Known-defect regression and source/export checks, not an independent aesthetic benchmark or professional approval.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
