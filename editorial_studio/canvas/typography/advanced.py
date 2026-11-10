"""Cluster-aware path placement and conservative line-band irregular flow."""

import math

from shapely.geometry import LineString, box

from editorial_studio.canvas.geometry import transform_path
from editorial_studio.canvas.models import AffineMM, ParagraphLayout, TextLine
from editorial_studio.canvas.typography.advanced_models import OutlineGlyph
from editorial_studio.canvas.typography.outlines import FontOutlines
from editorial_studio.canvas.typography.paths import ArcLengthPath, region, settings
from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import path_bounds


class AdvancedTypography:
    def __init__(self, engine):
        self.engine = engine
        self.outlines = FontOutlines(engine.fonts)
        self.cache = {}

    def _outline(self, layer, report):
        style = self.engine.fonts.styles[layer.style_name]
        size = style.font_size_pt
        result = []
        for run in report.runs:
            font = next(f for f in self.engine.fonts.config.fonts if f.sha256 == run.font_hash)
            axes = {
                **font.axes,
                **({a.tag: a.value for a in style.font_axes} if font.id == style.font_id else {}),
            }
            for g in run.glyphs:
                if g.glyph_id is None:
                    raise ValueError("shaped glyph has no outline ID")
                result.append(
                    OutlineGlyph(
                        text_layer_id=layer.id,
                        glyph_index=g.index,
                        glyph_id=g.glyph_id,
                        font_hash=run.font_hash,
                        cluster_start=g.cluster_start,
                        cluster_end=g.cluster_end,
                        path=self.outlines.glyph(run.font_hash, g.glyph_id, size, axes),
                        x_mm=g.x_mm,
                        y_mm=g.y_mm,
                        tangent_deg=0,
                    )
                )
        return result

    def layout(self, layer, presentation):
        key = (
            layer.model_dump_json()
            + presentation.model_dump_json()
            + self.engine.fonts.styles[layer.style_name].model_dump_json()
        )
        if key in self.cache:
            return self.cache[key]
        if presentation.shape_flow:
            report, glyphs = self._flow(layer, presentation)
        else:
            probe = (
                layer.model_copy(
                    update={"bounds": m.BoundsMM(x_mm=0, y_mm=0, width_mm=10000, height_mm=1000)}
                )
                if presentation.path_text
                else layer
            )
            report = self.engine.layout_paragraph(
                probe, probe.bounds if presentation.path_text else presentation.source_bounds
            )
            glyphs = self._outline(layer, report)
            if presentation.path_text:
                report, glyphs = self._path(layer, presentation, report, glyphs)
        transformations = {t.glyph_index: t for t in presentation.glyph_transforms}
        if len(transformations) != len(presentation.glyph_transforms) or not set(
            transformations
        ) <= {g.glyph_index for g in glyphs}:
            raise ValueError("glyph transform refers to an unavailable shaped glyph index")
        for g in glyphs:
            t = transformations.get(g.glyph_index)
            angle = g.tangent_deg + (t.rotation_deg if t else 0)
            r = math.radians(angle)
            sx = t.scale_x if t else 1
            sy = t.scale_y if t else 1
            if g.path:
                g.path = transform_path(
                    g.path,
                    AffineMM(
                        a=math.cos(r) * sx,
                        b=math.sin(r) * sx,
                        c=-math.sin(r) * sy,
                        d=math.cos(r) * sy,
                        e_mm=g.x_mm + (t.dx_mm if t else 0),
                        f_mm=g.y_mm + (t.dy_mm if t else 0),
                    ),
                )
            g.x_mm += t.dx_mm if t else 0
            g.y_mm += t.dy_mm if t else 0
            g.tangent_deg = angle
        paths = [path_bounds(g.path) for g in glyphs if g.path]
        if paths:
            x = min(p.x_mm for p in paths)
            y = min(p.y_mm for p in paths)
            report.result.ink_bounds = m.BoundsMM(
                x_mm=x,
                y_mm=y,
                width_mm=max(p.x_mm + p.width_mm for p in paths) - x,
                height_mm=max(p.y_mm + p.height_mm for p in paths) - y,
            )
        mapped = {g.glyph_index: g for g in glyphs}
        report.result.glyphs = [
            m.ShapedGlyphPlacement(
                glyph_index=g.glyph_index,
                cluster_start=g.cluster_start,
                cluster_end=g.cluster_end,
                position=m.PointMM(x_mm=g.x_mm, y_mm=g.y_mm),
                tangent_deg=g.tangent_deg,
                advance_mm=next(
                    (p.advance_mm for p in report.result.glyphs if p.glyph_index == g.glyph_index),
                    0,
                ),
            )
            for g in glyphs
        ]
        for run in report.runs:
            for g in run.glyphs:
                if g.index in mapped:
                    g.x_mm = mapped[g.index].x_mm
                    g.y_mm = mapped[g.index].y_mm
        self.cache[key] = (report, glyphs)
        return report, glyphs

    def _path(self, layer, p, report, glyphs):
        if "\n" in layer.text_content:
            raise ValueError("path lettering requires one paragraph")
        spec = p.path_text
        arc = ArcLengthPath(spec.path)
        baseline = report.lines[0].baseline_mm if report.lines else 0
        left = min((g.x_mm for g in glyphs), default=0)
        consumed = len(layer.text_content)
        placed = []
        findings = list(report.result.findings)
        advances = {g.index: g.advance_mm for r in report.runs for g in r.glyphs}
        failed = {
            g.cluster_start
            for g in glyphs
            if spec.start_offset_mm + g.x_mm - left + advances[g.glyph_index] > arc.length + 1e-6
        }
        if failed:
            consumed = 0 if report.result.writing_direction == "rtl" else min(failed)
        for g in glyphs:
            if g.cluster_end > consumed:
                continue
            s = spec.start_offset_mm + g.x_mm - left
            if spec.side == "right":
                s = arc.length - s
            offset = g.y_mm - baseline
            x, y, angle = arc.at(s)
            if spec.side == "right":
                angle += 180
            radians = math.radians(angle)
            g.x_mm = x - math.sin(radians) * offset
            g.y_mm = y + math.cos(radians) * offset
            g.tangent_deg = angle
            placed.append(g)
        if consumed < len(layer.text_content):
            findings.append(
                m.TypographyFinding(
                    code="PATH_OVERFLOW",
                    severity="HIGH",
                    detail=f"Path too short; source {consumed}:{len(layer.text_content)} is unplaced",
                )
            )
        if any(90 < abs((g.tangent_deg + 180) % 360 - 180) <= 180 for g in placed):
            findings.append(
                m.TypographyFinding(
                    code="UNREADABLE_ORIENTATION",
                    severity="MEDIUM",
                    detail="Path tangent turns lettering upside down; explicit visual review required",
                )
            )
        report.result = report.result.model_copy(
            update={
                "text_layer_id": layer.id,
                "consumed_end_char": consumed,
                "overflow_start_char": consumed if failed else None,
                "logical_bounds": path_bounds(spec.path),
                "findings": findings,
            }
        )
        placed_indices = {g.glyph_index for g in placed}
        report.runs = [
            run.model_copy(update={"glyphs": [g for g in run.glyphs if g.index in placed_indices]})
            for run in report.runs
            if any(g.index in placed_indices for g in run.glyphs)
        ]
        report.lines = (
            [
                TextLine(
                    start_char=0,
                    end_char=consumed,
                    baseline_mm=placed[0].y_mm,
                    logical_bounds=path_bounds(spec.path),
                    paragraph_start=True,
                )
            ]
            if placed
            else []
        )
        report.visible_line_count = len(report.lines)
        report.result.line_count = len(report.lines)
        return report, placed

    def _flow(self, layer, p):
        spec = p.shape_flow
        shape = region(spec.boundary)
        for exclusion in spec.exclusion_paths:
            shape = shape.difference(region(exclusion))
        clearance = settings()["flow_clearance_mm"]
        shape = shape.buffer(-clearance)
        if shape.is_empty:
            raise ValueError("exclusions consume the complete flow region")
        minx, miny, maxx, maxy = shape.bounds
        # Probe the actual pinned font for its line box and baseline offset.
        probe = layer.model_copy(
            update={
                "text_content": "Ag",
                "bounds": m.BoundsMM(x_mm=0, y_mm=0, width_mm=100, height_mm=100),
            }
        )
        metric = self.engine.layout_paragraph(probe)
        line = metric.lines[0]
        lineheight = line.logical_bounds.height_mm
        style = self.engine.fonts.styles[layer.style_name]
        source_direction = self.engine.layout_paragraph(layer).result.writing_direction
        step = max(lineheight, style.baseline_step_mm or lineheight)
        cursor = 0
        y = miny
        glyphs = []
        runs = []
        lines = []
        findings = []
        placements = []
        index = 0

        def intervals_at(yy):
            intersection = shape.intersection(LineString([(minx - 1, yy), (maxx + 1, yy)]))
            segments = (
                [intersection]
                if intersection.geom_type == "LineString"
                else list(intersection.geoms)
                if hasattr(intersection, "geoms")
                else []
            )
            return [
                (s.bounds[0], s.bounds[2])
                for s in segments
                if s.geom_type == "LineString" and s.length > 0
            ]

        count = 0
        while y + lineheight <= maxy + 1e-6 and cursor < len(layer.text_content):
            count += 1
            if count > settings()["maximum_flow_lines"]:
                raise ValueError("flow line limit exceeded")
            # Intersect top, middle, bottom and every polygon vertex crossing the band.
            polygon_parts = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
            critical = [y + 1e-5, y + lineheight / 2, y + lineheight - 1e-5]
            for poly in polygon_parts:
                if poly.geom_type != "Polygon":
                    continue
                for ring in [poly.exterior, *poly.interiors]:
                    critical.extend(vy for _, vy in ring.coords if y < vy < y + lineheight)
            ordered = sorted(set(critical))
            critical.extend((a + b) / 2 for a, b in zip(ordered, ordered[1:], strict=False))
            intervals = intervals_at(critical[0])
            for yy in critical[1:]:
                allowed = intervals_at(yy)
                intervals = [
                    (max(a, c), min(b, d))
                    for a, b in intervals
                    for c, d in allowed
                    if min(b, d) > max(a, c)
                ]
            intervals = [
                (a, b)
                for a, b in intervals
                if b - a >= spec.minimum_line_width_mm
                and shape.covers(box(a + 1e-6, y + 1e-6, b - 1e-6, y + lineheight - 1e-6))
            ]
            for a, b in sorted(intervals, reverse=source_direction == "rtl"):
                remaining = layer.text_content[cursor:]
                temp = layer.model_copy(
                    update={
                        "text_content": remaining,
                        "bounds": m.BoundsMM(x_mm=a, y_mm=y, width_mm=b - a, height_mm=10000),
                    }
                )
                report = self.engine.layout_paragraph(temp)
                if not report.lines:
                    continue
                first = report.lines[0]
                if first.logical_bounds.width_mm > b - a + 0.001:
                    continue
                consumed = report.lines[1].start_char if len(report.lines) > 1 else len(remaining)
                if not consumed:
                    continue
                outline = self._outline(temp, report)
                selected = [g for g in outline if g.cluster_start < consumed]
                mapping = {}
                for g in selected:
                    oldindex = g.glyph_index
                    mapping[oldindex] = index
                    g.glyph_index = index
                    g.cluster_start += cursor
                    g.cluster_end += cursor
                    glyphs.append(g)
                    original = next(v for r in report.runs for v in r.glyphs if v.index == oldindex)
                    placements.append(
                        m.ShapedGlyphPlacement(
                            glyph_index=index,
                            cluster_start=g.cluster_start,
                            cluster_end=g.cluster_end,
                            position=m.PointMM(x_mm=g.x_mm, y_mm=g.y_mm),
                            advance_mm=original.advance_mm,
                        )
                    )
                    index += 1
                for run in report.runs:
                    subset = [
                        g.model_copy(
                            update={
                                "index": mapping[g.index],
                                "cluster_start": g.cluster_start + cursor,
                                "cluster_end": g.cluster_end + cursor,
                            }
                        )
                        for g in run.glyphs
                        if g.index in mapping
                    ]
                    if subset:
                        runs.append(run.model_copy(update={"glyphs": subset}))
                lines.append(
                    TextLine(
                        start_char=cursor,
                        end_char=cursor + consumed,
                        baseline_mm=first.baseline_mm,
                        logical_bounds=first.logical_bounds,
                        paragraph_start=cursor == 0 or layer.text_content[:cursor].endswith("\n"),
                    )
                )
                findings.extend(
                    f
                    for f in report.result.findings
                    if f.code in ("UNSUPPORTED_SCRIPT", "FONT_FALLBACK")
                )
                if len(remaining[:consumed].strip().split()) == 1 and consumed < len(remaining):
                    findings.append(
                        m.TypographyFinding(
                            code="UNSATISFIED_WIDOW_ORPHAN",
                            severity="MEDIUM",
                            detail="A single-word shape-flow line needs editorial inspection",
                        )
                    )
                cursor += consumed
                if cursor >= len(layer.text_content):
                    break
            y += step
        if cursor < len(layer.text_content):
            findings.append(
                m.TypographyFinding(
                    code="TEXT_OVERFLOW",
                    severity="HIGH",
                    detail=f"Irregular region has unused source {cursor}:{len(layer.text_content)}; reallocate copy",
                )
            )
        if not lines:
            findings.append(
                m.TypographyFinding(
                    code="NARROW_LINE_REGION",
                    severity="HIGH",
                    detail="No full-height readable line interval fits the region",
                )
            )
        bounds = path_bounds(spec.boundary)
        result = m.TextLayoutResult(
            text_layer_id=layer.id,
            font_hash=metric.result.font_hash,
            ink_bounds=bounds,
            logical_bounds=bounds,
            writing_direction=source_direction,
            consumed_end_char=cursor,
            overflow_start_char=cursor if cursor < len(layer.text_content) else None,
            line_count=len(lines),
            glyphs=placements,
            findings=findings,
        )
        return ParagraphLayout(
            result=result,
            lines=lines,
            runs=runs,
            visible_line_count=len(lines),
            copyfit_actions=["adjust_frame", "repaginate"]
            if cursor < len(layer.text_content)
            else [],
        ), glyphs
