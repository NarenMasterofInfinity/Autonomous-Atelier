"""Physical-grid, source-coverage, and identity-token acceptance tests."""

import pytest
from pydantic import ValidationError

from editorial_studio.art_direction.bible import create_bible, generate_guidelines
from editorial_studio.art_direction.service import load_stories
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.design_system.grid import BaselineGrid
from editorial_studio.design_system.layout import BaselineComposer, BaselineCopyfitError
from editorial_studio.design_system.models import GridSpec
from editorial_studio.design_system.system import DesignSystem
from editorial_studio.references.registry import ReferenceCatalog, ReferenceRegistry


@pytest.fixture(scope="module")
def system():
    return DesignSystem()


@pytest.fixture(scope="module")
def bible(system):
    return create_bible("m2-test", system, ["citizen-18", "guggenheim-03"])


def test_grid_has_six_columns_outside_fold_safe_zone(system):
    grid = BaselineGrid(system.tokens.grid)
    assert len(grid.columns) == 6
    assert [c.bounds.x_mm for c in grid.columns] == [20, 82, 144, 220, 282, 344]
    for column in grid.columns:
        b = column.bounds
        assert b.x_mm + b.width_mm <= 200 or b.x_mm >= 220
    assert grid.region(0, 3, 20, 100).width_mm == 180
    assert grid.snap(23) == 25 and grid.snap(25) == 25
    assert grid.on_baseline(25.005) and not grid.on_baseline(26)


@pytest.mark.parametrize(
    "arguments",
    [(2, 2, 20, 100), (0, 0, 20, 100), (-1, 1, 20, 100), (0, 1, 10, 100), (0, 1, 260, 30)],
)
def test_invalid_or_fold_crossing_regions_are_rejected(system, arguments):
    with pytest.raises(ValueError):
        BaselineGrid(system.tokens.grid).region(*arguments)


@pytest.mark.parametrize(
    "values",
    [
        {"columns_per_page": 0},
        {"outer_margin_mm": 205},
        {"top_margin_mm": 290},
        {"width_mm": 400},
        {"baseline_step_mm": float("nan")},
    ],
)
def test_impossible_grid_specs_fail(values):
    with pytest.raises(ValidationError):
        GridSpec(**values)


def test_modular_sizes_and_guidelines_come_from_executable_tokens(system, bible):
    guidelines = generate_guidelines(bible, system, ["citizen-18"])
    styles = {s.name.rsplit(".", 1)[-1]: s for s in system.typography(bible).styles}
    assert styles["headline"].font_size_pt == round(11 * 1.25**6, 3) == guidelines.headline_size_pt
    assert styles["body"].font_size_pt == guidelines.body_size_pt == 11
    assert styles["body"].baseline_step_mm == guidelines.baseline_step_mm == 5
    assert styles["body"].color == guidelines.palette_roles["ink"]
    assert "repaginate" in guidelines.copyfit_actions


@pytest.mark.parametrize("story_index", [0, 1, 2])
def test_three_baseline_stories_preserve_all_copy_and_grid_positions(
    system, bible, store, story_index
):
    story = load_stories()[story_index]
    document, report = BaselineComposer(system, bible).compose(story, story.id)
    layers = {layer.id: layer for layer in document.scene.layers}
    for field, value in [("title", story.title), ("deck", story.deck), ("body", story.body)]:
        placements = [p for p in report.placements if p.field == field]
        assert placements[0].start_char == 0 and placements[-1].end_char == len(value)
        assert all(
            a.end_char == b.start_char for a, b in zip(placements, placements[1:], strict=False)
        )
        assert "".join(layers[p.layer_id].text_content for p in placements) == value
    grid = BaselineGrid(system.tokens.grid)
    assert report.unplaced_body_start is None
    assert all(grid.on_baseline(b) for b in report.body_baselines_mm)
    for layer in document.scene.layers:
        if layer.semantic_role == "body":
            assert layer.bounds.x_mm + layer.bounds.width_mm <= 200 or layer.bounds.x_mm >= 220
    rendered = Renderer(store, "project").render(document, dpi=72)
    native_baselines = [
        line.baseline_mm
        for layout in rendered.metadata.text_layouts
        if layout.result.text_layer_id.startswith("body-")
        for line in layout.lines
    ]
    assert native_baselines == report.body_baselines_mm
    assert all(
        layout.result.overflow_start_char is None for layout in rendered.metadata.text_layouts
    )
    assert CanvasDocument.model_validate_json(document.model_dump_json()) == document


def test_body_copy_really_flows_between_regions(system, bible):
    story = load_stories()[1]
    document, report = BaselineComposer(system, bible).compose(story, story.id)
    assert len([p for p in report.placements if p.field == "body"]) == 2


