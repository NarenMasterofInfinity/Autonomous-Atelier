import numpy as np
import pymupdf
import pytest
from PIL import Image
from test_m9_issue import IssueProvider
from test_m9_issue import issue_inputs as issue_inputs

from editorial_studio.canvas.models import LayerPresentation
from editorial_studio.contracts import models as m
from editorial_studio.creative.issue import build_issue
from editorial_studio.llm.gateway import Gateway
from editorial_studio.photos.models import PlacementAssessment, UpscaleResult
from editorial_studio.photos.pipeline import png
from editorial_studio.production.models import ProductionPreflight
from editorial_studio.production.service import (
    export_production,
    native_sources,
    pdf_fonts,
    sampling_for_image,
)


def test_complete_issue_exports_twelve_bleed_pages_with_subset_fonts_and_snapshot_binding(
    store, context, issue_inputs, pricing
):
    identity, stories = issue_inputs
    provider = IssueProvider(store, context, stories)
    issue = build_issue(
        Gateway(store, provider, pricing), context, [s.id for s in stories], identity.id
    )
    export_context = context.model_copy(update={"run_id": "print-export", "stage": "M10"})
    output = export_production(
        store, export_context, issue.id, expected_evidence_fingerprint=issue.evidence_fingerprint
    )
    report = store.get("production_preflight", output.id, ProductionPreflight)
    assert report.passed, [f.model_dump() for f in report.findings]
    assert output.state == "proof" and output.page_count == 12 and not output.human_approval
    assert all(sample.native_ppi >= 300 for sample in report.sampling)
    with pymupdf.open(
        stream=store.read_blob(context.project_id, output.pdf_asset_id), filetype="pdf"
    ) as pdf:
        assert len(pdf) == 12
        for page in pdf:
            assert abs(page.trimbox.width * 25.4 / 72 - 210) < 0.001
            assert abs(page.trimbox.height * 25.4 / 72 - 297) < 0.001
            assert abs(page.mediabox.width * 25.4 / 72 - 216) < 0.001
            assert abs(page.mediabox.height * 25.4 / 72 - 303) < 0.001
        assert "Source 0" in pdf[0].get_text()
        assert "Source 0" not in pdf[11].get_text()
        # Independent pixel truth: the back-cover photograph continues into
        # the actual left bleed, rather than leaving a padded paper border.
        pix = pdf[11].get_pixmap(dpi=72, alpha=False)
        assert pix.pixel(round(1.5 * 72 / 25.4), round(70 * 72 / 25.4)) == (120, 100, 70)
    assert (
        export_production(
            store,
            export_context,
            issue.id,
            expected_evidence_fingerprint=issue.evidence_fingerprint,
        )
        == output
    )
    assert provider.calls == 20

    report_bytes = store.read_blob(context.project_id, output.preflight_asset_id)
    (store.root / context.project_id / "blobs" / output.preflight_asset_id).unlink()
    with pytest.raises(FileNotFoundError):
        export_production(
            store,
            export_context,
            issue.id,
            expected_evidence_fingerprint=issue.evidence_fingerprint,
        )
    assert (
        store.put_blob(context.project_id, report_bytes, "application/json").id
        == output.preflight_asset_id
    )

    # A later discovered enlargement lineage invalidates the cached preflight;
    # the same 5000px raster no longer counts as native 5000px photography.
    sample = report.sampling[0]
    low = store.put_blob(
        context.project_id, png(Image.new("RGB", (500, 500), (120, 100, 70))), "image/png"
    )
    placement = PlacementAssessment(
        source_asset_id=low.id,
        frame=m.BoundsMM(x_mm=0, y_mm=0, width_mm=100, height_mm=100),
        effective_ppi=127,
        original_ppi=127,
        visible_source_fraction=1,
        status="stylize_or_reduce",
        upscale_eligible=False,
        requires_visual_review=True,
    )
    store.put_records(
        (
            "upscale",
            "discovered-lineage",
            context.project_id,
            UpscaleResult(
                source_asset_id=low.id,
                output_asset_id=sample.asset_id,
                backend="fixture",
                model_sha256="fixture",
                scale=10,
                placement=placement,
            ),
        )
    )
    with pytest.raises(ValueError, match="different issue evidence"):
        export_production(
            store,
            export_context,
            issue.id,
            expected_evidence_fingerprint=issue.evidence_fingerprint,
        )
    blocked = export_production(
        store,
        context.model_copy(update={"run_id": "low-resolution-export"}),
        issue.id,
        expected_evidence_fingerprint=issue.evidence_fingerprint,
    )
    blocked_report = store.get("production_preflight", blocked.id, ProductionPreflight)
    assert blocked.state == "blocked" and blocked.pdf_asset_id is None and blocked.page_count == 0
    assert any(f.code == "SOURCE_PPI" and f.severity == "error" for f in blocked_report.findings)
    assert provider.calls == 20
    with pytest.raises(ValueError, match="stale"):
        export_production(
            store,
            context.model_copy(update={"run_id": "stale-export"}),
            issue.id,
            expected_evidence_fingerprint="wrong",
        )
    (store.root / context.project_id / "blobs" / output.preflight_asset_id).unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        export_production(
            store,
            export_context,
            issue.id,
            expected_evidence_fingerprint=issue.evidence_fingerprint,
        )
    assert provider.calls == 20


