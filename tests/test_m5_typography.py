import math

import pytest
from shapely.geometry import box

from editorial_studio.canvas.models import CanvasDocument, LayerPresentation
from editorial_studio.canvas.renderer import LayoutRejected, Renderer
from editorial_studio.canvas.typography.advanced import AdvancedTypography
from editorial_studio.canvas.typography.advanced_models import PathTextSpec, ShapeFlowSpec
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.paths import ArcLengthPath, region
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import utcnow


def rect(x, y, w, h):
    return m.PathGeometry(
        commands=[
            m.MoveTo(p=m.PointMM(x_mm=x, y_mm=y)),
            m.LineTo(p=m.PointMM(x_mm=x + w, y_mm=y)),
            m.LineTo(p=m.PointMM(x_mm=x + w, y_mm=y + h)),
            m.LineTo(p=m.PointMM(x_mm=x, y_mm=y + h)),
            m.ClosePath(),
        ]
    )


def layer(text="Office, café — affinity.", style="headline"):
    return m.TextLayer(
        id="type",
        name="Type",
        semantic_role="headline",
        z_index=0,
        text_content=text,
        style_name=style,
        derived_text_id="retained-source",
        bounds=m.BoundsMM(x_mm=20, y_mm=20, width_mm=350, height_mm=50),
    )


@pytest.fixture(scope="module")
def advanced():
    return AdvancedTypography(TypographyEngine())


def test_arc_length_straight_and_bezier_against_independent_dense_sampling():
    straight = m.PathGeometry(
        commands=[m.MoveTo(p=m.PointMM(x_mm=0, y_mm=0)), m.LineTo(p=m.PointMM(x_mm=30, y_mm=40))]
    )
    arc = ArcLengthPath(straight)
    assert arc.length == 50 and arc.at(25) == pytest.approx(
        (15, 20, math.degrees(math.atan2(40, 30)))
    )
    curve = m.PathGeometry(
        commands=[
            m.MoveTo(p=m.PointMM(x_mm=0, y_mm=0)),
            m.CubicTo(
                control1=m.PointMM(x_mm=0, y_mm=100),
                control2=m.PointMM(x_mm=100, y_mm=100),
                p=m.PointMM(x_mm=100, y_mm=0),
            ),
        ]
    )
    arc = ArcLengthPath(curve)
    assert abs(arc.length - 200) < 0.01
    x, y, tangent = arc.at(arc.length / 2)
    assert (x, y) == pytest.approx((50, 75), abs=0.01) and abs(tangent) < 1


def test_path_text_uses_shaped_clusters_and_tangents(advanced):
    item = layer()
    path = m.PathGeometry(
        commands=[
            m.MoveTo(p=m.PointMM(x_mm=25, y_mm=100)),
            m.CubicTo(
                control1=m.PointMM(x_mm=140, y_mm=20),
                control2=m.PointMM(x_mm=250, y_mm=180),
                p=m.PointMM(x_mm=390, y_mm=100),
            ),
        ]
    )
    p = LayerPresentation(
        layer_id=item.id, source_bounds=item.bounds, path_text=PathTextSpec(path=path)
    )
    report, glyphs = advanced.layout(item, p)
    assert report.result.overflow_start_char is None
    assert any(g.cluster_end - g.cluster_start > 1 for g in glyphs)
    assert len({round(g.tangent_deg, 1) for g in glyphs}) > 5
    assert all(g.font_hash for g in glyphs) and any(g.path for g in glyphs)
    assert (
        item.text_content == "Office, café — affinity."
        and item.derived_text_id == "retained-source"
    )


def test_path_overflow_preserves_whole_clusters_and_upside_down_warning(advanced):
    item = layer("Office affinity")
    short = m.PathGeometry(
        commands=[m.MoveTo(p=m.PointMM(x_mm=0, y_mm=50)), m.LineTo(p=m.PointMM(x_mm=10, y_mm=50))]
    )
    r, g = advanced.layout(
        item,
        LayerPresentation(
            layer_id=item.id, source_bounds=item.bounds, path_text=PathTextSpec(path=short)
        ),
    )
    assert r.result.overflow_start_char is not None and all(
        x.cluster_end <= r.result.consumed_end_char for x in g
    )
    reverse = m.PathGeometry(
        commands=[
            m.MoveTo(p=m.PointMM(x_mm=390, y_mm=100)),
            m.LineTo(p=m.PointMM(x_mm=20, y_mm=100)),
        ]
    )
    r, _ = advanced.layout(
        item,
        LayerPresentation(
            layer_id=item.id, source_bounds=item.bounds, path_text=PathTextSpec(path=reverse)
        ),
    )
    assert any(f.code == "UNREADABLE_ORIENTATION" for f in r.result.findings)


