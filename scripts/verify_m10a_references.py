"""Independent artifact checks of the authored atlas; no aesthetic score or API call."""

import json
from io import BytesIO

import numpy as np
import pymupdf
from PIL import Image

from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.core.storage import Store
from editorial_studio.creative.compiler import source_partitions
from editorial_studio.creative.models import CompiledConcept, CreativeReview
from editorial_studio.photos.models import IngestedStory
from editorial_studio.reference_studio.catalog import proof_assets, references
from editorial_studio.settings import ROOT, load_settings


def main():
    s = Store(load_settings().data_root, readonly=True)
    rows = references(s)
    reports = []
    assert len(rows) == 12 and len({r.family_id for r in rows}) == 10
    for r in rows:
        proof_assets(s, r)
        c = s.get("concept", r.spread.concept_id, CompiledConcept)
        story = s.get("story", r.story_id, IngestedStory)
        source_partitions(s, r.project_id, story, c.proposal)
        review = s.get("creative_review", r.spread.review_id, CreativeReview)
        assert review.execution.verdict.value == "ACCEPT" and not r.human_approval
        doc = CanvasDocument.model_validate_json(
            s.read_blob(r.project_id, r.spread.document_asset_id)
        )
        image = np.array(
            Image.open(BytesIO(s.read_blob(r.project_id, r.spread.png_asset_id))).convert("RGB"),
            dtype=np.int16,
        )
        with pymupdf.open(
            stream=s.read_blob(r.project_id, r.spread.pdf_asset_id), filetype="pdf"
        ) as pdf:
            assert len(pdf) == 1
            page = pdf[0]
            assert (
                abs(page.rect.width * 25.4 / 72 - 420) < 0.001
                and abs(page.rect.height * 25.4 / 72 - 297) < 0.001
            )
            pix = page.get_pixmap(dpi=144, alpha=False)
            actual = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
            if actual.size != (image.shape[1], image.shape[0]):
                actual = actual.resize((image.shape[1], image.shape[0]))
            delta = np.abs(image - np.array(actual, dtype=np.int16))
            mean = float(delta.mean())
            near = float((delta.max(axis=2) <= 10).mean())
            # Preserve raw diagnostics. Cairo and MuPDF use different image
            # resampling at 144dpi, especially detailed alpha photographs on
            # dark paper. Compare structure at a shared 72dpi box-filtered
            # scale as well; font/source/geometry checks remain independent.
            target = (image.shape[1] // 2, image.shape[0] // 2)
            expected_low = Image.fromarray(image.astype("uint8")).resize(
                target, Image.Resampling.BOX
            )
            actual_low = actual.resize(target, Image.Resampling.BOX)
            low_delta = np.abs(
                np.array(expected_low, dtype=np.int16) - np.array(actual_low, dtype=np.int16)
            )
            low_mean = float(low_delta.mean())
            low_near = float((low_delta.max(axis=2) <= 10).mean())
            assert mean < 3 and low_mean < 3 and low_near > 0.94, (
                r.design_id,
                mean,
                near,
                low_mean,
                low_near,
            )
            for font in page.get_fonts(full=True):
                assert font[0] and pdf.extract_font(font[0])[3]
        sampling = []
        for layer in doc.scene.layers:
            if layer.layer_type == "image":
                im = Image.open(BytesIO(s.read_blob(r.project_id, layer.asset_id)))
                sampling.append(
                    min(im.width / layer.bounds.width_mm, im.height / layer.bounds.height_mm) * 25.4
                )
        reports.append(
            {
                "reference_id": r.id,
                "design_id": r.design_id,
                "family": r.family_id,
                "authorship": r.authorship,
                "human_approval": False,
                "source_partitions": "exact",
                "execution": "ACCEPT",
                "pdf_size_mm": [420, 297],
                "png_pdf_mean_error": mean,
                "png_pdf_fraction_within_10": near,
                "box_72dpi_mean_error": low_mean,
                "box_72dpi_fraction_within_10": low_near,
                "minimum_source_ppi": min(sampling),
                "scope": "Authored study; not M10 print approval or professional artistic certification.",
            }
        )
        print(r.design_id, "parity", round(mean, 3), round(near, 4), flush=True)
    target = ROOT / "data/exports/m10a/m10a-v3/verification.json"
    target.write_text(
        json.dumps(
            {
                "references": reports,
                "reference_count": len(rows),
                "family_count": len({r.family_id for r in rows}),
                "api_calls": 0,
            },
            indent=2,
        )
    )
    print("Verified authored atlas; API calls: 0", flush=True)


if __name__ == "__main__":
    main()