def test_worst_axis_sampling_includes_affine_stretch_and_preserves_upscale_risk(store):
    original = store.put_blob("project", png(Image.new("RGB", (400, 400), "#887766")), "image/png")
    enlarged = store.put_blob("project", png(Image.new("RGB", (800, 800), "#887766")), "image/png")
    frame = m.BoundsMM(x_mm=20, y_mm=30, width_mm=50.8, height_mm=50.8)
    placement = PlacementAssessment(
        source_asset_id=original.id,
        frame=frame,
        effective_ppi=200,
        original_ppi=200,
        visible_source_fraction=1,
        status="inspect_crop",
        upscale_eligible=True,
        requires_visual_review=True,
    )
    lineage = UpscaleResult(
        source_asset_id=original.id,
        output_asset_id=enlarged.id,
        backend="independent-fixture",
        model_sha256="fixture",
        scale=2,
        placement=placement,
    )
    store.put_records(("upscale", "fixture-upscale", "project", lineage))
    layer = m.ImageLayer(
        id="photo",
        name="photo",
        semantic_role="image",
        z_index=0,
        bounds=frame,
        asset_id=enlarged.id,
    )
    presentation = LayerPresentation(layer_id=layer.id, source_bounds=frame)
    sample = sampling_for_image(
        store, "project", layer, presentation, np.eye(3), native_sources(store, "project")
    )
    assert sample.effective_ppi == pytest.approx(400) and sample.native_ppi == pytest.approx(200)
    stretched = sampling_for_image(
        store, "project", layer, presentation, np.diag([2, 1, 1]), native_sources(store, "project")
    )
    assert stretched.native_ppi == pytest.approx(100)
    cropped = store.put_blob("project", png(Image.new("RGB", (200, 200), "#887766")), "image/png")
    store.put_records(
        (
            "upscale",
            "unsupported-crop",
            "project",
            lineage.model_copy(update={"output_asset_id": cropped.id}),
        )
    )
    with pytest.raises(ValueError, match="geometry is unsupported or cropped"):
        native_sources(store, "project")


def test_standard_unembedded_font_fails_production_preflight():
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((20, 30), "Unembedded Helvetica")
    errors, count = pdf_fonts(pdf)
    assert count == 1 and any(f.code == "FONT_NOT_EMBEDDED" for f in errors)
    pdf.close()


def test_bleed_checks_each_actual_shape_component_instead_of_global_extents():
    from shapely.geometry import box
    from shapely.ops import unary_union

    from editorial_studio.production.service import missing_bleed_sides

    # The upper fragment has real bleed; the lower fragment ends at trim.
    shape = unary_union([box(-3, 20, 12, 30), box(0, 40, 12, 50)])
    assert missing_bleed_sides(shape, 3, 0.05) == ["LEFT"]
    assert missing_bleed_sides(box(-3, 20, 12, 50), 3, 0.05) == []
    detached = unary_union([box(-0.1, -4, 424, 301), box(-4, -4, -2.5, 301)])
    assert "LEFT" in missing_bleed_sides(detached, 3, 0.01)
