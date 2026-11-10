import cv2
import numpy as np
import pytest
from PIL import Image

from editorial_studio.contracts.models import NormalizedPoint
from editorial_studio.photos.pipeline import png
from editorial_studio.segmentation.models import SegmentPrompt
from editorial_studio.segmentation.service import edge_quality, refine_alpha, segment


def test_solid_subject_hole_filling_preserves_exterior_and_open_concavities():
    from editorial_studio.segmentation.service import fill_enclosed_holes

    mask = np.zeros((100, 100), dtype="uint8")
    mask[10:90, 10:90] = 255
    mask[40:60, 40:60] = 0
    mask[10:35, 45:55] = 0
    filled = fill_enclosed_holes(mask)
    assert filled[50, 50] == 255  # enclosed helmet-like dropout
    assert filled[20, 50] == 0  # genuine exterior-connected negative space
    assert filled[0, 0] == 0
    assert np.all(filled[mask == 255] == 255)
    # The exterior seed must also work when the foreground meets all four edges.
    edge = np.full((20, 20), 255, dtype="uint8")
    edge[8:12, 8:12] = 0
    assert fill_enclosed_holes(edge).min() == 255


class KnownSilhouette:
    name = "independent-test-backend"
    model_sha256 = "fixture"

    def predict(self, rgb, prompt):
        mask = np.zeros(rgb.shape[:2], dtype="uint8")
        cv2.circle(mask, (50, 50), 30, 255, -1)
        return mask, 0.95


def test_refinement_preserves_known_interior_exterior_and_silhouette():
    rng = np.random.default_rng(21)
    rgb = rng.integers(0, 256, (100, 100, 3), dtype="uint8")
    mask = np.zeros((100, 100), dtype="uint8")
    cv2.circle(mask, (50, 50), 30, 255, -1)
    alpha = refine_alpha(rgb, mask)
    assert alpha[50, 50] == 255 and alpha[0, 0] == 0 and np.any((alpha > 0) & (alpha < 255))
    q = edge_quality(alpha, mask)
    assert q.passed and q.reference_iou > 0.98
    assert not edge_quality(np.zeros((100, 100), dtype="uint8")).passed
    assert not edge_quality(np.full((100, 100), 255, dtype="uint8")).passed


def test_cutout_retains_source_dimensions_alpha_and_idempotent_trace(store, context):
    source = store.put_blob("project", png(Image.new("RGB", (100, 100), "#995533")), "image/png")
    prompt = SegmentPrompt(
        source_asset_id=source.id, points=[NormalizedPoint(x=0.5, y=0.5)], labels=[1]
    )
    result = segment(store, context, prompt, KnownSilhouette())
    assert result.quality.passed and result.human_review_required
    assert segment(store, context, prompt, KnownSilhouette()) == result
    from io import BytesIO

    image = Image.open(BytesIO(store.read_blob("project", result.cutout_asset_id)))
    assert image.mode == "RGBA" and image.size == (100, 100) and image.getpixel((0, 0))[3] == 0
    with pytest.raises(ValueError):
        SegmentPrompt(source_asset_id=source.id, points=prompt.points, labels=[])


def test_opt_in_solid_subject_cleanup_drops_dust_and_restores_only_enclosed_holes(store, context):
    from io import BytesIO

    class NoisySilhouette(KnownSilhouette):
        name = "independent-noisy-silhouette"

        def predict(self, rgb, prompt):
            mask, score = super().predict(rgb, prompt)
            mask[45:55, 45:55] = 0
            mask[2:4, 2:4] = 255
            return mask, score

    source = store.put_blob("project", png(Image.new("RGB", (100, 100), "#995533")), "image/png")
    prompt = SegmentPrompt(
        source_asset_id=source.id, points=[NormalizedPoint(x=0.6, y=0.6)], labels=[1]
    )
    original = segment(store, context, prompt, NoisySilhouette())
    cleaned = segment(
        store,
        context,
        prompt.model_copy(update={"fill_enclosed_holes": True, "keep_largest_component": True}),
        NoisySilhouette(),
    )
    a = Image.open(BytesIO(store.read_blob("project", original.alpha_asset_id)))
    b = Image.open(BytesIO(store.read_blob("project", cleaned.alpha_asset_id)))
    cut = Image.open(BytesIO(store.read_blob("project", cleaned.cutout_asset_id)))
    assert a.getpixel((50, 50)) == 0 and b.getpixel((50, 50)) == 255
    assert b.getpixel((2, 2)) == 0 and b.getpixel((10, 10)) == 0
    assert cut.getpixel((50, 50)) == (153, 85, 51, 255)
    assert cleaned.id != original.id and cleaned.quality.components == 1


def test_real_mobilesam_import_and_hash_pin():
    import hashlib

    from editorial_studio.segmentation.service import configuration
    from editorial_studio.settings import ROOT

    cfg = configuration()
    path = ROOT / cfg["checkpoint"]
    if not path.exists():
        pytest.skip("optional local model not installed")
    import mobile_sam

    assert "vit_t" in mobile_sam.sam_model_registry
    assert hashlib.sha256(path.read_bytes()).hexdigest() == cfg["sha256"]
