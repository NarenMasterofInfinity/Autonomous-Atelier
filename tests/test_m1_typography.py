"""Native shaping tests. Expectations come from source clusters and physical geometry."""

import hashlib

import pytest

from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts.models import BoundsMM, TextLayer


@pytest.fixture(scope="module")
def typography():
    return TypographyEngine()


def text_layer(text, *, width=80, height=60):
    return TextLayer(
        id="text",
        name="Text",
        semantic_role="body",
        z_index=0,
        text_content=text,
        style_name="body",
        bounds=BoundsMM(x_mm=10, y_mm=20, width_mm=width, height_mm=height),
    )


def test_whole_run_ligatures_preserve_multicharacter_clusters(typography):
    layer = text_layer("office café")
    result = typography.layout_paragraph(layer).result
    assert len(result.glyphs) < len(layer.text_content)
    assert any(g.cluster_end - g.cluster_start > 1 for g in result.glyphs)
    assert result.consumed_end_char == len(layer.text_content)
    assert not result.findings


def test_kerning_comes_from_shaping_not_character_arithmetic(typography):
    pair = typography.measure_text(text_layer("AV")).logical_bounds.width_mm
    separate = sum(
        typography.measure_text(text_layer(char)).logical_bounds.width_mm for char in "AV"
    )
    assert pair < separate


@pytest.mark.parametrize(
    "text", ["café naïve — 2026; 1.25%", "Αθήνα 123", "Москва 2026", "Hello\n\nA second paragraph."]
)
def test_unicode_and_punctuation_source_offsets(typography, text):
    result = typography.layout_paragraph(text_layer(text)).result
    assert result.overflow_start_char is None and result.consumed_end_char == len(text)
    assert all(0 <= g.cluster_start < g.cluster_end <= len(text) for g in result.glyphs)
    assert not any(f.code == "UNSUPPORTED_SCRIPT" for f in result.findings)


def test_rtl_fallback_is_explicit_and_uses_a_pinned_font(typography):
    report = typography.layout_paragraph(text_layer("العربية"))
    assert report.result.writing_direction == "rtl"
    assert any(f.code == "FONT_FALLBACK" for f in report.result.findings)
    assert any(run.direction == "rtl" for run in report.runs)
    assert {run.font_hash for run in report.runs} <= {
        f.sha256 for f in typography.fonts.config.fonts
    }
    glyphs = report.result.glyphs
    assert glyphs[0].cluster_start > glyphs[-1].cluster_start


def test_unavailable_script_is_reviewable_instead_of_silent(typography):
    report = typography.layout_paragraph(text_layer("क्षेत्र"))
    assert any(
        f.code == "UNSUPPORTED_SCRIPT" and f.severity == "HIGH" for f in report.result.findings
    )


def test_overflow_preserves_unplaced_source_and_never_shrinks(typography):
    layer = text_layer("A quiet room holds the afternoon light. " * 30, width=35, height=15)
    report = typography.fit_text_region(layer, layer.bounds)
    start = report.result.overflow_start_char
    assert start is not None and 0 <= start < len(layer.text_content)
    assert report.result.consumed_end_char == start
    assert report.visible_line_count < report.result.line_count
    assert any(f.code == "TEXT_OVERFLOW" for f in report.result.findings)
    assert "repaginate" in report.copyfit_actions
    assert typography.fonts.styles["body"].font_size_pt == 11


def test_long_unbreakable_word_exposes_horizontal_overflow(typography):
    report = typography.layout_paragraph(text_layer("supercalifragilisticexpialidocious", width=5))
    assert report.result.overflow_start_char == 0


def test_repeated_layout_has_identical_lines_clusters_and_bounds(typography):
    layer = text_layer(
        "A restrained paragraph with café, punctuation, and office ligatures. " * 5, width=55
    )
    one = typography.layout_paragraph(layer)
    two = typography.layout_paragraph(layer)
    assert one == two
    assert one.result.line_count > 1
    assert typography.get_ink_bounds(layer) == one.result.ink_bounds
    assert typography.get_logical_bounds(layer) == one.result.logical_bounds


def test_font_files_match_declared_hashes():
    registry = FontRegistry()
    for spec, path in zip(registry.config.fonts, registry.paths, strict=True):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == spec.sha256


def test_unsupported_writing_direction_is_not_silently_substituted(typography):
    with pytest.raises(ValueError, match="writing directions"):
        typography.layout_paragraph(text_layer("text"), direction="vertical")
