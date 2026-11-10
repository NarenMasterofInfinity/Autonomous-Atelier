import pytest
from test_m8_tournament import inputs as inputs
from test_m8_tournament import proposal

from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.creative.planning import prepare_proposal
from editorial_studio.creative.tournament import configuration, material, provider_materials


def test_display_copyfit_uses_native_font_sizes_and_preserves_body_floor(store, context, inputs):
    identity, story = inputs
    raw = proposal(store, context, story, 0)
    headline = next(n for n in raw.graph.nodes if n.id == "headline")
    headline.target_region.height = 0.035
    materials, _ = material(store, context.project_id, story, identity, configuration())
    visible, bindings = provider_materials(materials)
    assert visible["copy"][0]["derived_text_id"] == "text-headline"
    for node in raw.graph.nodes:
        if node.derived_text_id:
            node.derived_text_id = next(
                key for key, value in bindings.items() if value == node.derived_text_id
            )
    fitted = prepare_proposal(store, context, raw, materials)
    styles = {style.name: style for style in fitted.typography.styles}
    treatments = {t.node_id: t for t in fitted.treatments}
    assert styles[treatments["headline"].style_name].font_size_pt < identity.tokens.type_scale.size(
        "headline"
    )
    assert styles[treatments["body"].style_name].font_size_pt == 11
    engine = TypographyEngine(FontRegistry(configuration=fitted.typography.freeze()))
    text = materials["copy"][0]["text"]
    r = headline.target_region
    result = engine.layout_paragraph(
        m.TextLayer(
            id="headline",
            name="headline",
            semantic_role="headline",
            z_index=0,
            text_content=text,
            style_name=treatments["headline"].style_name,
            bounds=m.BoundsMM(
                x_mm=r.x * 420, y_mm=r.y * 297, width_mm=r.width * 420, height_mm=r.height * 297
            ),
        )
    )
    assert result.result.overflow_start_char is None


def test_planner_rejects_an_impossible_display_frame_instead_of_dropping_text(
    store, context, inputs
):
    identity, story = inputs
    raw = proposal(store, context, story, 0)
    raw.graph.nodes[0].target_region.height = 0.001
    materials, _ = material(store, context.project_id, story, identity, configuration())
    with pytest.raises(ValueError, match="reallocate"):
        prepare_proposal(store, context, raw, materials)


def test_native_image_fit_reserves_real_bleed_and_bounds_automatic_reduction(
    store, context, inputs
):
    identity, story = inputs
    raw = proposal(store, context, story, 0)
    photo = next(n for n in raw.graph.nodes if n.id == "photo")
    photo.target_region = m.NormalizedRegion(x=0, y=0, width=0.6, height=0.68)
    mat, _ = material(store, context.project_id, story, identity, configuration())
    # Independently specified original pixel dimensions and physical print limit.
    row = next(p for p in mat["photos"] if p["asset_id"] == photo.source_asset_id)
    row.update(width_px=3000, height_px=2400)
    fitted = prepare_proposal(
        store,
        context,
        raw,
        mat,
        minimum_image_ppi=300,
        resize_images=True,
        maximum_image_reduction=0.10,
    )
    frame = next(n.target_region for n in fitted.graph.nodes if n.id == "photo")
    assert frame.x == 0 and frame.y == 0
    assert frame.width * 420 + 3 <= 254 + 1e-6
    assert frame.height * 297 + 3 <= 203.2 + 1e-6
    assert next(t for t in fitted.treatments if t.node_id == "photo").image_bleed_mm == 3
    row.update(width_px=1000, height_px=800)
    with pytest.raises(ValueError, match="more than 10%"):
        prepare_proposal(
            store,
            context,
            raw,
            mat,
            minimum_image_ppi=300,
            resize_images=True,
            maximum_image_reduction=0.10,
        )
