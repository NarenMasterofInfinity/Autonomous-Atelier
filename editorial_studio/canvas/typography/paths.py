"""Adaptive curve flattening, arc-length lookup and closed-region Boolean geometry."""

import bisect
import math

import yaml
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import closed
from editorial_studio.settings import ROOT


def settings():
    return yaml.safe_load((ROOT / "config/advanced_typography.yaml").read_text())


def point(p):
    return (p.x_mm, p.y_mm)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def midpoint(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def flatten(path: m.PathGeometry, tolerance=None) -> list[list[tuple[float, float]]]:
    cfg = settings()
    tol = tolerance or cfg["curve_flatness_mm"]
    subpaths = []
    points = []
    start = None

    def curve(controls, depth=0, budget=None):
        budget = tol if budget is None else budget
        chord = distance(controls[0], controls[-1])
        polygon = sum(distance(a, b) for a, b in zip(controls, controls[1:], strict=False))
        # Split the arc-length error budget between children; flatness remains geometric.
        if (
            polygon - chord <= budget
            and max(
                (
                    abs(
                        (controls[-1][0] - controls[0][0]) * (p[1] - controls[0][1])
                        - (controls[-1][1] - controls[0][1]) * (p[0] - controls[0][0])
                    )
                    / max(chord, 1e-12)
                    for p in controls[1:-1]
                ),
                default=0,
            )
            <= tol
        ):
            points.append(controls[-1])
            return
        if depth >= cfg["curve_max_depth"]:
            raise ValueError("curve subdivision tolerance could not be met")
        rows = [controls]
        while len(rows[-1]) > 1:
            rows.append([midpoint(a, b) for a, b in zip(rows[-1], rows[-1][1:], strict=False)])
        curve([r[0] for r in rows], depth + 1, budget / 2)
        curve([r[-1] for r in reversed(rows)], depth + 1, budget / 2)

    current = None
    for cmd in path.commands:
        if isinstance(cmd, m.MoveTo):
            if points:
                subpaths.append(points)
            current = start = point(cmd.p)
            points = [current]
        elif isinstance(cmd, m.LineTo):
            current = point(cmd.p)
            points.append(current)
        elif isinstance(cmd, m.QuadraticTo):
            curve([current, point(cmd.control), point(cmd.p)])
            current = point(cmd.p)
        elif isinstance(cmd, m.CubicTo):
            curve([current, point(cmd.control1), point(cmd.control2), point(cmd.p)])
            current = point(cmd.p)
        else:
            if points[-1] != start:
                points.append(start)
            current = start
    if points:
        subpaths.append(points)
    return subpaths


class ArcLengthPath:
    def __init__(self, path):
        parts = flatten(path)
        if len(parts) != 1:
            raise ValueError("path lettering requires one continuous subpath")
        self.points = parts[0]
        self.lengths = [0.0]
        for a, b in zip(self.points, self.points[1:], strict=False):
            self.lengths.append(self.lengths[-1] + distance(a, b))
        self.length = self.lengths[-1]
        if self.length < 1e-6:
            raise ValueError("path has zero length")

    def at(self, s):
        s = max(0.0, min(s, self.length))
        i = min(len(self.points) - 2, max(0, bisect.bisect_right(self.lengths, s) - 1))
        while i < len(self.points) - 2 and self.lengths[i + 1] == self.lengths[i]:
            i += 1
        a, b = self.points[i : i + 2]
        span = self.lengths[i + 1] - self.lengths[i]
        t = (s - self.lengths[i]) / max(span, 1e-12)
        return (
            a[0] + t * (b[0] - a[0]),
            a[1] + t * (b[1] - a[1]),
            math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])),
        )


def region(path):
    closed(path)
    parts = flatten(path)
    rings = []
    for points in parts:
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area <= 1e-8:
            raise ValueError("invalid or empty text region")
        signed = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:], strict=False))
        rings.append((polygon, signed))
    result = GeometryCollection()
    if path.fill_rule == "evenodd":
        for polygon, _ in rings:
            result = result.symmetric_difference(polygon)
    else:
        # Build nested contours by winding number rather than discarding holes.
        cells = []
        from shapely.ops import polygonize, unary_union

        for cell in polygonize(unary_union([p.boundary for p, _ in rings])):
            probe = cell.representative_point()
            winding = sum(1 if sign > 0 else -1 for p, sign in rings if p.covers(probe))
            if winding:
                cells.append(cell)
        from shapely.ops import unary_union

        result = unary_union(cells)
    if result.is_empty or not result.is_valid:
        raise ValueError("empty or invalid compound region")
    return result


def geometry_path(shape):
    if shape.is_empty:
        raise ValueError("Boolean result is empty")
    polygons = (
        [shape]
        if isinstance(shape, Polygon)
        else list(shape.geoms)
        if isinstance(shape, MultiPolygon)
        else []
    )
    if not polygons:
        raise ValueError("Boolean result is not an area")
    commands = []
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            coords = list(ring.coords)
            commands.append(m.MoveTo(p=m.PointMM(x_mm=coords[0][0], y_mm=coords[0][1])))
            commands.extend(m.LineTo(p=m.PointMM(x_mm=x, y_mm=y)) for x, y in coords[1:-1])
            commands.append(m.ClosePath())
    return m.PathGeometry(commands=commands, fill_rule="evenodd")