def test_irregular_flow_respects_donut_hole_and_exclusion_and_keeps_source(advanced):
    boundary = rect(20, 20, 180, 160)
    hole = rect(75, 60, 55, 65)
    compound = m.PathGeometry(commands=boundary.commands + hole.commands, fill_rule="evenodd")
    shape = region(compound)
    assert shape.area == pytest.approx(180 * 160 - 55 * 65)
    item = layer("A paragraph with café, office ligatures, and deliberate spacing. " * 15, "body")
    p = LayerPresentation(
        layer_id=item.id, source_bounds=item.bounds, shape_flow=ShapeFlowSpec(boundary=compound)
    )
    report, glyphs = advanced.layout(item, p)
    assert report.result.overflow_start_char is None and report.result.consumed_end_char == len(
        item.text_content
    )
    assert report.lines[0].start_char == 0 and report.lines[-1].end_char == len(item.text_content)
    assert all(
        a.end_char == b.start_char for a, b in zip(report.lines, report.lines[1:], strict=False)
    )
    for line in report.lines:
        b = line.logical_bounds
        assert shape.buffer(0.01).covers(
            box(b.x_mm, b.y_mm, b.x_mm + b.width_mm, b.y_mm + b.height_mm)
        )
    assert glyphs and len({g.glyph_index for g in glyphs}) == len(glyphs)
    assert all(g.cluster_end <= len(item.text_content) for g in glyphs)


def test_shape_overflow_and_unavailable_glyph_transform_rejected(advanced, store):
    item = layer("Too much source text. " * 100, "body")
    p = LayerPresentation(
        layer_id=item.id,
        source_bounds=item.bounds,
        shape_flow=ShapeFlowSpec(boundary=rect(20, 20, 25, 15)),
    )
    report, _ = advanced.layout(item, p)
    assert report.result.overflow_start_char < len(item.text_content)
    doc = CanvasDocument(
        scene=m.Scene(
            id="overflow",
            spread_id="overflow",
            version="v1",
            width_mm=420,
            height_mm=297,
            design_language_id="test",
            created_at=utcnow(),
            layers=[item],
        ),
        presentations=[p],
    )
    with pytest.raises(LayoutRejected):
        Renderer(store, "project").render(doc, dpi=72)
    p = LayerPresentation(
        layer_id=item.id,
        source_bounds=item.bounds,
        glyph_transforms=[m.GlyphTransform(glyph_index=999999)],
    )
    with pytest.raises(ValueError, match="shaped glyph index"):
        advanced.layout(item, p)


def test_all_ten_techniques_execute_registered_operations_and_export_vector_proofs(store, context):
    import pymupdf

    from editorial_studio.canvas.executor import Executor
    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.contracts.capability_matrix import CAPABILITIES
    from editorial_studio.spatial.proofs import build_capability_proofs

    proofs = build_capability_proofs(store, context, dpi=72)
    assert len(proofs) == 10 and all(p.status == "technically_verified" for p in proofs)
    assert (
        len(
            Executor(
                SceneRepository(store, "project"), Renderer(store, "project")
            ).supported_operations
        )
        == 21
    )
    for proof, capability in zip(proofs, CAPABILITIES, strict=True):
        assert set(capability.operation_names) <= set(proof.operation_names)
        with pymupdf.open(
            stream=store.read_blob("project", proof.pdf_asset_id), filetype="pdf"
        ) as pdf:
            assert len(pdf) == 1 and pdf[0].rect.width == pytest.approx(420 * 72 / 25.4, abs=0.01)
        assert store.read_blob("project", proof.thumbnail_asset_id) and store.read_blob(
            "project", proof.crop_asset_id
        )
    assert build_capability_proofs(store, context, dpi=72) == proofs


