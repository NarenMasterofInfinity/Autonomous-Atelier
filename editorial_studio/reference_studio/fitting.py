"""Fit exact story text into reference composition without moving its visual structure."""

import re
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageOps, ImageStat

from editorial_studio.canvas.models import LayerPresentation
from editorial_studio.canvas.typography.advanced import AdvancedTypography
from editorial_studio.canvas.typography.advanced_models import ShapeFlowSpec
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import node_bounds, source_partitions, story_sources
from editorial_studio.creative.models import TextRange
from editorial_studio.photos.models import PhotoAssessment
from editorial_studio.reference_studio.programs import face_visibility
from editorial_studio.segmentation.geometry import silhouette_path
from editorial_studio.segmentation.models import SegmentationResult
from editorial_studio.spatial.skills import rect


def continue_cover_edge(proposal, program, store, project):
    """Continue a uniform photographic edge onto the otherwise empty cover field."""
    if "front_cover_headline" not in program.characteristics.mechanisms:
        return
    nodes = {n.id: n for n in proposal.graph.nodes}
    for slot in program.slots:
        node = nodes[slot.node_id]
        r = node.target_region
        if (
            slot.role != "photo"
            or abs(r.x - 0.5) > 0.001
            or abs(r.width - 0.5) > 0.001
            or r.y > 0.001
            or r.height >= 0.98
        ):
            continue
        image = Image.open(BytesIO(store.read_blob(project, node.source_asset_id))).convert("RGB")
        image = ImageOps.fit(image, (512, round(512 * r.height * 297 / (r.width * 420))))
        edge = image.crop((0, image.height - 2, image.width, image.height))
        if any(high - low > 24 for low, high in edge.getextrema()):
            continue
        colour = "#" + "".join(f"{int(v):02x}" for v in ImageStat.Stat(edge).median)
        key = "cover-edge-field-" + node.id
        proposal.graph.nodes.append(
            m.ConceptNode(
                id=key,
                role="vector",
                target_region=m.NormalizedRegion(x=0.5, y=0, width=0.5, height=1),
                z_order_hint=min(n.z_order_hint for n in proposal.graph.nodes) - 1,
            )
        )
        proposal.treatments.append(
            type(proposal.treatments[0])(
                node_id=key, path=rect(210, 0, 210, 297), fill_color=colour
            )
        )


def story_images(store, project, story, index=0):
    # Preserve the existing first selected photo; no ranking or substitute imagery.
    if index >= len(story.photo_assessment_ids):
        raise ValueError("Reference requires more selected story photographs")
    photo = store.get("photo", story.photo_assessment_ids[index], PhotoAssessment)
    if photo is None or photo.project_id != project:
        raise PermissionError("Photo outside story project")
    source = photo.source_asset_id
    image = Image.open(BytesIO(store.read_blob(project, source)))
    alpha = (
        source
        if image.mode == "RGBA" and image.getchannel("A").getextrema() != (255, 255)
        else None
    )
    for row in store.list("segmentation", SegmentationResult, project):
        if row.source_asset_id == source and row.quality.passed:
            alpha = row.cutout_asset_id
            break
    return {"photo": source, "alpha": alpha}


