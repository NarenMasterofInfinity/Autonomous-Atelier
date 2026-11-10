"""Capture editable authored composition, replacing all original story inputs with slots."""

import hashlib
import json
from io import BytesIO

import numpy as np
from PIL import Image

from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.creative.compiler import node_bounds, source_partitions, z_order
from editorial_studio.creative.models import CompiledConcept
from editorial_studio.photos.models import IngestedStory, PhotoAssessment
from editorial_studio.reference_studio.catalog import proof_assets
from editorial_studio.reference_studio.models import (
    CompositionProgram,
    CompositionSlot,
    LayoutCharacteristics,
)
from editorial_studio.segmentation.models import SegmentationResult


def face_visibility(face, aspect, frame_aspect):
    width, height = min(1, frame_aspect / aspect), min(1, aspect / frame_aspect)
    left, top = (1 - width) / 2, (1 - height) / 2
    intersection = max(0, min(face.x + face.width, left + width) - max(face.x, left)) * max(
        0, min(face.y + face.height, top + height) - max(face.y, top)
    )
    return intersection / (face.width * face.height)


def capture_program(store, reference):
    proof_assets(store, reference)
    if reference.status == "needs_rework":
        raise ValueError("Reference is marked for rework")
    project = reference.project_id
    concept = store.get("concept", reference.spread.concept_id, CompiledConcept)
    if concept.authorship != "authored":
        raise ValueError("Composition programs require explicit authored reference evidence")
    story = store.get("story", reference.story_id, IngestedStory)
    placements = source_partitions(store, project, story, concept.proposal)
    metadata = RenderMetadata.model_validate_json(
        store.read_blob(project, reference.spread.metadata_asset_id)
    )
    line_counts = {
        layout.result.text_layer_id: layout.result.line_count for layout in metadata.text_layouts
    }
    ink_boxes = {
        layout.result.text_layer_id: layout.result.ink_bounds for layout in metadata.text_layouts
    }
    proposal = concept.proposal.model_copy(deep=True)
    slots = []
    treatments = {t.node_id: t for t in proposal.treatments}
    styles = {s.name: s for s in concept.typography.styles}
    rendered_styles = {
        op.layer_id: op.style_name for op in concept.recipe.operations if op.op == "add_text"
    }
    sizes, fonts, paints, rotations, reading, mechanisms = [], [], [], [], [], []
    photo_area = 0
    for node in proposal.graph.nodes:
        t = treatments[node.id]
        if node.role == "text":
            t.style_name = t.style_name or rendered_styles[node.id]
            role, derived, start, end = placements[node.id]
            b = node_bounds(node, t)
            ink = ink_boxes[node.id]
            style = styles[t.style_name]
            half = style.stroke_width_pt * 25.4 / 144 if style.paint != "fill" else 0
            # Different glyphs have different optical overshoots. Keep a small
            # em-relative allowance, while measuring actual ink rather than advances.
            tolerance = 0.15 + style.font_size_pt * 0.02 * 25.4 / 72
            overhang = (
                max(0, b.x_mm - ink.x_mm + half) + tolerance,
                max(0, b.y_mm - ink.y_mm + half) + tolerance,
                max(0, ink.x_mm + ink.width_mm + half - b.x_mm - b.width_mm) + tolerance,
                max(0, ink.y_mm + ink.height_mm + half - b.y_mm - b.height_mm) + tolerance,
            )
            node.derived_text_id = "input-" + role
            slots.append(
                CompositionSlot(
                    node_id=node.id,
                    role=role,
                    source_order=start,
                    source_fraction=(end - start) / len(derived.text),
                    display_line_count=line_counts[node.id] if role == "headline" else None,
                    display_ink_overhang_mm=overhang if role == "headline" else None,
                )
            )
            t.text_range = None
            style = styles[t.style_name]
            if role == "headline":
                sizes.append(style.font_size_pt)
                fonts.append(style.font_id)
                paints.append(style.paint)
                rotations.append(t.rotation_deg)
            else:
                r = node.target_region
                reading.append([r.x * 420, r.y * 297, r.width * 420, r.height * 297])
            if t.layout != "rect":
                mechanisms.append(t.layout)
        elif node.role in ("image", "subject", "texture"):
            im = Image.open(BytesIO(store.read_blob(project, node.source_asset_id)))
            alpha = im.mode == "RGBA" and im.getchannel("A").getextrema() != (255, 255)
            role = "alpha" if alpha else "photo"
            aspect = im.width / im.height
            frame_aspect = node.target_region.width * 420 / (node.target_region.height * 297)
            source_photos = [
                store.get("photo", p, PhotoAssessment) for p in story.photo_assessment_ids
            ]
            root_asset = next(
                (
                    seg.source_asset_id
                    for seg in store.list("segmentation", SegmentationResult, project)
                    if seg.cutout_asset_id == node.source_asset_id
                ),
                node.source_asset_id,
            )
            photo_index = next(
                (i for i, p in enumerate(source_photos) if p.source_asset_id == root_asset), 0
            )
            photo = next(
                (p for p in source_photos if p.source_asset_id == node.source_asset_id), None
            )
            face_floor = 0.9 if node.target_region.width * node.target_region.height >= 0.2 else 0
            if photo and photo.faces:
                face_floor = max(
                    0,
                    min(face_visibility(face, aspect, frame_aspect) for face in photo.faces) - 0.05,
                )
            slots.append(
                CompositionSlot(
                    node_id=node.id,
                    role=role,
                    source_aspect_ratio=aspect,
                    reference_crop_fraction=min(aspect / frame_aspect, frame_aspect / aspect),
                    minimum_face_visibility=face_floor,
                    photo_index=photo_index,
                )
            )
            node.source_asset_id = "input-" + role
            r = node.target_region
            photo_area += r.width * r.height
            if alpha:
                mechanisms.append("foreground_alpha")
            if t.gradient:
                mechanisms.append("gradient_transition")
        elif node.source_asset_id:
            raise ValueError("Unresolved external source in composition program")
    mechanisms += [r.relation for r in proposal.graph.relationships]
    photo_fills = {}
    for rel in proposal.graph.relationships:
        if rel.relation == "clips_to" and treatments[rel.target_id].style_role == "headline":
            slot = next(
                (s for s in slots if s.node_id == rel.source_id and s.role == "photo"), None
            )
            if slot:
                photo_fills.setdefault(slot.photo_index, []).append(slot.node_id)
    groups = [keys for keys in photo_fills.values() if len(keys) > 1]
    if groups:
        mechanisms.append("continuous_photo_fill_when_native")
    if any(p != "fill" for p in paints):
        mechanisms.append("outlined_type")
    if any(rotations):
        mechanisms.append("directional_type")
    # Capture resolved, actually rendered typography, not the pre-fit proposal sizes.
    from editorial_studio.creative.models import ConceptTypography

    proposal.typography = ConceptTypography.from_configuration(concept.typography)
    proposal.artifact_requirements = []
    characteristics = LayoutCharacteristics(
        background_color=concept.background_color,
        display_sizes_pt=sizes,
        display_fonts=fonts,
        paint_modes=paints,
        rotations_deg=rotations,
        photographic_area_fraction=min(1, photo_area),
        mechanisms=sorted(set(mechanisms)),
        layer_order=z_order(proposal),
        reading_regions=reading,
    )
    from editorial_studio.reference_studio.quality import Probe

    document = CanvasDocument.model_validate_json(
        store.read_blob(project, reference.spread.document_asset_id)
    )
    probe = Probe(store, project, document)
    headline_ids = {s.node_id for s in slots if s.role == "headline"}
    photo_ids = {s.node_id for s in slots if s.role in ("photo", "alpha")}
    ink = (
        probe.plate(only=headline_ids, paint=dict.fromkeys(headline_ids, "#ffffff")).max(axis=2)
        / 255
    )
    photos = (
        probe.plate(only=photo_ids, paint=dict.fromkeys(photo_ids, "#ffffff")).max(axis=2) / 255
    )
    actual = np.asarray(
        Image.open(BytesIO(store.read_blob(project, reference.spread.png_asset_id))).convert("RGB"),
        dtype=np.int16,
    )
    paper = np.array([int(concept.background_color[i : i + 2], 16) for i in (1, 3, 5)])
    characteristics.source_metrics = {
        "display_ink_fraction": float(ink.mean()),
        "display_photo_overlap_fraction": float(np.minimum(ink, photos).sum() / max(1, ink.sum())),
        "background_fraction": float((np.abs(actual - paper).max(axis=2) < 10).mean()),
    }
    key = hashlib.sha256(
        (
            project
            + reference.id
            + proposal.model_dump_json()
            + characteristics.model_dump_json()
            + "".join(s.model_dump_json() for s in slots)
            + json.dumps(groups)
            + "reference-program-v1:.72:1.08"
        ).encode()
    ).hexdigest()[:16]
    return CompositionProgram(
        id="program-" + key,
        reference_id=reference.id,
        source_project=project,
        family_id=reference.family_id,
        name=reference.title,
        proposal=proposal,
        slots=slots,
        photo_fill_groups=groups,
        characteristics=characteristics,
    )