def test_new_effect_operations_and_boolean_paths_are_reproducible(store, context):
    from editorial_studio.canvas.executor import Executor
    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.spatial.assistant import SpatialAssistant
    from editorial_studio.spatial.skills import fixture_assets

    repo = SceneRepository(store, "project")
    executor = Executor(repo, Renderer(store, "project"))
    doc = CanvasDocument.from_scene(
        m.Scene(
            id="effects",
            spread_id="effects",
            version="initial",
            width_mm=420,
            height_mm=297,
            design_language_id="proof",
            created_at=utcnow(),
        )
    )
    executor.initialize(doc, context, dpi=72)
    photo, mask = fixture_assets(store, "project")
    ops = [
        m.AddImageOp(
            layer_id="image",
            asset_id=photo,
            bounds=m.BoundsMM(x_mm=20, y_mm=20, width_mm=150, height_mm=140),
        ),
        m.AddPathOp(layer_id="a", path=rect(200, 20, 80, 80), fill_color="#ff0000"),
        m.AddPathOp(layer_id="b", path=rect(230, 50, 80, 80)),
        m.SetOpacityOp(layer_id="b", opacity=0),
        m.BooleanPathOp(target_layer_id="a", operand_layer_id="b", operation_type="difference"),
        m.DisplacementMapOp(target_layer_id="image", map_asset_id=mask, scale_mm=2),
        m.ApplyFilterOp(layer_id="image", filter=m.BlurFilter(radius_mm=0.2)),
        m.ApplyFilterOp(
            layer_id="image",
            filter=m.ShadowFilter(
                offset=m.PointMM(x_mm=2, y_mm=2), radius_mm=1, rgba_hex="#00000088"
            ),
        ),
        m.ApplyFilterOp(layer_id="image", filter=m.HalftoneFilter(dot_spacing_mm=1, angle_deg=20)),
        m.GradientMaskOp(
            target_layer_id="image",
            gradient_type="radial",
            start=m.PointMM(x_mm=90, y_mm=90),
            end=m.PointMM(x_mm=160, y_mm=90),
            stops=[m.GradientStop(offset=0, opacity=1), m.GradientStop(offset=1, opacity=0)],
        ),
    ]
    SpatialAssistant(executor).apply(ops, "effects", context, dpi=72)
    saved = repo.load("effects")
    output = Renderer(store, "project").render(saved, dpi=72)
    assert output.png == Renderer(store, "project").render(saved, dpi=72).png
    a = next(item for item in saved.scene.layers if item.id == "a")
    assert region(a.path).area == pytest.approx(80 * 80 - 50 * 50)


def test_thin_exclusion_between_line_samples_cannot_be_crossed(advanced):
    text = layer("A readable line must avoid even a thin closed exclusion. " * 8, "body")
    boundary = rect(20, 20, 160, 80)
    thin = rect(50, 22, 100, 0.3)
    p = LayerPresentation(
        layer_id=text.id,
        source_bounds=text.bounds,
        shape_flow=ShapeFlowSpec(boundary=boundary, exclusion_paths=[thin]),
    )
    report, _ = advanced.layout(text, p)
    available = region(boundary).difference(region(thin))
    for line in report.lines:
        b = line.logical_bounds
        assert available.buffer(0.001).covers(
            box(b.x_mm, b.y_mm, b.x_mm + b.width_mm, b.y_mm + b.height_mm)
        )


def test_rtl_shape_flow_reports_source_direction(advanced):
    text = layer("مرحبا بالعالم. هذه فقرة عربية قصيرة. " * 4, "body")
    p = LayerPresentation(
        layer_id=text.id,
        source_bounds=text.bounds,
        shape_flow=ShapeFlowSpec(
            boundary=rect(20, 20, 180, 100), exclusion_paths=[rect(95, 20, 20, 100)]
        ),
    )
    report, _ = advanced.layout(text, p)
    assert report.result.writing_direction == "rtl"
    assert report.lines[0].logical_bounds.x_mm > 115


def test_truncated_path_has_consistent_placed_run_and_source_evidence(advanced):
    text = layer("Office affinity")
    path = m.PathGeometry(
        commands=[m.MoveTo(p=m.PointMM(x_mm=20, y_mm=50)), m.LineTo(p=m.PointMM(x_mm=35, y_mm=50))]
    )
    report, glyphs = advanced.layout(
        text,
        LayerPresentation(
            layer_id=text.id, source_bounds=text.bounds, path_text=PathTextSpec(path=path)
        ),
    )
    assert {g.index for run in report.runs for g in run.glyphs} == {g.glyph_index for g in glyphs}
    assert all(
        g.cluster_end <= report.result.consumed_end_char for run in report.runs for g in run.glyphs
    )