def fit_program(store, project, story, program, *, minimum_body_pt=11):
    proposal = program.proposal.model_copy(deep=True)
    sources = dict(story_sources(store, project, story))
    image_sets = {}
    nodes = {n.id: n for n in proposal.graph.nodes}
    treatments = {t.node_id: t for t in proposal.treatments}
    engine = TypographyEngine(FontRegistry(configuration=proposal.typography.freeze()))
    advanced = AdvancedTypography(engine)
    for slot in program.slots:
        if slot.role in ("photo", "alpha"):
            if slot.photo_index not in image_sets:
                image_sets[slot.photo_index] = story_images(store, project, story, slot.photo_index)
            images = image_sets[slot.photo_index]
            selected_photo = store.get(
                "photo", story.photo_assessment_ids[slot.photo_index], PhotoAssessment
            )
            if images[slot.role] is None:
                raise ValueError(
                    "Program requires a passed alpha for the selected story photograph"
                )
            nodes[slot.node_id].source_asset_id = images[slot.role]
            image = Image.open(BytesIO(store.read_blob(project, images[slot.role])))
            frame = node_bounds(nodes[slot.node_id], treatments[slot.node_id])
            aspect = image.width / image.height
            frame_aspect = frame.width_mm / frame.height_mm
            crop_fraction = min(aspect / frame_aspect, frame_aspect / aspect)
            if slot.role == "photo" and any(
                face_visibility(face, aspect, frame_aspect) < slot.minimum_face_visibility
                for face in selected_photo.faces
            ):
                raise ValueError(
                    "Reference crop would cut off the selected photograph's detected face"
                )
            if slot.reference_crop_fraction and crop_fraction + 0.15 < slot.reference_crop_fraction:
                raise ValueError(
                    "Photo orientation loses substantially more of the image than the reference crop"
                )
        else:
            nodes[slot.node_id].derived_text_id = sources[slot.role].id
    continue_cover_edge(proposal, program, store, project)
    original_styles = dict(engine.fonts.styles)
    # Letter windows share one photographic plane, so recognizable landmarks
    # do not repeat once per word. Narrow texture sources retain native detail.
    for group in program.photo_fill_groups:
        members = [nodes[key] for key in group]
        left = min(n.target_region.x for n in members)
        top = min(n.target_region.y for n in members)
        right = max(n.target_region.x + n.target_region.width for n in members)
        bottom = max(n.target_region.y + n.target_region.height for n in members)
        image = Image.open(BytesIO(store.read_blob(project, members[0].source_asset_id)))
        ppi = (
            min(image.width / ((right - left) * 420), image.height / ((bottom - top) * 297)) * 25.4
        )
        if ppi >= 150:
            for node in members:
                node.target_region = m.NormalizedRegion(
                    x=left, y=top, width=right - left, height=bottom - top
                )
    removed, ratios = set(), []

    def measure(key, text, size):
        t, node = treatments[key], nodes[key]
        style = original_styles[t.style_name].model_copy(
            update={"name": "fit-probe", "font_size_pt": size}
        )
        engine.fonts.styles[style.name] = style
        layer = m.TextLayer(
            id=key,
            name=key,
            semantic_role=t.style_role,
            z_index=0,
            text_content=text,
            style_name=style.name,
            bounds=node_bounds(node, t),
        )
        if t.layout == "shape":
            exclusions = list(t.exclusions)
            for rel in proposal.graph.relationships:
                if rel.source_id == key and rel.relation == "flows_around":
                    subject = nodes[rel.target_id]
                    exclusions.append(
                        silhouette_path(
                            store,
                            project,
                            subject.source_asset_id,
                            node_bounds(subject, treatments[subject.id]),
                        )
                    )
            state = LayerPresentation(
                layer_id=key,
                source_bounds=layer.bounds,
                shape_flow=ShapeFlowSpec(boundary=t.path, exclusion_paths=exclusions),
            )
            return advanced.layout(layer, state)[0].result
        if t.layout != "rect":
            raise ValueError("Program needs a dedicated fitter for its advanced text layout")
        return engine.layout_paragraph(layer).result

    for role in ("headline", "deck", "body"):
        slots = sorted((s for s in program.slots if s.role == role), key=lambda s: s.source_order)
        text = sources[role].text
        matches = list(re.finditer(r"\S+\s*", text))
        if not matches or not slots:
            raise ValueError("Missing source or composition text slots")
        offsets = [0] + [v.end() for v in matches]
        offsets[-1] = len(text)
        count = len(matches)
        biggest = max(original_styles[treatments[s.node_id].style_name].font_size_pt for s in slots)

        @lru_cache(maxsize=None)
        def fit(index, start, end, *, slots=slots, text=text, offsets=offsets, role=role):
            key = slots[index].node_id
            style = original_styles[treatments[key].style_name]
            fragment = text[offsets[start] : offsets[end]]
            minimum = (
                max(minimum_body_pt, style.font_size_pt)
                if role == "body"
                else max(10, 0.9 * style.font_size_pt)
                if role == "deck"
                else max(18, program.minimum_display_ratio * style.font_size_pt)
            )
            if minimum > style.font_size_pt + 0.001:
                return None
            high = style.font_size_pt

            def fits(probe_size):
                result = measure(key, fragment, probe_size)
                if role == "headline" and slots[index].display_ink_overhang_mm:
                    b = node_bounds(nodes[key], treatments[key])
                    ink = result.ink_bounds
                    left, top, right, bottom = slots[index].display_ink_overhang_mm
                    half = style.stroke_width_pt * 25.4 / 144 if style.paint != "fill" else 0
                    if (
                        ink.x_mm - half < b.x_mm - left
                        or ink.y_mm - half < b.y_mm - top
                        or ink.x_mm + ink.width_mm + half > b.x_mm + b.width_mm + right
                        or ink.y_mm + ink.height_mm + half > b.y_mm + b.height_mm + bottom
                    ):
                        return False
                return result.overflow_start_char is None and (
                    role != "headline"
                    or slots[index].display_line_count is None
                    or result.line_count <= slots[index].display_line_count
                )

            if fits(high):
                return high
            if not fits(minimum):
                return None
            for _ in range(12):
                middle = (minimum + high) / 2
                if fits(middle):
                    minimum = middle
                else:
                    high = middle
            return minimum

        @lru_cache(maxsize=None)
        def allocate(
            index,
            start,
            *,
            slots=slots,
            count=count,
            role=role,
            biggest=biggest,
            matches=matches,
            offsets=offsets,
            text=text,
            fit=fit,
        ):
            if index == len(slots):
                return (0, ()) if start == count else None
            slot = slots[index]
            style = original_styles[treatments[slot.node_id].style_name]
            if index == len(slots) - 1:
                ends = {count}
            elif role == "headline":
                ends = set(range(start + 1, count + 1))
            else:
                fraction = slot.source_fraction / sum(s.source_fraction for s in slots[index:])
                ideal = start + round((count - start) * fraction)
                ends = set(range(max(start + 1, ideal - 10), min(count, ideal + 10) + 1))
                ends.update(
                    i + 1
                    for i, match in enumerate(matches)
                    if i >= start and "\n\n" in match.group()
                )
                ends.add(count)
            if (role == "headline" and style.font_size_pt < biggest * 0.35) or start == count:
                ends.add(start)
            best = None
            for end in sorted(ends):
                if end == start:
                    tail = allocate(index + 1, end)
                    if tail:
                        candidate = (tail[0] - 3, ((start, end, None),) + tail[1])
                    else:
                        continue
                else:
                    size = fit(index, start, end)
                    if size is None:
                        continue
                    tail = allocate(index + 1, end)
                    if tail is None:
                        continue
                    fraction = (offsets[end] - offsets[start]) / len(text)
                    balance = abs(fraction - slot.source_fraction)
                    score = (size / style.font_size_pt) * (
                        1 + style.font_size_pt / biggest
                    ) - balance
                    if role == "body" and end < count and "\n\n" in matches[end - 1].group():
                        score += 0.35
                    candidate = (score + tail[0], ((start, end, size),) + tail[1])
                if best is None or candidate[0] > best[0]:
                    best = candidate
            return best

        allocation = allocate(0, 0)
        if allocation is None:
            raise ValueError(
                f"{role} cannot fit this reference while preserving its scale and reading areas"
            )
        for slot, (start, end, size) in zip(slots, allocation[1], strict=True):
            if size is None:
                removed.add(slot.node_id)
                continue
            treatment = treatments[slot.node_id]
            original = original_styles[treatment.style_name]
            name = "adapted." + slot.node_id
            proposal.typography.styles.append(
                original.model_copy(update={"name": name, "font_size_pt": size})
            )
            treatment.style_name = name
            treatment.minimum_display_pt = size if role == "headline" else None
            treatment.text_range = TextRange(start_char=offsets[start], end_char=offsets[end])
            if role == "headline":
                ratios.append(size / original.font_size_pt)
    # If an optional small source word is absent, remove its dependent decoration too.
    for rel in proposal.graph.relationships:
        if rel.relation == "clips_to" and rel.target_id in removed:
            removed.add(rel.source_id)
    proposal.graph.nodes = [n for n in proposal.graph.nodes if n.id not in removed]
    proposal.treatments = [t for t in proposal.treatments if t.node_id not in removed]
    proposal.graph.relationships = [
        r for r in proposal.graph.relationships if not {r.source_id, r.target_id} & removed
    ]
    proposal.visual_metaphor = program.name + ": adapted editorial composition"
    proposal.narrative_expression = "The story's own exact copy and chosen photograph inhabit the captured reference relationships."
    source_partitions(store, project, story, proposal)
    return proposal, min(ratios)
