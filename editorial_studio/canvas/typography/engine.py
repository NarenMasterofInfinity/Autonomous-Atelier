"""Pango/HarfBuzz shapes whole runs in canonical 72-dpi point coordinates.

The pinned Pango serialization is consumed only as a native adapter, then
normalized into our stable typed glyph records. Native serialized layouts are
never used as the durable scene format.
"""

import hashlib
import json
from typing import Literal

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

from editorial_studio.canvas.geometry import PT_PER_MM
from editorial_studio.canvas.models import GlyphDetail, ParagraphLayout, ShapedRun, TextLine
from editorial_studio.canvas.typography.fonts import FontRegistry, verify_native_libraries
from editorial_studio.contracts.models import (
    BoundsMM,
    PointMM,
    ShapedGlyphPlacement,
    TextLayer,
    TextLayoutResult,
    TypographyFinding,
)

UNIT = Pango.SCALE * PT_PER_MM


def rectangle(rect, origin: BoundsMM) -> BoundsMM:
    return BoundsMM(
        x_mm=origin.x_mm + rect.x / UNIT,
        y_mm=origin.y_mm + rect.y / UNIT,
        width_mm=max(rect.width / UNIT, 0.00001),
        height_mm=max(rect.height / UNIT, 0.00001),
    )


class TypographyEngine:
    def __init__(self, fonts: FontRegistry | None = None):
        self.native_libraries = verify_native_libraries()
        self.fonts = fonts or FontRegistry()
        self.fonts.configure()
        self.fontmap = PangoCairo.FontMap.new()
        self.fontmap.set_resolution(72)
        self._cache = {}

    def _prepare(
        self,
        layer: TextLayer,
        bounds: BoundsMM | None = None,
        direction: Literal["auto", "ltr", "rtl"] = "auto",
    ):
        if direction not in {"auto", "ltr", "rtl"}:
            raise ValueError("M1 supports auto, ltr, and rtl writing directions")
        bounds = bounds or layer.bounds
        style = self.fonts.styles[layer.style_name]
        font = self.fonts.fonts[style.font_id]
        key = hashlib.sha256(
            (
                layer.model_dump_json()
                + bounds.model_dump_json()
                + direction
                + style.model_dump_json()
                + font.model_dump_json()
            ).encode()
        ).hexdigest()
        if key in self._cache:
            return self._cache[key]
        context = self.fontmap.create_context()
        context.set_round_glyph_positions(False)
        PangoCairo.context_set_resolution(context, 72)
        options = cairo.FontOptions()
        options.set_hint_metrics(cairo.HINT_METRICS_OFF)
        options.set_hint_style(cairo.HINT_STYLE_NONE)
        PangoCairo.context_set_font_options(context, options)
        context.set_language(Pango.Language.from_string("en"))
        if direction != "auto":
            context.set_base_dir(Pango.Direction.RTL if direction == "rtl" else Pango.Direction.LTR)
        native = Pango.Layout.new(context)
        native.set_auto_dir(direction == "auto")
        desc = Pango.FontDescription()
        fallbacks = [f.family for f in self.fonts.config.fonts if f.fallback and f.id != font.id]
        desc.set_family(",".join([font.family, *fallbacks]))
        axes = {**font.axes, **{a.tag: a.value for a in style.font_axes}}
        if axes:
            desc.set_variations(",".join(f"{tag}={value}" for tag, value in sorted(axes.items())))
        desc.set_style(Pango.Style.ITALIC if font.slant == "italic" else Pango.Style.NORMAL)
        desc.set_size(round(style.font_size_pt * Pango.SCALE))
        native.set_font_description(desc)
        native.set_text(layer.text_content, -1)
        native.set_width(round(bounds.width_mm * UNIT))
        native.set_wrap(Pango.WrapMode.WORD)
        native.set_alignment(
            {
                "left": Pango.Alignment.LEFT,
                "center": Pango.Alignment.CENTER,
                "right": Pango.Alignment.RIGHT,
            }[style.alignment]
        )
        native.set_line_spacing(style.line_spacing)
        attributes = Pango.AttrList()
        if style.tracking_pt:
            attributes.insert(Pango.attr_letter_spacing_new(round(style.tracking_pt * Pango.SCALE)))
        if style.baseline_step_mm is not None:
            native.set_line_spacing(0)
            attributes.insert(
                Pango.attr_line_height_new_absolute(round(style.baseline_step_mm * UNIT))
            )
        native.set_attributes(attributes)
        native.set_ellipsize(Pango.EllipsizeMode.NONE)
        ink, logical = native.get_extents()
        byte_chars = {0: 0}
        offset = 0
        for index, char in enumerate(layer.text_content):
            offset += len(char.encode("utf-8"))
            byte_chars[offset] = index + 1
        data = json.loads(native.serialize(Pango.LayoutSerializeFlags.OUTPUT).get_data())["output"]
        lines = []
        it = native.get_iter()
        for row in data["lines"]:
            _, lr = it.get_line_extents()
            lines.append(
                TextLine(
                    start_char=byte_chars[row["start-index"]],
                    end_char=byte_chars[row["start-index"] + row["length"]],
                    baseline_mm=bounds.y_mm + it.get_baseline() / UNIT,
                    logical_bounds=rectangle(lr, bounds),
                    paragraph_start=row["paragraph-start"],
                )
            )
            it.next_line()
        findings = []
        visible = 0
        for line in lines:
            if (
                line.logical_bounds.y_mm + line.logical_bounds.height_mm
                <= bounds.y_mm + bounds.height_mm + 0.001
                and line.logical_bounds.width_mm <= bounds.width_mm + 0.001
            ):
                visible += 1
            else:
                break
        if visible < len(lines) and style.min_paragraph_lines > 1:
            # Keep at least two lines of a paragraph on either side of a split.
            para_start = max((i for i in range(visible) if lines[i].paragraph_start), default=0)
            next_start = next(
                (i for i in range(visible, len(lines)) if lines[i].paragraph_start), len(lines)
            )
            if visible - para_start < style.min_paragraph_lines:
                visible = para_start
            elif next_start - visible == 1 and visible - para_start > style.min_paragraph_lines:
                visible -= 1
            findings.append(
                TypographyFinding(
                    code="UNSATISFIED_WIDOW_ORPHAN",
                    severity="MEDIUM",
                    detail="Paragraph split requires copyfit or reallocation; no font shrinking was applied.",
                )
            )
        consumed = lines[visible].start_char if visible < len(lines) else len(layer.text_content)
        if consumed < len(layer.text_content):
            findings.append(
                TypographyFinding(
                    code="TEXT_OVERFLOW",
                    severity="HIGH",
                    detail=f"Unplaced source characters {consumed}:{len(layer.text_content)}",
                )
            )
        if native.get_unknown_glyphs_count():
            findings.append(
                TypographyFinding(
                    code="UNSUPPORTED_SCRIPT",
                    severity="HIGH",
                    detail=f"{native.get_unknown_glyphs_count()} glyphs are unavailable in the pinned fonts.",
                )
            )
        runs = []
        placements = []
        run_iterator = native.get_iter()
        index = 0
        checksums = {f.sha256: f for f in self.fonts.config.fonts}
        for row in data["lines"]:
            for run_data in row["runs"]:
                while run_iterator.get_run_readonly() is None:
                    if not run_iterator.next_run():
                        raise RuntimeError("Pango run mapping failed")
                _, run_rect = run_iterator.get_run_extents()
                baseline = run_iterator.get_run_baseline()
                native_font = run_data["font"]
                checksum = native_font["checksum"]
                applied = checksums.get(checksum)
                if applied is None:
                    raise RuntimeError(
                        "Pango resolved an unpinned font; refusing approximate font identity"
                    )
                if applied.id != font.id:
                    findings.append(
                        TypographyFinding(
                            code="FONT_FALLBACK",
                            severity="LOW",
                            detail=f"{font.family} → {applied.family} ({applied.sha256})",
                        )
                    )
                clusters = sorted(
                    {g["log-cluster"] for g in run_data["glyphs"]} | {run_data["length"]}
                )
                x = run_rect.x + run_data.get("start-x-offset", 0)
                glyphs = []
                for g in run_data["glyphs"]:
                    cluster = g["log-cluster"]
                    next_cluster = next(c for c in clusters if c > cluster)
                    first = byte_chars[run_data["offset"] + cluster]
                    last = byte_chars[run_data["offset"] + next_cluster]
                    position = PointMM(
                        x_mm=bounds.x_mm + (x + g.get("x-offset", 0)) / UNIT,
                        y_mm=bounds.y_mm + (baseline + g.get("y-offset", 0)) / UNIT,
                    )
                    glyphs.append(
                        GlyphDetail(
                            index=index,
                            glyph_id=g["glyph"] if isinstance(g["glyph"], int) else None,
                            cluster_start=first,
                            cluster_end=last,
                            x_mm=position.x_mm,
                            y_mm=position.y_mm,
                            advance_mm=max(0, g["width"] / UNIT),
                        )
                    )
                    placements.append(
                        ShapedGlyphPlacement(
                            glyph_index=index,
                            cluster_start=first,
                            cluster_end=last,
                            position=position,
                            advance_mm=max(0, g["width"] / UNIT),
                        )
                    )
                    index += 1
                    x += g["width"]
                runs.append(
                    ShapedRun(
                        font_family=applied.family,
                        font_hash=checksum,
                        direction="rtl" if run_data["bidi-level"] % 2 else "ltr",
                        glyphs=glyphs,
                    )
                )
                run_iterator.next_run()
        result = TextLayoutResult(
            text_layer_id=layer.id,
            font_hash=font.sha256,
            ink_bounds=rectangle(ink, bounds),
            logical_bounds=rectangle(logical, bounds),
            writing_direction=data["lines"][0]["direction"] if data["lines"] else "ltr",
            consumed_end_char=consumed,
            overflow_start_char=consumed if consumed < len(layer.text_content) else None,
            line_count=len(lines),
            glyphs=placements,
            findings=findings,
        )
        report = ParagraphLayout(
            result=result,
            lines=lines,
            runs=runs,
            visible_line_count=visible,
            copyfit_actions=["editorial_edit", "adjust_frame", "alternate_style", "repaginate"]
            if consumed < len(layer.text_content)
            else [],
        )
        self._cache[key] = (native, report)
        return native, report

    def layout_paragraph(
        self, layer: TextLayer, bounds: BoundsMM | None = None, direction="auto"
    ) -> ParagraphLayout:
        return self._prepare(layer, bounds, direction)[1].model_copy(deep=True)

    def measure_text(self, layer: TextLayer) -> TextLayoutResult:
        return self.layout_paragraph(layer).result

    def fit_text_region(self, layer: TextLayer, region: BoundsMM) -> ParagraphLayout:
        return self.layout_paragraph(layer, region)

    def get_ink_bounds(self, layer: TextLayer) -> BoundsMM:
        return self.measure_text(layer).ink_bounds

    def get_logical_bounds(self, layer: TextLayer) -> BoundsMM:
        return self.measure_text(layer).logical_bounds

    def detect_overflow(self, layer: TextLayer) -> bool:
        return self.measure_text(layer).overflow_start_char is not None

    def draw(self, cr, layer: TextLayer, bounds: BoundsMM):
        native, _ = self._prepare(layer, bounds)
        cr.move_to(bounds.x_mm * PT_PER_MM, bounds.y_mm * PT_PER_MM)
        style = self.fonts.styles[layer.style_name]
        if style.paint == "fill":
            PangoCairo.show_layout(cr, native)
        else:
            PangoCairo.layout_path(cr, native)
            if style.paint == "fill_stroke":
                cr.fill_preserve()
            cr.set_source_rgb(*(int(style.stroke_color[i : i + 2], 16) / 255 for i in (1, 3, 5)))
            cr.set_line_width(style.stroke_width_pt)
            cr.stroke()
