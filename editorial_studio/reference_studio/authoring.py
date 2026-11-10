"""Explicit authored compositions using the production compiler's exact source partitions."""

import json
import re

import yaml

from editorial_studio.canvas.typography.fonts import FontConfiguration, TypeStyle
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import story_sources
from editorial_studio.creative.models import (
    ConceptProposal,
    ConceptTypography,
    NodeTreatment,
    TextRange,
)
from editorial_studio.settings import ROOT
from editorial_studio.spatial.skills import rect

PAPER = "#eeeae2"
INK = "#202b35"
ORANGE = "#e34f22"


def fonts():
    rows = yaml.safe_load((ROOT / "config/fonts.yaml").read_text())["fonts"]
    rows += yaml.safe_load((ROOT / "config/flagship.yaml").read_text())["fonts"]
    rows += json.loads((ROOT / "config/m10a_fonts.json").read_text())["fonts"]
    return rows


class Author:
    def __init__(self, store, project, story, photo, cutout=None, *, paper=PAPER):
        self.sources = dict(story_sources(store, project, story))
        self.photo = photo
        self.cutout = cutout
        self.nodes = []
        self.treatments = []
        self.styles = []
        self.relationships = []
        self.paper = paper
        self.cursors = {role: 0 for role in self.sources}

    def region(self, b):
        x, y, w, h = b
        return m.NormalizedRegion(x=x / 420, y=y / 297, width=w / 420, height=h / 297)

    def style(self, key, font, size, color=INK, **kwargs):
        style = TypeStyle(
            name=key, font_id=font, font_size_pt=size, color=color, min_paragraph_lines=1, **kwargs
        )
        self.styles.append(style)
        return key

    def text(
        self,
        key,
        role,
        b,
        *,
        size=80,
        font="Anton",
        color=INK,
        text=None,
        z=5,
        rotation=0,
        layout="rect",
        path=None,
        exclusions=None,
        **kwargs,
    ):
        source = self.sources[role].text
        start = self.cursors[role]
        text = source[start:] if text is None else text
        if source[start : start + len(text)] != text:
            raise ValueError(f"{key}: authored fragment differs from source")
        self.cursors[role] += len(text)
        name = self.style(key + ".style", font, size, color, **kwargs)
        self.nodes.append(
            m.ConceptNode(
                id=key,
                role="text",
                derived_text_id=self.sources[role].id,
                target_region=self.region(b),
                z_order_hint=z,
            )
        )
        self.treatments.append(
            NodeTreatment(
                node_id=key,
                style_role=role,
                style_name=name,
                text_range=TextRange(start_char=start, end_char=start + len(text)),
                rotation_deg=rotation,
                layout=layout,
                path=path,
                exclusions=exclusions or [],
            )
        )

    def title_words(self, frames, *, font="Anton", color=INK):
        words = [r.group() for r in re.finditer(r"\S+\s*", self.sources["headline"].text)]
        if len(words) != len(frames):
            raise ValueError("word/frame count differs")
        for i, (word, frame) in enumerate(zip(words, frames, strict=True)):
            b, size, *extra = frame
            kw = extra[0] if extra else {}
            self.text(
                f"title-{i}", "headline", b, text=word, size=size, font=font, color=color, **kw
            )

    def body(self, frames, *, color=INK, size=11, font="Newsreader", **kwargs):
        text = self.sources["body"].text
        if len(frames) == 1:
            parts = [text]
        elif len(frames) == 2:
            at = text.index("\n\n") + 2
            parts = [text[:at], text[at:]]
        else:
            raise ValueError("author explicit reading partitions")
        for i, (b, part) in enumerate(zip(frames, parts, strict=True)):
            self.text(
                f"body-{i}", "body", b, text=part, size=size, font=font, color=color, **kwargs
            )

    def deck(self, b, *, color=INK, size=12, font="DejaVuSans", **kwargs):
        b = [b[0], b[1], min(b[2], 178), b[3]]
        self.text("deck", "deck", b, size=size, color=color, font=font, **kwargs)

    def image(self, key, b, *, asset=None, subject=False, z=0, gradient=None, path=None):
        self.nodes.append(
            m.ConceptNode(
                id=key,
                role="subject" if subject else "image",
                source_asset_id=asset or self.photo,
                target_region=self.region(b),
                z_order_hint=z,
            )
        )
        self.treatments.append(NodeTreatment(node_id=key, gradient=gradient, path=path))

    def vector(self, key, b, color, *, z=1):
        self.nodes.append(
            m.ConceptNode(id=key, role="vector", target_region=self.region(b), z_order_hint=z)
        )
        self.treatments.append(NodeTreatment(node_id=key, path=rect(*b), fill_color=color))

    def fade(self, key, x0, x1, *, vertical=False):
        return m.GradientMaskOp(
            target_layer_id=key,
            gradient_type="linear",
            start=m.PointMM(x_mm=0 if vertical else x0, y_mm=x0 if vertical else 0),
            end=m.PointMM(x_mm=0 if vertical else x1, y_mm=x1 if vertical else 0),
            stops=[m.GradientStop(offset=0, opacity=1), m.GradientStop(offset=1, opacity=0)],
        )

    def finish(self, brief, caps):
        for role, s in self.sources.items():
            if self.cursors[role] != len(s.text):
                raise ValueError("unplaced source " + role)
        return ConceptProposal(
            visual_metaphor=brief,
            compositional_structure=brief,
            photography_treatment="Actual source photographs; authored crop, color and registered geometry.",
            narrative_expression=brief,
            graph=m.SpatialConceptGraph(nodes=self.nodes, relationships=self.relationships),
            treatments=self.treatments,
            typography=ConceptTypography.from_configuration(
                FontConfiguration(fonts=fonts(), styles=self.styles)
            ),
            required_capabilities=caps,
            spatial_intent=m.SpatialIntent(mode="guided"),
            inspection_crop=m.BoundsMM(x_mm=220, y_mm=190, width_mm=195, height_mm=100),
        )


