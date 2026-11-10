"""Deterministic affine geometry in scene millimetres."""

import math

from editorial_studio.canvas.models import AffineMM
from editorial_studio.contracts import models as m

PT_PER_MM = 72 / 25.4


def compose(left: AffineMM, right: AffineMM) -> AffineMM:
    return AffineMM(
        a=left.a * right.a + left.c * right.b,
        b=left.b * right.a + left.d * right.b,
        c=left.a * right.c + left.c * right.d,
        d=left.b * right.c + left.d * right.d,
        e_mm=left.a * right.e_mm + left.c * right.f_mm + left.e_mm,
        f_mm=left.b * right.e_mm + left.d * right.f_mm + left.f_mm,
    )


def inverse(t: AffineMM) -> AffineMM:
    det = t.a * t.d - t.b * t.c
    return AffineMM(
        a=t.d / det,
        b=-t.b / det,
        c=-t.c / det,
        d=t.a / det,
        e_mm=(t.c * t.f_mm - t.d * t.e_mm) / det,
        f_mm=(t.b * t.e_mm - t.a * t.f_mm) / det,
    )


def point(t: AffineMM, p: m.PointMM) -> m.PointMM:
    return m.PointMM(
        x_mm=t.a * p.x_mm + t.c * p.y_mm + t.e_mm, y_mm=t.b * p.x_mm + t.d * p.y_mm + t.f_mm
    )


def bounds(t: AffineMM, b: m.BoundsMM) -> m.BoundsMM:
    points = [
        point(t, m.PointMM(x_mm=x, y_mm=y))
        for x in [b.x_mm, b.x_mm + b.width_mm]
        for y in [b.y_mm, b.y_mm + b.height_mm]
    ]
    xs, ys = [p.x_mm for p in points], [p.y_mm for p in points]
    return m.BoundsMM(
        x_mm=min(xs), y_mm=min(ys), width_mm=max(xs) - min(xs), height_mm=max(ys) - min(ys)
    )


def operation_transform(op: m.TransformLayerOp, b: m.BoundsMM) -> AffineMM:
    angle = math.radians(op.rotation_deg)
    co, si = math.cos(angle), math.sin(angle)
    linear = AffineMM(a=co * op.scale_x, b=si * op.scale_x, c=-si * op.scale_y, d=co * op.scale_y)
    return compose(
        AffineMM(e_mm=b.x_mm + op.dx_mm, f_mm=b.y_mm + op.dy_mm),
        compose(linear, AffineMM(e_mm=-b.x_mm, f_mm=-b.y_mm)),
    )


def transform_path(path: m.PathGeometry, t: AffineMM) -> m.PathGeometry:
    commands = []
    for cmd in path.commands:
        values = cmd.model_dump()
        for field in ["p", "control", "control1", "control2"]:
            if hasattr(cmd, field):
                values[field] = point(t, getattr(cmd, field)).model_dump()
        commands.append(values)
    return m.PathGeometry(commands=commands, fill_rule=path.fill_rule)


def cairo_path(cr, path: m.PathGeometry):
    """Append M/L/Q/C/Z, converting quadratic segments exactly to cubic segments."""
    current = None
    start = None
    for cmd in path.commands:
        if isinstance(cmd, m.MoveTo):
            current = start = cmd.p
            cr.move_to(cmd.p.x_mm * PT_PER_MM, cmd.p.y_mm * PT_PER_MM)
        elif isinstance(cmd, m.LineTo):
            cr.line_to(cmd.p.x_mm * PT_PER_MM, cmd.p.y_mm * PT_PER_MM)
            current = cmd.p
        elif isinstance(cmd, m.CubicTo):
            cr.curve_to(
                cmd.control1.x_mm * PT_PER_MM,
                cmd.control1.y_mm * PT_PER_MM,
                cmd.control2.x_mm * PT_PER_MM,
                cmd.control2.y_mm * PT_PER_MM,
                cmd.p.x_mm * PT_PER_MM,
                cmd.p.y_mm * PT_PER_MM,
            )
            current = cmd.p
        elif isinstance(cmd, m.QuadraticTo):
            c1 = m.PointMM(
                x_mm=current.x_mm + 2 / 3 * (cmd.control.x_mm - current.x_mm),
                y_mm=current.y_mm + 2 / 3 * (cmd.control.y_mm - current.y_mm),
            )
            c2 = m.PointMM(
                x_mm=cmd.p.x_mm + 2 / 3 * (cmd.control.x_mm - cmd.p.x_mm),
                y_mm=cmd.p.y_mm + 2 / 3 * (cmd.control.y_mm - cmd.p.y_mm),
            )
            cr.curve_to(
                c1.x_mm * PT_PER_MM,
                c1.y_mm * PT_PER_MM,
                c2.x_mm * PT_PER_MM,
                c2.y_mm * PT_PER_MM,
                cmd.p.x_mm * PT_PER_MM,
                cmd.p.y_mm * PT_PER_MM,
            )
            current = cmd.p
        else:
            cr.close_path()
            current = start