def test_spatial_assistant_solves_anchors_as_transactional_operations(store, context):
    from editorial_studio.canvas.executor import Executor
    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.spatial.assistant import SpatialAssistant

    repo = SceneRepository(store, "project")
    executor = Executor(repo, Renderer(store, "project"))
    doc = CanvasDocument.from_scene(
        m.Scene(
            id="anchors",
            spread_id="anchors",
            version="initial",
            width_mm=420,
            height_mm=297,
            design_language_id="proof",
            created_at=utcnow(),
            layers=[
                m.VectorLayer(
                    id="a",
                    name="A",
                    semantic_role="graphic",
                    z_index=0,
                    bounds=m.BoundsMM(x_mm=20, y_mm=20, width_mm=50, height_mm=50),
                    path=rect(20, 20, 50, 50),
                    fill_color="#ff0000",
                ),
                m.VectorLayer(
                    id="b",
                    name="B",
                    semantic_role="graphic",
                    z_index=1,
                    bounds=m.BoundsMM(x_mm=100, y_mm=20, width_mm=50, height_mm=50),
                    path=rect(100, 20, 50, 50),
                    fill_color="#0000ff",
                ),
            ],
        )
    )
    executor.initialize(doc, context, dpi=72)
    intent = m.SpatialIntent(
        mode="guided",
        anchor_relationships=[
            m.AnchorRelationship(
                source_layer_id="a",
                target_layer_id="b",
                relationship_type="align_left",
                offset_mm=3,
            ),
            m.AnchorRelationship(
                source_layer_id="a", target_layer_id="b", relationship_type="above"
            ),
        ],
    )
    version = SpatialAssistant(executor).solve(intent, "anchors", context, dpi=72)
    saved = repo.load("anchors")
    layers = {item.id: item for item in saved.scene.layers}
    assert layers["a"].bounds.x_mm == 103 and layers["a"].z_index > layers["b"].z_index
    assert version.parent_version == "initial" and len(repo.history("anchors")) == 2
    intent.anchor_relationships.append(
        m.AnchorRelationship(source_layer_id="b", target_layer_id="a", relationship_type="above")
    )
    with pytest.raises(ValueError, match="cycle"):
        SpatialAssistant(executor).solve(intent, "anchors", context, dpi=72)


def test_advanced_glyph_paths_remain_vector_and_pdf_matches_preview(store):
    from io import BytesIO

    import numpy as np
    import pymupdf
    from PIL import Image

    text = layer("Office, café — affinity.")
    path = m.PathGeometry(
        commands=[
            m.MoveTo(p=m.PointMM(x_mm=25, y_mm=90)),
            m.CubicTo(
                control1=m.PointMM(x_mm=140, y_mm=40),
                control2=m.PointMM(x_mm=260, y_mm=150),
                p=m.PointMM(x_mm=390, y_mm=90),
            ),
        ]
    )
    presentation = LayerPresentation(
        layer_id=text.id, source_bounds=text.bounds, path_text=PathTextSpec(path=path)
    )
    doc = CanvasDocument(
        scene=m.Scene(
            id="vector-path",
            spread_id="vector-path",
            version="v1",
            width_mm=420,
            height_mm=297,
            design_language_id="proof",
            created_at=utcnow(),
            layers=[text],
        ),
        presentations=[presentation],
    )
    output = Renderer(store, "project").render(doc, dpi=72)
    with pymupdf.open(stream=output.pdf, filetype="pdf") as pdf:
        assert len(pdf[0].get_drawings()) > 10 and not pdf[0].get_images()
        pix = pdf[0].get_pixmap(alpha=False)
        rendered = np.frombuffer(pix.samples, dtype="uint8").reshape(pix.height, pix.width, 3)
    preview = np.asarray(Image.open(BytesIO(output.png)).convert("RGB"))
    assert (
        preview.shape == rendered.shape
        and np.abs(preview.astype("float32") - rendered).mean() < 1.0
    )


def test_right_side_path_reverses_traversal_without_reversing_source_clusters(advanced):
    text = layer("ABC")
    path = m.PathGeometry(
        commands=[m.MoveTo(p=m.PointMM(x_mm=20, y_mm=60)), m.LineTo(p=m.PointMM(x_mm=200, y_mm=60))]
    )
    report, glyphs = advanced.layout(
        text,
        LayerPresentation(
            layer_id=text.id,
            source_bounds=text.bounds,
            path_text=PathTextSpec(path=path, side="right"),
        ),
    )
    assert report.result.overflow_start_char is None
    assert glyphs[0].x_mm == pytest.approx(200) and glyphs[-1].x_mm < glyphs[0].x_mm
    assert [g.cluster_start for g in glyphs] == [0, 1, 2]


def test_halftone_preserves_white_black_and_alpha_endpoints():
    from PIL import Image

    from editorial_studio.canvas.effects import process

    p = LayerPresentation(
        layer_id="photo",
        source_bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=20, height_mm=20),
        filters=[m.HalftoneFilter(dot_spacing_mm=1)],
    )
    for value in (0, 255):
        output = process(Image.new("RGBA", (64, 64), (value, value, value, 128)), p, lambda _: None)
        assert output.getchannel("R").getextrema() == (value, value)
        assert output.getchannel("A").getextrema() == (128, 128)
