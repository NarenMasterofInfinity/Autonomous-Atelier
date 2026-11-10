"""Check saved benchmark artifacts without rendering again or issuing API calls."""

import argparse
import hashlib
import json
import re

import numpy as np
import pymupdf
from PIL import Image

from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import Store, identifier
from editorial_studio.creative.compiler import source_partitions
from editorial_studio.creative.models import CompiledConcept, CreativeReview, CreativeSpread
from editorial_studio.photos.models import IngestedStory
from editorial_studio.settings import ROOT, load_settings


def verify(run):
    identifier(run)
    store = Store(load_settings().data_root, readonly=True)
    project = "flagship-proof"
    spread = store.get("creative_spread", run, CreativeSpread)
    if spread is None or spread.project_id != project:
        raise ValueError("saved flagship run not found")
    target = ROOT / "data/exports/flagship" / run
    compiled = store.get("concept", spread.concept_id, CompiledConcept)
    review = store.get("creative_review", spread.review_id, CreativeReview)
    story = store.get("story", spread.story_id, IngestedStory)
    version = SceneRepository(store, project).head(spread.scene_id)
    assert version.version == spread.scene_version
    files = {
        "spread.png": spread.png_asset_id,
        "spread.pdf": spread.pdf_asset_id,
        "scene.json": spread.document_asset_id,
        "metadata.json": spread.metadata_asset_id,
    }
    for filename, asset in files.items():
        assert (target / filename).read_bytes() == store.read_blob(project, asset), filename
    document = CanvasDocument.model_validate_json((target / "scene.json").read_bytes())
    metadata = RenderMetadata.model_validate_json((target / "metadata.json").read_bytes())
    assert (
        hashlib.sha256((target / "scene.json").read_bytes()).hexdigest() == metadata.document_hash
    )
    assert document.typography == compiled.typography and document.enforce_text_provenance
    assert all(layout.result.overflow_start_char is None for layout in metadata.text_layouts)
    layers = {layer.id: layer for layer in document.scene.layers}
    represented = {}
    for node, (role, source, start, end) in source_partitions(
        store, project, story, compiled.proposal
    ).items():
        layer = layers[node]
        assert isinstance(layer, m.TextLayer) and layer.text_content == source.text[start:end]
        derived = store.get("derived_text", layer.derived_text_id, m.DerivedText)
        assert derived.text == layer.text_content
        represented.setdefault(role, []).append((start, end, layer.text_content))
    with pymupdf.open(target / "spread.pdf") as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert abs(page.rect.width * 25.4 / 72 - 420) < 0.001
        assert abs(page.rect.height * 25.4 / 72 - 297) < 0.001
        font_ids = {font[0] for font in page.get_fonts(full=True)}
        assert font_ids and all(pdf.extract_font(xref)[3] for xref in font_ids)
        extracted = re.sub(r"\s+", " ", page.get_text())
        for rows in represented.values():
            for _, _, text in rows:
                assert re.sub(r"\s+", " ", text).strip() in extracted
        pix = page.get_pixmap(dpi=round(metadata.dpi), alpha=False)
        preview = Image.open(target / "spread.png").convert("RGB")
        assert preview.size == (pix.width, pix.height)
        raster = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[
            :, :, :3
        ]
        delta = np.abs(np.array(preview, dtype=np.int16) - raster.astype(np.int16))
        mean_error = float(delta.mean())
        near_fraction = float((delta.max(axis=2) <= 10).mean())
        # Different rasterizers antialias glyphs differently; detect material
        # layout/export divergence without requiring identical edge pixels.
        assert mean_error < 3 and near_fraction > 0.95
    report = {
        "run": run,
        "authorship": compiled.authorship,
        "scope": "One authored benchmark; no autonomous-quality or print-preflight claim.",
        "checks": "Saved assets, source partitions, text extraction, embedded fonts, physical page size and PNG/PDF raster agreement passed.",
        "source_characters": {
            role: sum(end - start for start, end, _ in rows) for role, rows in represented.items()
        },
        "pdf_embedded_fonts": len(font_ids),
        "png_pdf_mean_channel_error": mean_error,
        "png_pdf_fraction_within_10": near_fraction,
        "model_verdicts": {
            name: getattr(review, name).verdict.value if getattr(review, name) else None
            for name in ("execution", "artistic", "fidelity")
        },
        "human_approval": review.human_approval,
    }
    (target / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    print(json.dumps(verify(parser.parse_args().run), indent=2))