def test_unplaceable_copy_is_reported_without_shrinking_or_silent_loss(system, bible):
    story = load_stories()[0].model_copy(update={"paragraphs": ["Unplaced source words. " * 1000]})
    with pytest.raises(BaselineCopyfitError) as caught:
        BaselineComposer(system, bible).compose(story, story.id)
    assert caught.value.report.unplaced_body_start < len(story.body)
    assert system.tokens.type_scale.body_pt == 11


def test_frozen_identity_styles_survive_later_default_style_changes(system, bible, store):
    document, _ = BaselineComposer(system, bible).compose(load_stories()[0], "frozen")
    renderer = Renderer(store, "project")
    before = renderer.render(document, dpi=72)
    renderer.typography.fonts.styles["body"].font_size_pt = 16
    renderer.typography.fonts.styles["headline"].color = "#ff00ff"
    after = renderer.render(document, dpi=72)
    assert before.png == after.png
    assert before.metadata.text_layouts == after.metadata.text_layouts


def test_two_pairings_produce_distinct_headline_styles_without_changing_body_size(system):
    serif = create_bible("serif", system, ["citizen-18"])
    sans = create_bible("sans", system, ["citizen-18"], pairing_id="direct-sans")
    a = {s.name.rsplit(".", 1)[-1]: s for s in system.typography(serif).styles}
    b = {s.name.rsplit(".", 1)[-1]: s for s in system.typography(sans).styles}
    assert a["headline"].font_id != b["headline"].font_id
    assert a["body"].font_size_pt == b["body"].font_size_pt == 11


def test_unknown_pairings_and_references_are_rejected(system):
    with pytest.raises(ValueError):
        create_bible("bad", system, ["citizen-18"], pairing_id="unknown")
    with pytest.raises(ValueError):
        create_bible("bad", system, ["unknown"])
    with pytest.raises(ValueError):
        create_bible("bad", system, [])


def test_manual_reference_catalog_has_twenty_distinct_traceable_spread_examples():
    registry = ReferenceRegistry()
    entries = registry.catalog.references
    assert len(entries) == 20 and len({r.id for r in entries}) == 20
    assert len({str(r.image_url) for r in entries}) == 20
    assert all(r.kind in {"spread", "spread_series"} and r.source_image_name for r in entries)
    assert {r.publication for r in entries} == {"Citizen", "413 / Port", "Guggenheim"}
    filtered = registry.search(["portrait"])
    assert filtered and all("portrait" in r.tags for r in filtered)
    assert registry.search(["unknown-tag"]) == []
    duplicate = registry.catalog.model_dump()
    duplicate["references"].append(duplicate["references"][0])
    with pytest.raises(ValidationError):
        ReferenceCatalog.model_validate(duplicate)


def test_reference_preview_is_local_and_hash_checked(tmp_path, monkeypatch):
    import hashlib

    import yaml

    import editorial_studio.references.registry as module

    entry = ReferenceRegistry().catalog.references[0].model_copy(deep=True)
    data = b"preview-fixture"
    path = tmp_path / "data/references/preview.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    entry.preview_path = "data/references/preview.jpg"
    entry.preview_sha256 = hashlib.sha256(data).hexdigest()
    catalog = tmp_path / "references.yaml"
    catalog.write_text(
        yaml.safe_dump({"version": "test", "references": [entry.model_dump(mode="json")]})
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    registry = ReferenceRegistry(catalog)
    assert registry.preview(entry.id) == data
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        registry.preview(entry.id)
    path.unlink()
    assert registry.preview(entry.id) is None


def test_direct_sans_pairing_renders_all_three_story_proofs(system, store):
    bible = create_bible("sans-native", system, ["citizen-18"], pairing_id="direct-sans")
    for story in load_stories():
        document, report = BaselineComposer(system, bible).compose(story, story.id)
        rendered = Renderer(store, "project").render(document, dpi=72)
        assert report.unplaced_body_start is None
        assert not any(
            layout.result.overflow_start_char is not None
            for layout in rendered.metadata.text_layouts
        )


def test_reading_regions_prefer_complete_paragraphs(system, bible):
    story = load_stories()[1]
    document, report = BaselineComposer(system, bible).compose(story, story.id)
    body = [placement for placement in report.placements if placement.field == "body"]
    assert len(body) == 2
    assert story.body[: body[0].end_char].endswith("\n\n")
    assert story.body[body[1].start_char :].startswith(story.paragraphs[3])


@pytest.mark.parametrize("field", ["title", "deck"])
def test_frontmatter_overflow_is_measured_and_reported_before_publication(system, bible, field):
    story = load_stories()[0].model_copy(update={field: "Oversized front matter. " * 300})
    with pytest.raises(BaselineCopyfitError) as caught:
        BaselineComposer(system, bible).compose(story, story.id)
    assert caught.value.report.unplaced_fields == [field]
    evidence = next(f for f in caught.value.report.text_fit if f.field == field)
    assert evidence.overflow_start_char is not None
    assert evidence.consumed_end_char < evidence.source_char_count
