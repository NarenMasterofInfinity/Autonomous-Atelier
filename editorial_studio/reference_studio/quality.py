"""Counterfactual raster probes measure visible ink, not merely source-object presence.

Black/white recolorings isolate a layer's contribution through actual clipping,
gradients, alpha and foreground occlusion. These are readability safeguards;
they do not score editorial taste or infer professional approval.
"""

import math
import re
from io import BytesIO

import cairo
import numpy as np
from PIL import Image

from editorial_studio.canvas.geometry import PT_PER_MM
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.reference_studio.models import LayoutFinding, LayoutQuality, TextVisibility


class Probe:
    def __init__(self, store, project, document, dpi=72):
        self.doc, self.dpi = document, dpi
        self.renderer = Renderer(
            store, project, TypographyEngine(FontRegistry(configuration=document.typography))
        )
        self.states = {p.layer_id: p for p in document.presentations}

    def plate(self, *, only=None, omit=(), paint=None, word=None, padding_px=0):
        doc = self.doc.model_copy(deep=True)
        if only is not None:
            doc.background_color = "#000000"
        for i, layer in enumerate(doc.scene.layers):
            if layer.id in omit or (only is not None and layer.id not in only):
                layer.visible = False
            if word and layer.id == word[0]:
                state = self.states[layer.id]
                _, glyphs = self.renderer.advanced.layout(layer, state)
                commands = [
                    command
                    for g in glyphs
                    if g.path and word[1] <= g.cluster_start < word[2]
                    for command in g.path.commands
                ]
                if not commands:
                    continue
                style = self.renderer.typography.fonts.styles[layer.style_name]
                replacement = m.VectorLayer(
                    **layer.model_dump(
                        exclude={"layer_type", "text_content", "style_name", "derived_text_id"}
                    ),
                    path=m.PathGeometry(commands=commands),
                    fill_color="#ffffff" if style.paint != "stroke" else None,
                    stroke_color="#ffffff" if style.paint != "fill" else None,
                )
                replacement.opacity = 1
                doc.scene.layers[i] = replacement
                next(p for p in doc.presentations if p.layer_id == layer.id).stroke_width_mm = (
                    style.stroke_width_pt / PT_PER_MM
                )
                layer = replacement
            if paint and layer.id in paint:
                color = paint[layer.id]
                if isinstance(layer, m.TextLayer):
                    old = self.renderer.typography.fonts.styles[layer.style_name]
                    name = "probe." + layer.id
                    self.renderer.typography.fonts.styles[name] = old.model_copy(
                        update={"name": name, "color": color, "stroke_color": color}
                    )
                    layer.style_name = name
                    if only is not None:
                        layer.opacity = 1
                elif isinstance(layer, m.VectorLayer):
                    if layer.fill_color:
                        layer.fill_color = color
                    if layer.stroke_color:
                        layer.stroke_color = color
                elif isinstance(layer, m.ImageLayer):
                    original, _ = self.renderer._image(layer.asset_id)
                    image = Image.new("RGBA", original.size, color)
                    image.putalpha(original.getchannel("A"))
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    key = "probe-" + layer.id + color
                    self.renderer._images[key] = (
                        image,
                        cairo.ImageSurface.create_from_png(BytesIO(buffer.getvalue())),
                    )
                    layer.asset_id = key
        surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32,
            math.ceil(doc.scene.width_mm * self.dpi / 25.4) + 2 * padding_px,
            math.ceil(doc.scene.height_mm * self.dpi / 25.4) + 2 * padding_px,
        )
        cr = cairo.Context(surface)
        cr.scale(self.dpi / 72, self.dpi / 72)
        cr.translate(padding_px * 72 / self.dpi, padding_px * 72 / self.dpi)
        self.renderer._draw(cr, doc)
        surface.flush()
        data = np.ndarray(
            (surface.get_height(), surface.get_width(), 4),
            dtype=np.uint8,
            buffer=surface.get_data(),
            strides=(surface.get_stride(), 4, 1),
        )
        return data[:, :, :3][:, :, ::-1].copy()


