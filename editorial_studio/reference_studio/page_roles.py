"""Adapt reference vocabulary to wrap-cover topology before native copy fitting."""

import hashlib

from editorial_studio.canvas.geometry import transform_path
from editorial_studio.canvas.models import AffineMM


def cover_program(source):
    program = source.model_copy(deep=True)
    proposal = program.proposal
    treatments = {t.node_id: t for t in proposal.treatments}
    slots = {s.node_id: s for s in program.slots}
    if program.photo_fill_groups or any(
        t.layout != "rect" or t.glyph_transforms for t in proposal.treatments
    ):
        raise ValueError("This reference needs a dedicated cover fitter")
    reading = [
        n for n in proposal.graph.nodes if n.id in slots and slots[n.id].role in ("body", "deck")
    ]
    body = [n for n in reading if slots[n.id].role == "body"]
    if len(body) > 2:
        raise ValueError("Cover reading layout supports at most two captured columns")
    for node in proposal.graph.nodes:
        old = node.target_region
        t = treatments[node.id]
        role = slots[node.id].role if node.id in slots else None
        if role == "headline":
            node.target_region = old.model_copy(
                update={"x": 0.5 + old.x / 2, "width": old.width / 2}
            )
        elif role == "body":
            index = body.index(node)
            node.target_region = old.model_copy(
                update={"x": (22 + 90 * index) / 420, "width": 88 / 420}
            )
        elif role == "deck":
            node.target_region = old.model_copy(
                update={"x": 22 / 420, "width": min(old.width, 178 / 420)}
            )
        elif role in ("photo", "alpha"):
            width = old.width / 2
            height = old.height / 2 if role == "alpha" else old.height
            node.target_region = old.model_copy(
                update={"x": 0.5 + old.x / 2, "width": width, "height": height}
            )
            aspect = slots[node.id].source_aspect_ratio
            if aspect:
                frame_aspect = width * 420 / (height * 297)
                slots[node.id].reference_crop_fraction = min(
                    aspect / frame_aspect, frame_aspect / aspect
                )
            if t.path:
                t.path = transform_path(
                    t.path,
                    AffineMM(
                        a=0.5,
                        d=0.5 if role == "alpha" else 1,
                        e_mm=210,
                        f_mm=old.y * 297 * (0.5 if role == "alpha" else 0),
                    ),
                )
            if t.gradient:
                for point in (t.gradient.start, t.gradient.end):
                    point.x_mm = 210 + point.x_mm / 2
                    if role == "alpha":
                        point.y_mm = old.y * 297 + (point.y_mm - old.y * 297) / 2
        elif node.role == "vector":
            intersects_body = any(
                old.y < b.target_region.y + b.target_region.height
                and old.y + old.height > b.target_region.y
                for b in body
            )
            x, width = (0, 0.5) if intersects_body else (0.5 + old.x / 2, old.width / 2)
            node.target_region = old.model_copy(update={"x": x, "width": width})
            if t.path:
                scale = width / old.width
                t.path = transform_path(t.path, AffineMM(a=scale, e_mm=(x - scale * old.x) * 420))
    program.name = "Wrap cover · " + source.name
    program.characteristics.mechanisms += ["front_cover_headline", "back_cover_reading"]
    program.characteristics.reading_regions = [
        [
            n.target_region.x * 420,
            n.target_region.y * 297,
            n.target_region.width * 420,
            n.target_region.height * 297,
        ]
        for n in reading
    ]
    metrics = program.characteristics.source_metrics
    metrics["display_ink_fraction"] *= 0.5
    metrics["display_photo_overlap_fraction"] *= 0.5
    metrics["background_fraction"] = 1 - 0.5 * (1 - metrics["background_fraction"])
    program.id = (
        "program-"
        + hashlib.sha256(
            (
                source.id
                + "cover"
                + proposal.model_dump_json()
                + program.characteristics.model_dump_json()
            ).encode()
        ).hexdigest()[:16]
    )
    return program
