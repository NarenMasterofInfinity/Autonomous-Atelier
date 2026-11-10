from pathlib import Path

import pytest
import yaml
from test_m8_tournament import inputs as inputs
from test_m8_tournament import proposal

from editorial_studio.canvas.models import LayerPresentation
from editorial_studio.canvas.typography.advanced import AdvancedTypography
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontConfiguration, FontRegistry, TypeStyle
from editorial_studio.contracts import models as m
from editorial_studio.creative.planning import prepare_proposal
from editorial_studio.creative.tournament import configuration, material


def typography():
    fonts = (
        yaml.safe_load(Path("config/fonts.yaml").read_text())["fonts"]
        + yaml.safe_load(Path("config/flagship.yaml").read_text())["fonts"]
    )
    return TypographyEngine(
        FontRegistry(
            configuration=FontConfiguration(
                fonts=fonts,
                styles=[
                    TypeStyle(
                        name="display", font_id="Newsreader", font_size_pt=72, color="#22211f"
                    )
                ],
            )
        )
    )


def layer():
    return m.TextLayer(
        id="type",
        name="Type",
        semantic_role="headline",
        z_index=0,
        text_content="Human scale",
        style_name="display",
        bounds=m.BoundsMM(x_mm=15, y_mm=20, width_mm=250, height_mm=70),
    )


def test_tracking_alignment_and_cache_follow_changed_style():
    engine = typography()
    text = layer()
    old = engine.layout_paragraph(text)
    engine.fonts.styles["display"] = engine.fonts.styles["display"].model_copy(
        update={"tracking_pt": 3}
    )
    spaced = engine.layout_paragraph(text)
    assert spaced.result.logical_bounds.width_mm > old.result.logical_bounds.width_mm + 6
    assert spaced.result.glyphs[-1].position.x_mm > old.result.glyphs[-1].position.x_mm + 6
    engine.fonts.styles["display"] = engine.fonts.styles["display"].model_copy(
        update={"tracking_pt": 0, "alignment": "right"}
    )
    right = engine.layout_paragraph(text)
    assert right.result.ink_bounds.x_mm > old.result.ink_bounds.x_mm + 80
    assert right.result.consumed_end_char == len(text.text_content)


def test_per_style_axes_change_native_and_vector_outlines_consistently():
    from editorial_studio.canvas.typography.fonts import StyleAxis

    engine = typography()
    text = layer()
    advanced = AdvancedTypography(engine)
    state = LayerPresentation(layer_id=text.id, source_bounds=text.bounds, outline_text=True)
    normal, normal_glyphs = advanced.layout(text, state)
    engine.fonts.styles["display"] = engine.fonts.styles["display"].model_copy(
        update={"font_axes": [StyleAxis(tag="wght", value=750)]}
    )
    heavy, heavy_glyphs = advanced.layout(text, state)
    assert normal_glyphs[0].path != heavy_glyphs[0].path
    assert (
        heavy.result.consumed_end_char == normal.result.consumed_end_char == len(text.text_content)
    )
    cfg = engine.fonts.config.model_copy(deep=True)
    cfg.styles[0].font_axes = [StyleAxis(tag="FAKE", value=1)]
    with pytest.raises(ValueError, match="Unsupported per-style axis"):
        FontRegistry(configuration=cfg)


def test_outline_style_requires_actual_stroke_and_preserves_defaults():
    with pytest.raises(ValueError, match="outline type requires"):
        TypeStyle(
            name="outline", font_id="Anton", font_size_pt=130, color="#111111", paint="stroke"
        )
    old = TypeStyle(name="old", font_id="Anton", font_size_pt=130, color="#111111")
    assert old.tracking_pt == 0 and old.alignment == "left" and old.paint == "fill"


def test_display_floor_rejects_a_small_frame_instead_of_weakening_type(store, context, inputs):
    identity, story = inputs
    raw = proposal(store, context, story, 0)
    headline = next(n for n in raw.graph.nodes if n.id == "headline")
    headline.target_region.height = 0.035
    treatment = next(t for t in raw.treatments if t.node_id == "headline")
    treatment.minimum_display_pt = 40
    materials, _ = material(store, context.project_id, story, identity, configuration())
    with pytest.raises(ValueError, match="reallocate"):
        prepare_proposal(store, context, raw, materials)


def test_display_measurements_follow_each_pinned_face_and_fit_natively(store, context, inputs):
    identity, story = inputs
    identity.pairing.body_font_id = "DejaVuSans"
    cfg = {**configuration(), "preserve_display_scale": True, "quality_reference": None}
    materials, _ = material(store, context.project_id, story, identity, cfg)
    words = next(row for row in materials["copy"] if row["role"] == "headline")[
        "native_display_word_boxes"
    ]
    assert {row["font_id"] for row in words} == {"DejaVuSerif", "DejaVuSans"}
    from editorial_studio.creative.models import ConceptTypography

    typed = ConceptTypography.model_validate(materials["available_typography"])
    engine = TypographyEngine(FontRegistry(configuration=typed.freeze()))
    for sample in words:
        engine.fonts.styles["sample"] = TypeStyle(
            name="sample",
            font_id=sample["font_id"],
            font_size_pt=sample["font_size_pt"],
            color="#22211f",
            line_spacing=1,
            min_paragraph_lines=1,
        )
        text = layer().model_copy(
            update={
                "text_content": sample["text"],
                "style_name": "sample",
                "bounds": m.BoundsMM(
                    x_mm=0,
                    y_mm=0,
                    width_mm=sample["native_width_mm"] + 1,
                    height_mm=sample["native_height_mm"] + 1,
                ),
            }
        )
        assert engine.layout_paragraph(text).result.overflow_start_char is None


def test_raster_silhouette_normalizes_pixel_necks_without_weakening_authored_paths(store):
    from PIL import Image, ImageDraw

    from editorial_studio.canvas.typography.paths import region
    from editorial_studio.photos.pipeline import png
    from editorial_studio.segmentation.geometry import silhouette_path

    image = Image.new("L", (80, 80))
    d = ImageDraw.Draw(image)
    d.rectangle((10, 10, 30, 30), fill=255)
    d.rectangle((30, 30, 50, 50), fill=255)
    d.line((2, 2, 6, 2), fill=255)
    asset = store.put_blob("project", png(image), "image/png")
    path = silhouette_path(
        store,
        "project",
        asset.id,
        m.BoundsMM(x_mm=0, y_mm=0, width_mm=80, height_mm=80),
        is_mask=True,
    )
    shape = region(path)
    assert shape.is_valid and 700 < shape.area < 900