def luminance(rgb):
    value = rgb.astype(np.float32) / 255
    linear = np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def analyze_layout(store, project, document, proposal, *, dpi=72):
    probe = Probe(store, project, document, dpi)
    actual = probe.plate()
    roles = {t.node_id: t.style_role for t in proposal.treatments}
    clips = {}
    for r in proposal.graph.relationships:
        if r.relation == "clips_to":
            clips.setdefault(r.target_id, set()).add(r.source_id)
    masks, rows, findings = {}, [], []
    photo_ids = {layer.id for layer in document.scene.layers if isinstance(layer, m.ImageLayer)}
    photos = (
        probe.plate(only=photo_ids, paint=dict.fromkeys(photo_ids, "#ffffff")).max(axis=2) / 255
    )
    for layer in document.scene.layers:
        if not isinstance(layer, m.TextLayer):
            continue
        key, role = layer.id, roles.get(layer.id, layer.semantic_role)
        targets = {key} | clips.get(key, set())
        expected = (
            probe.plate(only={key}, paint={key: "#ffffff"}).max(axis=2).astype(np.float32) / 255
        )
        white = probe.plate(paint=dict.fromkeys(targets, "#ffffff"))
        black = probe.plate(paint=dict.fromkeys(targets, "#000000"))
        visible = np.abs(white.astype(np.float32) - black).max(axis=2) / 255
        area = float(expected.sum())
        ratio = min(1, float(np.minimum(expected, visible).sum()) / max(area, 1))
        background = probe.plate(omit=targets)
        a, b = luminance(actual), luminance(background)
        contrast = (np.maximum(a, b) + 0.05) / (np.minimum(a, b) + 0.05)
        core = (expected > 0.8) & (visible > 0.7)
        contrast_fraction = (
            float((contrast[core] >= (3 if role in ("body", "deck") else 2.2)).mean())
            if core.any()
            else 0
        )
        masks[key] = expected
        rows.append(
            TextVisibility(
                layer_id=key, role=role, visible_fraction=ratio, contrast_fraction=contrast_fraction
            )
        )
        minimum = 0.995 if role in ("body", "deck") else 0.70
        if ratio < minimum:
            findings.append(
                LayoutFinding(
                    code="hidden_text",
                    layers=[key],
                    detail=f"{role}: only {ratio:.1%} of expected ink remains visible",
                )
            )
        if contrast_fraction < (0.9 if role in ("body", "deck") else 0.75):
            findings.append(
                LayoutFinding(
                    code="text_contrast",
                    layers=[key],
                    severity="review" if key in clips else "error",
                    detail=f"{role}: {contrast_fraction:.1%} of visible core ink has adequate local contrast",
                )
            )
        if role == "headline":
            for word in re.finditer(r"\S+", layer.text_content):
                padding = round(48 * dpi / 25.4)
                full_word = (
                    probe.plate(
                        only={key}, word=(key, word.start(), word.end()), padding_px=padding
                    ).max(axis=2)
                    / 255
                )
                word_mask = full_word[
                    padding : padding + visible.shape[0], padding : padding + visible.shape[1]
                ]
                fraction = float(np.minimum(word_mask, visible).sum()) / max(
                    float(full_word.sum()), 1
                )
                if fraction < 0.70:
                    findings.append(
                        LayoutFinding(
                            code="hidden_word",
                            layers=[key],
                            detail=f"Headline word {word.group()!r}: only {fraction:.1%} visible ink",
                        )
                    )
    keys = list(masks)
    for i, key in enumerate(keys):
        for other in keys[i + 1 :]:
            overlap = float(np.minimum(masks[key], masks[other]).sum())
            fraction = overlap / max(1, min(float(masks[key].sum()), float(masks[other].sum())))
            if overlap > 3 and fraction > 0.025:
                findings.append(
                    LayoutFinding(
                        code="text_collision",
                        layers=[key, other],
                        detail=f"Text ink overlaps by {fraction:.1%} of the smaller text object",
                    )
                )
    display = (
        np.maximum.reduce([v for k, v in masks.items() if roles.get(k) == "headline"])
        if any(roles.get(k) == "headline" for k in masks)
        else np.zeros(photos.shape)
    )
    paper = np.array([int(document.background_color[i : i + 2], 16) for i in (1, 3, 5)])
    return LayoutQuality(
        passed=not any(f.severity == "error" for f in findings),
        text=rows,
        findings=findings,
        display_ink_fraction=float(display.mean()),
        display_photo_overlap_fraction=float(
            np.minimum(display, photos).sum() / max(1, display.sum())
        ),
        background_fraction=float(
            (np.abs(actual.astype(np.int16) - paper).max(axis=2) < 10).mean()
        ),
    )
