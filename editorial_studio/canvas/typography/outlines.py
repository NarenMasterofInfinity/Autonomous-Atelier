"""Pinned-font shaped glyph IDs become editable Bézier paths, retaining cluster provenance."""

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from editorial_studio.canvas.geometry import PT_PER_MM
from editorial_studio.contracts import models as m
from editorial_studio.settings import ROOT


class GeometryPen(BasePen):
    def __init__(self, glyphset, scale):
        super().__init__(glyphset)
        self.commands = []
        self.scale = scale

    def p(self, p):
        return m.PointMM(x_mm=p[0] * self.scale, y_mm=-p[1] * self.scale)

    def _moveTo(self, p):
        self.commands.append(m.MoveTo(p=self.p(p)))

    def _lineTo(self, p):
        self.commands.append(m.LineTo(p=self.p(p)))

    def _curveToOne(self, a, b, c):
        self.commands.append(m.CubicTo(control1=self.p(a), control2=self.p(b), p=self.p(c)))

    def _qCurveToOne(self, a, b):
        self.commands.append(m.QuadraticTo(control=self.p(a), p=self.p(b)))

    def _closePath(self):
        self.commands.append(m.ClosePath())

    def _endPath(self):
        raise ValueError("font glyph outline contains an open contour")


class FontOutlines:
    def __init__(self, fonts):
        self.fonts = fonts
        self.cache = {}
        self.loaded = {}

    def glyph(self, font_hash, glyph_id, size_pt, axes=None):
        # PANGO_GLYPH_EMPTY represents zero-width formatting and line-break glyphs.
        if glyph_id == 268435455:
            return None
        key = (font_hash, glyph_id, size_pt, tuple(sorted((axes or {}).items())))
        if key in self.cache:
            return self.cache[key]
        font = next(f for f in self.fonts.config.fonts if f.sha256 == font_hash)
        if font_hash not in self.loaded:
            self.loaded[font_hash] = TTFont(ROOT / font.path)
        tt = self.loaded[font_hash]
        glyphset = tt.getGlyphSet(location=axes if axes is not None else (font.axes or None))
        if glyph_id >= len(tt.getGlyphOrder()):
            raise ValueError("shaped glyph ID outside pinned font")
        pen = GeometryPen(glyphset, size_pt / PT_PER_MM / tt["head"].unitsPerEm)
        glyphset[tt.getGlyphOrder()[glyph_id]].draw(pen)
        path = m.PathGeometry(commands=pen.commands) if pen.commands else None
        self.cache[key] = path
        return path