STUDIES = [
    ("01-depth-portrait", "foreground-depth", "portrait"),
    ("02-photo-overlay", "photo-overlay", "launch"),
    ("03-monumental", "monumental-type", "portrait"),
    ("04-serif-earthrise", "editorial-serif", "moon"),
    ("05-outline-globe", "outline-hybrid", "cover"),
    ("06-terrain-lettering", "image-lettering", "mars"),
    ("07-contour-globe", "contour-flow", "cover"),
    ("08-lunar-collage", "editorial-collage", "moon"),
    ("09-reversed-light", "reversed-field", "closing"),
    ("10-directional", "directional-type", "portrait"),
    ("11-serif-portrait", "editorial-serif", "portrait"),
    ("12-overlay-earthrise", "photo-overlay", "moon"),
]


def compose(key, a):
    if key == "01-depth-portrait":
        b = [0, 24, 216, 273]
        a.image("atmosphere", b, gradient=a.fade("atmosphere", 130, 216))
        a.image("person", b, asset=a.cutout, subject=True, z=4)
        a.title_words(
            [
                ([214, 7, 80, 16], 24),
                ([118, 12, 292, 119], 230),
                ([211, 94, 200, 100], 200),
                ([252, 181, 36, 22], 28),
                ([292, 181, 116, 22], 28),
            ],
            color=INK,
        )
        for t in a.treatments:
            if t.node_id in ("title-1", "title-2"):
                a.nodes[
                    next(i for i, n in enumerate(a.nodes) if n.id == t.node_id)
                ].z_order_hint = 2
        a.deck([250, 204, 155, 25], size=10)
        a.body([[250, 232, 74, 63], [333, 232, 74, 63]], size=11)
    elif key == "02-photo-overlay":
        a.paper = "#152e3e"
        a.image("launch", [116, 0, 304, 243], gradient=a.fade("launch", 160, 243, vertical=True))
        a.title_words(
            [([18, 12, 345, 70], 122), ([20, 88, 100, 40], 42), ([18, 130, 390, 84], 145)],
            color=PAPER,
        )
        a.deck([22, 219, 158, 22], color="#fa9c64", size=11)
        a.body([[22, 249, 176, 45], [222, 249, 176, 45]], color=PAPER, size=11)
    elif key == "03-monumental":
        a.paper = ORANGE
        a.title_words(
            [
                ([18, 5, 70, 18], 24),
                ([12, 21, 396, 125], 245),
                ([12, 112, 340, 102], 215),
                ([345, 148, 53, 23], 34),
                ([215, 238, 190, 45], 80),
            ],
            color=INK,
        )
        a.image("portrait-fragment", [16, 210, 179, 87], z=3)
        a.deck([216, 14, 190, 18], size=10)
        a.vector("reading-paper", [200, 195, 220, 102], PAPER, z=4)
        # Keep OF/SPACE above the reading field, with body beneath their rhythm.
        next(n for n in a.nodes if n.id == "title-3").target_region = a.region([350, 130, 55, 28])
        next(n for n in a.nodes if n.id == "title-4").target_region = a.region([218, 158, 182, 44])
        a.body([[216, 216, 90, 78], [315, 216, 90, 78]], size=11)
    elif key in ("04-serif-earthrise", "12-overlay-earthrise"):
        dark = key.startswith("12")
        a.paper = "#101418" if dark else PAPER
        a.image(
            "lunar",
            [0, 0, 420, 196],
            gradient=a.fade("lunar", 145, 210, vertical=True) if dark else None,
        )
        color = PAPER if dark else INK
        a.text(
            "title",
            "headline",
            [18, 10 if dark else 137, 390, 83],
            size=104 if dark else 110,
            font="NewsreaderItalic" if dark else "Newsreader",
            color=PAPER,
            tracking_pt=-1.4,
        )
        a.deck([22, 201 if dark else 263, 376, 24], color="#f09665" if dark else INK, size=12)
        a.body(
            [
                [22, 235 if dark else 226, 178, 58 if dark else 36],
                [222, 235 if dark else 226, 178, 58 if dark else 36],
            ],
            color=color,
            size=11,
        )
        if not dark:
            # Deck precedes the aligned reading columns in the designed hierarchy.
            next(n for n in a.nodes if n.id == "deck").target_region = a.region([22, 205, 178, 21])
            for n in a.nodes:
                if n.id.startswith("body"):
                    n.target_region = a.region([22 if n.id == "body-0" else 222, 238, 178, 57])
    elif key == "05-outline-globe":
        a.paper = "#10273a"
        a.image("globe", [150, 0, 270, 270], asset=a.cutout)
        a.title_words(
            [
                (
                    [15, 1, 390, 125],
                    230,
                    {"paint": "stroke", "stroke_color": "#f7e9d4", "stroke_width_pt": 1.5},
                ),
                ([15, 110, 390, 125], 230, {"paint": "fill", "tracking_pt": -3}),
            ],
            color="#f7e9d4",
        )
        a.deck([22, 227, 375, 20], color="#e7a878", size=11)
        a.body([[22, 258, 177, 37], [222, 258, 177, 37]], color=PAPER, size=11)
    elif key == "06-terrain-lettering":
        a.paper = "#e8b66e"
        a.title_words(
            [([20, 3, 85, 34], 48), ([15, 44, 250, 122], 235), ([170, 140, 245, 122], 235)],
            color=INK,
        )
        # The complete source-bound title remains in the editable scene; its
        # actual shaped outlines clip the real photograph into the two words.
        for word in (1, 2):
            node = next(n for n in a.nodes if n.id == f"title-{word}")
            a.treatments[
                next(i for i, t in enumerate(a.treatments) if t.node_id == node.id)
            ].opacity = 0
            a.image(
                f"letter-photo-{word}",
                [
                    node.target_region.x * 420,
                    node.target_region.y * 297,
                    node.target_region.width * 420,
                    min(node.target_region.height * 297, 118),
                ],
                z=6,
            )
            a.relationships.append(
                m.ConceptRelationship(
                    source_id=f"letter-photo-{word}",
                    target_id=node.id,
                    relation="clips_to",
                    rationale="Actual photographic terrain fills the shaped display letterforms.",
                )
            )
        a.deck([126, 8, 272, 26], size=11)
        a.body([[22, 255, 177, 42], [222, 255, 177, 42]], size=11)
    elif key == "07-contour-globe":
        a.image("globe", [120, 97, 190, 190], asset=a.cutout, subject=True, z=2)
        a.title_words([([18, 2, 390, 110], 202), ([236, 91, 175, 92], 156)], color=INK)
        a.deck([22, 106, 115, 38], size=11)
        # Exclusion geometry is generated by the compiler from the alpha,
        # not a hand-drawn stand-in for the globe.
        a.text(
            "flow",
            "body",
            [22, 140, 230, 145],
            size=11,
            font="Newsreader",
            layout="shape",
            path=rect(22, 140, 230, 145),
        )
        a.relationships.append(
            m.ConceptRelationship(
                source_id="flow",
                target_id="globe",
                relation="flows_around",
                rationale="The actual globe contour shapes the reading measure.",
            )
        )
    elif key == "08-lunar-collage":
        a.paper = "#a6b3ac"
        a.image("lunar-wide", [0, 0, 250, 148], path=rect(0, 0, 250, 148))
        a.image("lunar-detail", [265, 58, 155, 166], z=3, path=rect(265, 58, 155, 166))
        a.vector("title-field", [0, 130, 420, 86], INK, z=2)
        a.text(
            "title",
            "headline",
            [20, 137, 380, 76],
            size=104,
            font="NewsreaderItalic",
            color=PAPER,
            z=5,
            tracking_pt=-1.2,
        )
        a.vector("caption-field", [0, 224, 420, 73], PAPER, z=2)
        a.deck([22, 205, 215, 22], size=10)
        a.body([[22, 243, 178, 52], [222, 243, 178, 52]], size=11)
    elif key == "09-reversed-light":
        a.paper = "#0a1118"
        a.image("light", [0, 0, 420, 297], gradient=a.fade("light", 180, 295, vertical=True))
        a.title_words(
            [([22, 8, 68, 30], 48), ([18, 45, 240, 92], 132), ([100, 122, 300, 100], 157)],
            font="NewsreaderItalic",
            color=PAPER,
        )
        a.deck([22, 222, 175, 32], color="#f4b57a", size=11)
        a.body([[22, 264, 178, 33], [222, 264, 178, 33]], color=PAPER, size=11)
    elif key == "10-directional":
        a.title_words(
            [
                ([18, 9, 75, 20], 26),
                ([105, 26, 252, 103], 208, {"rotation": 90}),
                ([114, 5, 294, 100], 189),
                ([119, 106, 45, 22], 31),
                ([169, 106, 231, 50], 85),
            ],
            color=INK,
        )
        a.image("portrait", [125, 133, 207, 164], z=1)
        a.deck([338, 141, 65, 41], size=10)
        a.body([[216, 212, 88, 83], [315, 212, 88, 83]], size=11)
        a.vector("reading-field", [207, 202, 213, 95], PAPER, z=3)
    elif key == "11-serif-portrait":
        a.paper = "#dbe4db"
        a.image("portrait", [0, 0, 195, 297], gradient=a.fade("portrait", 157, 210))
        a.title_words(
            [
                ([204, 10, 86, 28], 32),
                ([171, 23, 243, 95], 140),
                (
                    [170, 99, 246, 105],
                    150,
                    {"font_axes": [{"tag": "wght", "value": 650}, {"tag": "opsz", "value": 72}]},
                ),
                ([220, 188, 36, 25], 26),
                ([260, 180, 151, 55], 58),
            ],
            font="NewsreaderItalic",
            color=INK,
        )
        a.deck([220, 216, 178, 24], size=10)
        a.body([[220, 243, 86, 54], [314, 243, 90, 54]], size=11)
    else:
        raise ValueError(key)
    return a
