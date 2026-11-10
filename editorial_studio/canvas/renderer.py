"""One continuous scene, shared shaped layout, raster preview and vector PDF."""

import hashlib
import math
from io import BytesIO

import cairo
from PIL import Image, ImageOps

from editorial_studio.canvas.geometry import PT_PER_MM, cairo_path
from editorial_studio.canvas.models import CanvasDocument, RenderMetadata, RenderOutput
from editorial_studio.canvas.typography.engine import Pango, TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import RuntimePolicy, Validator, closed
from editorial_studio.core.storage import Store


class LayoutRejected(ValueError):
    pass


def color(cr, value):
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError("M1 colors must be #RRGGBB")
    cr.set_source_rgb(*(int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)))


def transform(cr, t):
    cr.transform(cairo.Matrix(t.a, t.b, t.c, t.d, t.e_mm * PT_PER_MM, t.f_mm * PT_PER_MM))


class Renderer:
    # This is a capability declaration, not a second operation dispatch table.
    # Parameter schemas and dispatch names continue to come from REGISTRY.
    supported_operations = frozenset(
        {
            "add_image",
            "add_text",
            "transform_layer",
            "clip_to_path",
            "set_z_index",
            "apply_mask",
            "add_path",
            "edit_path",
            "set_blend_mode",
            "create_group",
            "set_clip_stack",
            "bind_asset",
            "set_opacity",
            "boolean_path",
            "text_on_path",
            "flow_text_into_shape",
            "set_glyph_transforms",
            "gradient_mask",
            "color_adjust",
            "apply_filter",
            "displacement_map",
        }
    )

    def __init__(self, store: Store, project_id: str, typography: TypographyEngine | None = None):
        self.store, self.project_id = store, project_id
        self.typography = typography or TypographyEngine()
        from editorial_studio.canvas.typography.advanced import AdvancedTypography

        self.advanced = AdvancedTypography(self.typography)
        self._images = {}
        self._effects = {}

    def _effect_image(self, asset_id, presentation):
        if not (
            presentation.filters or presentation.color_adjustments or presentation.displacements
        ):
            return self._image(asset_id)
        key = asset_id + presentation.model_dump_json()
        if key not in self._effects:
            from editorial_studio.canvas.effects import process

            image = process(
                self._image(asset_id)[0], presentation, lambda value: self._image(value)[0]
            )
            png = BytesIO()
            image.save(png, format="PNG")
            self._effects[key] = (
                image,
                cairo.ImageSurface.create_from_png(BytesIO(png.getvalue())),
            )
        return self._effects[key]

    def _image(self, asset_id):
        if asset_id not in self._images:
            ref = self.store.asset(self.project_id, asset_id)
            if not ref.media_type.startswith("image/"):
                raise ValueError("Image or mask asset must be a decoded raster image")
            with Image.open(BytesIO(self.store.read_blob(self.project_id, asset_id))) as original:
                image = ImageOps.exif_transpose(original).convert("RGBA")
            png = BytesIO()
            image.save(png, format="PNG")
            self._images[asset_id] = (
                image,
                cairo.ImageSurface.create_from_png(BytesIO(png.getvalue())),
            )
        return self._images[asset_id]

    def _coverage(self, asset_id, invert=False):
        image, _ = self._image(asset_id)
        alpha = image.getchannel("A")
        if alpha.getextrema() == (255, 255):
            alpha = image.convert("L")
        if invert:
            alpha = ImageOps.invert(alpha)
        return alpha

    def _mask_pattern(self, asset_id, b, invert=False):
        alpha = self._coverage(asset_id, invert)
        image = alpha
        stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_A8, image.width)
        data = bytearray(stride * image.height)
        raw = alpha.tobytes()
        for row in range(image.height):
            data[row * stride : row * stride + image.width] = raw[
                row * image.width : (row + 1) * image.width
            ]
        surface = cairo.ImageSurface.create_for_data(
            data, cairo.FORMAT_A8, image.width, image.height, stride
        )
        pattern = cairo.SurfacePattern(surface)
        sx, sy = image.width / (b.width_mm * PT_PER_MM), image.height / (b.height_mm * PT_PER_MM)
        pattern.set_matrix(
            cairo.Matrix(xx=sx, yy=sy, x0=-b.x_mm * PT_PER_MM * sx, y0=-b.y_mm * PT_PER_MM * sy)
        )
        return pattern

    def _validate(self, doc):
        scene = doc.scene
        ids = {layer.id for layer in scene.layers}
        policy = RuntimePolicy(
            readable_layer_ids=ids,
            writable_layer_ids=ids,
            allowed_operations=set(),
            renderer_operations=set(),
        )
        Validator(scene, policy).validate_groups()
        by_id = {layer.id: layer for layer in scene.layers}
        parents = {
            member: layer.id
            for layer in scene.layers
            if isinstance(layer, m.GroupLayer)
            for member in layer.member_layer_ids
        }
        for presentation in doc.presentations:
            for path in presentation.clips:
                closed(path)
            for layer_id in presentation.clip_layer_ids:
                if not isinstance(by_id[layer_id], m.VectorLayer):
                    raise ValueError("Clip layer is not a vector")
                if layer_id == presentation.layer_id:
                    raise ValueError("Layer cannot clip itself")
                if parents.get(layer_id) != parents.get(presentation.layer_id):
                    raise ValueError("M1 clip references must share a parent group")
                closed(by_id[layer_id].path)
            if presentation.mask_asset_id:
                self._image(presentation.mask_asset_id)
            for displacement in presentation.displacements:
                self._image(displacement.map_asset_id)
        reports = []
        provenance = {
            record.id: record
            for record in self.store.list("derived_text", m.DerivedText, self.project_id)
        }
        for layer in scene.layers:
            if isinstance(layer, m.ImageLayer):
                self._image(layer.asset_id)
            elif isinstance(layer, m.MaskLayer):
                self._image(layer.mask_asset_id)
            elif isinstance(layer, m.TextLayer):
                record = (
                    self.store.get("derived_text", layer.derived_text_id, m.DerivedText)
                    if layer.derived_text_id
                    else None
                )
                if doc.enforce_text_provenance or record is not None:
                    if (
                        layer.derived_text_id not in provenance
                        or provenance[layer.derived_text_id].text != layer.text_content
                    ):
                        raise ValueError(
                            "text differs from its project-scoped source derivation; create a provenance-aware editorial revision"
                        )
                p = next(p for p in doc.presentations if p.layer_id == layer.id)
                if p.path_text or p.shape_flow or p.outline_text or p.glyph_transforms:
                    reports.append(self.advanced.layout(layer, p)[0])
                else:
                    reports.append(self.typography.layout_paragraph(layer, p.source_bounds))
        return reports

    def _draw(self, cr, doc):
        layers = {layer.id: layer for layer in doc.scene.layers}
        states = {p.layer_id: p for p in doc.presentations}
        children = {
            member
            for layer in doc.scene.layers
            if isinstance(layer, m.GroupLayer)
            for member in layer.member_layer_ids
        }
        operators = {
            m.BlendMode.NORMAL: cairo.OPERATOR_OVER,
            m.BlendMode.MULTIPLY: cairo.OPERATOR_MULTIPLY,
            m.BlendMode.SCREEN: cairo.OPERATOR_SCREEN,
            m.BlendMode.OVERLAY: cairo.OPERATOR_OVERLAY,
            m.BlendMode.DARKEN: cairo.OPERATOR_DARKEN,
            m.BlendMode.LIGHTEN: cairo.OPERATOR_LIGHTEN,
        }
        color(cr, doc.background_color)
        cr.paint()

        def draw(layer):
            if not layer.visible:
                return
            p = states[layer.id]
            b = p.source_bounds
            cr.save()
            # Referenced clips are scene geometry in the shared parent coordinate space.
            for clip_id in p.clip_layer_ids:
                clip_layer = layers[clip_id]
                cr.new_path()
                cr.save()
                transform(cr, states[clip_id].transform)
                cairo_path(cr, clip_layer.path)
                cr.restore()
                cr.set_fill_rule(
                    cairo.FILL_RULE_EVEN_ODD
                    if clip_layer.path.fill_rule == "evenodd"
                    else cairo.FILL_RULE_WINDING
                )
                cr.clip()
            transform(cr, p.transform)
            for path in p.clips:
                cr.new_path()
                cairo_path(cr, path)
                cr.set_fill_rule(
                    cairo.FILL_RULE_EVEN_ODD
                    if path.fill_rule == "evenodd"
                    else cairo.FILL_RULE_WINDING
                )
                cr.clip()
            cr.push_group()
            cr.save()
            if isinstance(layer, m.GroupLayer):
                for child in sorted(
                    (layers[i] for i in layer.member_layer_ids), key=lambda child: child.z_index
                ):
                    draw(child)
            elif isinstance(layer, m.TextLayer):
                color(cr, self.typography.fonts.styles[layer.style_name].color)
                if p.path_text or p.shape_flow or p.outline_text or p.glyph_transforms:
                    _, glyphs = self.advanced.layout(layer, p)
                    for glyph in glyphs:
                        if glyph.path:
                            cr.new_path()
                            cairo_path(cr, glyph.path)
                            cr.set_fill_rule(cairo.FILL_RULE_WINDING)
                            style = self.typography.fonts.styles[layer.style_name]
                            if style.paint == "fill":
                                cr.fill()
                            else:
                                if style.paint == "fill_stroke":
                                    cr.fill_preserve()
                                color(cr, style.stroke_color)
                                cr.set_line_width(style.stroke_width_pt)
                                cr.stroke()
                else:
                    self.typography.draw(cr, layer, b)
            elif isinstance(layer, m.VectorLayer):
                cr.new_path()
                cairo_path(cr, layer.path)
                cr.set_fill_rule(
                    cairo.FILL_RULE_EVEN_ODD
                    if layer.path.fill_rule == "evenodd"
                    else cairo.FILL_RULE_WINDING
                )
                if layer.fill_color:
                    color(cr, layer.fill_color)
                    cr.fill_preserve()
                if layer.stroke_color and p.stroke_width_mm:
                    color(cr, layer.stroke_color)
                    cr.set_line_width(p.stroke_width_mm * PT_PER_MM)
                    cr.stroke()
                else:
                    cr.new_path()
            else:
                asset_id = (
                    layer.asset_id if isinstance(layer, m.ImageLayer) else layer.mask_asset_id
                )
                _, surface = self._effect_image(asset_id, p)
                if isinstance(layer, m.MaskLayer):
                    matte = self._coverage(asset_id, layer.invert)
                    buffer = BytesIO()
                    matte.save(buffer, format="PNG")
                    surface = cairo.ImageSurface.create_from_png(BytesIO(buffer.getvalue()))
                cr.rectangle(
                    b.x_mm * PT_PER_MM,
                    b.y_mm * PT_PER_MM,
                    b.width_mm * PT_PER_MM,
                    b.height_mm * PT_PER_MM,
                )
                cr.clip()
                scale = max(
                    b.width_mm * PT_PER_MM / surface.get_width(),
                    b.height_mm * PT_PER_MM / surface.get_height(),
                )
                cr.translate(
                    (b.x_mm + b.width_mm / 2) * PT_PER_MM, (b.y_mm + b.height_mm / 2) * PT_PER_MM
                )
                cr.scale(scale, scale)
                cr.translate(-surface.get_width() / 2, -surface.get_height() / 2)
                cr.set_source_surface(surface, 0, 0)
                cr.paint()
            # push_group does not isolate the Cairo transform/clip stack.
            cr.restore()
            cr.pop_group_to_source()
            if p.mask_asset_id:
                cr.push_group()
                cr.mask(self._mask_pattern(p.mask_asset_id, b, p.invert_mask))
                cr.pop_group_to_source()
            if p.gradient:
                g = p.gradient
                if g.gradient_type == "linear":
                    pattern = cairo.LinearGradient(
                        g.start.x_mm * PT_PER_MM,
                        g.start.y_mm * PT_PER_MM,
                        g.end.x_mm * PT_PER_MM,
                        g.end.y_mm * PT_PER_MM,
                    )
                else:
                    radius = (
                        math.hypot(g.end.x_mm - g.start.x_mm, g.end.y_mm - g.start.y_mm) * PT_PER_MM
                    )
                    pattern = cairo.RadialGradient(
                        g.start.x_mm * PT_PER_MM,
                        g.start.y_mm * PT_PER_MM,
                        0,
                        g.start.x_mm * PT_PER_MM,
                        g.start.y_mm * PT_PER_MM,
                        radius,
                    )
                for stop in g.stops:
                    pattern.add_color_stop_rgba(stop.offset, 1, 1, 1, stop.opacity)
                pattern.set_extend(cairo.EXTEND_PAD)
                cr.push_group()
                cr.mask(pattern)
                cr.pop_group_to_source()
            cr.set_operator(operators[layer.blend_mode])
            cr.paint_with_alpha(layer.opacity)
            cr.restore()

        for layer in sorted(
            (layer for layer in doc.scene.layers if layer.id not in children),
            key=lambda layer: layer.z_index,
        ):
            draw(layer)

    def render(
        self, document: CanvasDocument, *, dpi: float = 144, strict: bool = True
    ) -> RenderOutput:
        if document.typography is not None:
            typography = TypographyEngine(FontRegistry(configuration=document.typography))
            renderer = Renderer(self.store, self.project_id, typography)
            return renderer._render(document, dpi=dpi, strict=strict)
        return self._render(document, dpi=dpi, strict=strict)

    def _render(
        self, document: CanvasDocument, *, dpi: float = 144, strict: bool = True
    ) -> RenderOutput:
        doc = CanvasDocument.model_validate(document.model_dump())
        if not math.isfinite(dpi) or dpi <= 0 or dpi > 1200:
            raise ValueError("invalid render DPI")
        layouts = self._validate(doc)
        failures = [
            f
            for layout in layouts
            for f in layout.result.findings
            if f.severity in {m.Severity.HIGH, m.Severity.CRITICAL}
        ]
        if strict and failures:
            raise LayoutRejected("; ".join(f.detail for f in failures))
        width, height = doc.scene.width_mm * PT_PER_MM, doc.scene.height_mm * PT_PER_MM
        png_surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, math.ceil(width * dpi / 72), math.ceil(height * dpi / 72)
        )
        cr = cairo.Context(png_surface)
        cr.scale(dpi / 72, dpi / 72)
        self._draw(cr, doc)
        png = BytesIO()
        png_surface.write_to_png(png)
        pdf = BytesIO()
        surface = cairo.PDFSurface(pdf, width, height)
        surface.set_metadata(cairo.PDF_METADATA_CREATOR, "Autonomous Editorial Studio M1")
        surface.set_metadata(cairo.PDF_METADATA_CREATE_DATE, doc.scene.created_at.isoformat())
        surface.set_metadata(cairo.PDF_METADATA_MOD_DATE, doc.scene.created_at.isoformat())
        self._draw(cairo.Context(surface), doc)
        surface.finish()
        hashes = sorted({run.font_hash for layout in layouts for run in layout.runs})
        return RenderOutput(
            png=png.getvalue(),
            pdf=pdf.getvalue(),
            metadata=RenderMetadata(
                document_hash=hashlib.sha256(doc.model_dump_json().encode()).hexdigest(),
                cairo_version=cairo.cairo_version_string(),
                pango_version=Pango.version_string(),
                font_hashes=hashes,
                native_library_hashes={
                    spec.filename: spec.sha256 for spec in self.typography.native_libraries
                },
                dpi=dpi,
                canvas_width_mm=doc.scene.width_mm,
                canvas_height_mm=doc.scene.height_mm,
                text_layouts=layouts,
                glyph_outlines=[
                    glyph
                    for layer in doc.scene.layers
                    if isinstance(layer, m.TextLayer)
                    for p in doc.presentations
                    if p.layer_id == layer.id
                    and (p.path_text or p.shape_flow or p.outline_text or p.glyph_transforms)
                    for glyph in self.advanced.layout(layer, p)[1]
                ],
            ),
        )
