"""A deterministic M1 acceptance fixture, not the later composition engine."""

from uuid import uuid4

from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import utcnow


def proof_document(scene_id="m1-proof", image_asset_id: str | None = None) -> CanvasDocument:
    layers = []
    if image_asset_id:
        layers.append(
            m.ImageLayer(
                id="architecture",
                name="Architecture photograph",
                semantic_role="lead",
                z_index=0,
                asset_id=image_asset_id,
                bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=235, height_mm=297),
            )
        )

    def text(layer_id, name, content, style, x, y, width, height, z):
        layers.append(
            m.TextLayer(
                id=layer_id,
                name=name,
                semantic_role=style,
                z_index=z,
                text_content=content,
                style_name=style,
                bounds=m.BoundsMM(x_mm=x, y_mm=y, width_mm=width, height_mm=height),
            )
        )

    text("eyebrow", "Section label", "ATELIER / STUDY 01", "caption", 250, 22, 150, 10, 1)
    text("headline", "Headline", "Quiet rooms\nAfternoon light", "headline", 250, 62, 150, 60, 2)
    text(
        "body",
        "Story paragraph",
        "A quiet room holds the afternoon light. The line of a doorway, the grain of plaster, "
        "and the space between objects become a study in attention.\n\n"
        "An ordinary office can offer the same pause: a café cup, a familiar chair, a brief "
        "interval before the day resumes. Restraint gives each detail room to be seen.",
        "body",
        250,
        151,
        137,
        95,
        3,
    )
    text("folio", "Folio", "02   /   A STUDY IN RESTRAINT", "caption", 250, 277, 150, 10, 4)
    layers.append(
        m.VectorLayer(
            id="rule",
            name="Fine rule",
            semantic_role="divider",
            z_index=5,
            bounds=m.BoundsMM(x_mm=250, y_mm=137, width_mm=150, height_mm=0.25),
            stroke_color="#888176",
            path=m.PathGeometry(
                commands=[
                    m.MoveTo(p=m.PointMM(x_mm=250, y_mm=137)),
                    m.LineTo(p=m.PointMM(x_mm=400, y_mm=137)),
                ]
            ),
        )
    )
    scene = m.Scene(
        id=scene_id,
        spread_id="proof-spread",
        version=uuid4().hex,
        width_mm=420,
        height_mm=297,
        design_language_id="m1-technical-proof",
        created_at=utcnow(),
        layers=layers,
    )
    document = CanvasDocument.from_scene(scene)
    document.background_color = "#f4f0e8"
    next(p for p in document.presentations if p.layer_id == "rule").stroke_width_mm = 0.25
    return document
