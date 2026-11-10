"""Reconcile a typed spatial concept against real assets, source copy and renderer support."""

from io import BytesIO

from PIL import Image, ImageDraw

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.artifacts.models import ArtifactBuild
from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.geometry import transform_path
from editorial_studio.canvas.models import AffineMM, CanvasDocument
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.contracts import models as m
from editorial_studio.contracts.capability_matrix import CAPABILITIES
from editorial_studio.contracts.operation_registry import REGISTRY, Validator
from editorial_studio.core.storage import utcnow
from editorial_studio.creative.models import CompiledConcept, ConceptProposal
from editorial_studio.design_system.models import PairingCatalog
from editorial_studio.design_system.system import DesignSystem
from editorial_studio.photos.models import IngestedStory, PhotoAssessment
from editorial_studio.photos.pipeline import png
from editorial_studio.segmentation.geometry import silhouette_path
from editorial_studio.segmentation.models import SegmentationResult
from editorial_studio.spatial.assistant import SpatialAssistant
from editorial_studio.telemetry.tools import tool_span


def story_sources(store, project, story):
    ledger = ProvenanceLedger(store, project)
    return [
        (role, ledger.get(block).derived_texts[0])
        for role, block in [
            ("headline", story.title_block_id),
            ("deck", story.deck_block_id),
            ("body", story.body_block_id),
        ]
    ]


def photo_sources(store, project, story):
    result = []
    for record_id in story.photo_assessment_ids:
        photo = store.get("photo", record_id, PhotoAssessment)
        if photo is None or photo.project_id != project:
            raise PermissionError("story photo not in project")
        result.append(photo.source_asset_id)
    originals = set(result)
    result.extend(
        row.cutout_asset_id
        for row in store.list("segmentation", SegmentationResult, project)
        if row.source_asset_id in originals and row.quality.passed
    )
    return list(dict.fromkeys(result))


def source_partitions(store, project, story, proposal):
    """Validate an exact partition before creating any excerpt derivations.

    Ranges refer to the full immutable story derivation. Even whitespace must
    belong to one frame; overlaps and silently dropped copy are rejected.
    """
    sources = {d.id: (role, d) for role, d in story_sources(store, project, story)}
    treatments = {t.node_id: t for t in proposal.treatments}
    ranges = {key: [] for key in sources}
    placements = {}
    for node in proposal.graph.nodes:
        treatment = treatments[node.id]
        if node.role != "text":
            if treatment.text_range is not None or treatment.style_name is not None:
                raise ValueError("text controls require a text node")
            continue
        if node.derived_text_id not in sources:
            raise ValueError("concept must place every source derivation exactly once")
        role, derived = sources[node.derived_text_id]
        if treatment.style_role != role:
            raise ValueError("text role does not match source identity")
        start, end = (0, len(derived.text))
        if treatment.text_range:
            start, end = treatment.text_range.start_char, treatment.text_range.end_char
        if end > len(derived.text) or not derived.text[start:end].strip():
            raise ValueError("text range is outside the source or contains only whitespace")
        ranges[derived.id].append((start, end))
        placements[node.id] = (role, derived, start, end)
    for key, spans in ranges.items():
        cursor = 0
        for start, end in sorted(spans):
            if start != cursor:
                raise ValueError("concept must place every source character exactly once")
            cursor = end
        if cursor != len(sources[key][1].text):
            raise ValueError("concept must place every source character exactly once")
    return placements


def excerpt(store, project, derived, start, end):
    if start == 0 and end == len(derived.text):
        return derived
    # Story sources are immutable full verbatim revisions. Reject an indirect
    # edit rather than guessing how its offsets map back to the original.
    if derived.edit_type != m.EditType.VERBATIM or len(derived.derived_from) != 1:
        raise ValueError("source fragments require a full verbatim story derivation")
    span = derived.derived_from[0].model_copy(update={"start_char": start, "end_char": end})
    return ProvenanceLedger(store, project).derive(
        derived.text[start:end], m.EditType.EXCERPT, [span]
    )


def z_order(proposal):
    nodes = {n.id: n for n in proposal.graph.nodes}
    edges = {key: set() for key in nodes}
    indegree = dict.fromkeys(nodes, 0)
    for rel in proposal.graph.relationships:
        if rel.relation not in ("behind", "above"):
            continue
        a, b = (
            (rel.source_id, rel.target_id)
            if rel.relation == "behind"
            else (rel.target_id, rel.source_id)
        )
        if b not in edges[a]:
            edges[a].add(b)
            indegree[b] += 1
    ready = sorted(
        (key for key, n in indegree.items() if n == 0), key=lambda key: nodes[key].z_order_hint
    )
    order = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        for child in sorted(edges[key]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort(key=lambda key: nodes[key].z_order_hint)
    if len(order) != len(nodes):
        raise ValueError("concept depth relationships contain a cycle")
    return order


def node_bounds(node, treatment):
    r = node.target_region
    left, top, right, bottom = r.x * 420, r.y * 297, (r.x + r.width) * 420, (r.y + r.height) * 297
    bleed = treatment.image_bleed_mm if node.role in ("image", "subject", "texture") else 0
    if abs(left) < 0.05:
        left -= bleed
    if abs(top) < 0.05:
        top -= bleed
    if abs(right - 420) < 0.05:
        right += bleed
    if abs(bottom - 297) < 0.05:
        bottom += bleed
    return m.BoundsMM(x_mm=left, y_mm=top, width_mm=right - left, height_mm=bottom - top)


def sketch_graph(store, context, proposal, brief_id):
    image = Image.new("RGB", (840, 594), "#f4f0e8")
    draw = ImageDraw.Draw(image)
    colors = {
        "text": "#98917f",
        "image": "#b3a28a",
        "subject": "#9e4d32",
        "vector": "#b6baa3",
        "texture": "#cbc0b2",
        "mask": "#b0b0b0",
        "group": "#ded9ce",
    }
    for key in z_order(proposal):
        node = next(n for n in proposal.graph.nodes if n.id == key)
        r = node.target_region
        b = (r.x * 840, r.y * 594, (r.x + r.width) * 840, (r.y + r.height) * 594)
        if node.role in ("image", "subject") and node.source_asset_id:
            try:
                from PIL import ImageOps

                source = Image.open(
                    BytesIO(store.read_blob(context.project_id, node.source_asset_id))
                ).convert("RGBA")
                tile = ImageOps.fit(
                    source, (max(1, round(b[2] - b[0])), max(1, round(b[3] - b[1])))
                )
                image.paste(tile, (round(b[0]), round(b[1])), tile)
            except KeyError:
                draw.rectangle(b, fill=colors[node.role])
        else:
            draw.rectangle(b, fill=colors[node.role])
        draw.text((b[0] + 3, b[1] + 3), node.id, fill="#22211f")
    asset = store.put_blob(context.project_id, png(image), "image/png")
    return m.ConceptSketch(
        asset_id=asset.id,
        concept_brief_id=brief_id,
        aspect_ratio=420 / 297,
        source_photo_ids=[
            n.source_asset_id
            for n in proposal.graph.nodes
            if n.role in ("image", "subject") and n.source_asset_id
        ],
    )


def compile_concept(
    store,
    context,
    story: IngestedStory,
    identity: ProvisionalIdentity,
    proposal: ConceptProposal,
    *,
    concept_id: str,
    provider_call_id=None,
    artifacts: list[ArtifactBuild] | None = None,
    reference_program_id: str | None = None,
) -> CompiledConcept:
    if story.project_id != context.project_id or identity.project_id != context.project_id:
        raise PermissionError("concept inputs must belong to this project")
    proposal = ConceptProposal.model_validate(proposal.model_dump())
    prior = store.get("concept", concept_id, CompiledConcept)
    if prior:
        if (
            prior.project_id != context.project_id
            or prior.story_id != story.id
            or prior.identity_id != identity.id
            or prior.proposal != proposal
            or prior.reference_program_id != reference_program_id
        ):
            raise ValueError("concept ID is already bound to different inputs")
        return prior
    if any(build.project_id != context.project_id for build in artifacts or []):
        raise PermissionError("artifact is outside the concept project")

    partitions = source_partitions(store, context.project_id, story, proposal)
    text = {
        node_id: excerpt(store, context.project_id, derived, start, end)
        for node_id, (_, derived, start, end) in partitions.items()
    }
    allowed_photos = set(photo_sources(store, context.project_id, story))
    nodes = {n.id: n for n in proposal.graph.nodes}
    treatments = {t.node_id: t for t in proposal.treatments}
    builds = {b.request.id: b for b in artifacts or []}
    unsupported = []
    operations = []
    elements = []
    bounds = {}
    resolved_paths = {}
    system = DesignSystem(
        tokens=identity.tokens,
        pairing_catalog=PairingCatalog(pairings=[identity.pairing]),
        font_configuration=identity.typography,
    )
    typography = (
        proposal.typography.freeze() if proposal.typography else system.typography(identity.bible)
    )
    if len({s.name for s in typography.styles}) != len(typography.styles) or len(
        {f.id for f in typography.fonts}
    ) != len(typography.fonts):
        raise ValueError("typography requires unique font and style names")
    engine = TypographyEngine(FontRegistry(configuration=typography))
    style_names = {s.name.rsplit(".", 1)[-1]: s.name for s in typography.styles}
    node_styles = {}
    for node_id, (role, _, _, _) in partitions.items():
        treatment = treatments[node_id]
        name = treatment.style_name or style_names.get(role)
        style = next((s for s in typography.styles if s.name == name), None)
        if style is None:
            raise ValueError("text node references an unknown frozen style")
        if role == "body" and style.font_size_pt < identity.tokens.minimum_body_pt:
            raise ValueError("body style is below the identity reading floor")
        node_styles[node_id] = name
    known_caps = {c.id for c in CAPABILITIES}
    for capability in proposal.required_capabilities:
        if capability not in known_caps:
            unsupported.append(
                m.UnsupportedFeature(
                    feature=capability, reason="unknown capability", proposed_fallback=None
                )
            )
    with tool_span(store, context, "compile_visual_concept") as tool:
        for node in proposal.graph.nodes:
            treatment = treatments[node.id]
            b = node_bounds(node, treatment)
            bounds[node.id] = b
            if node.role == "text":
                derived = text[node.id]
                style = node_styles[node.id]
                operations.append(
                    m.AddTextOp(
                        layer_id=node.id,
                        text_content=derived.text,
                        style_name=style,
                        bounds=b,
                        derived_text_id=derived.id,
                    )
                )
                if treatment.layout == "path":
                    operations.append(
                        m.TextOnPathOp(
                            layer_id=node.id,
                            text_content=derived.text,
                            style_name=style,
                            path=treatment.path,
                        )
                    )
                if treatment.layout == "shape":
                    exclusions = list(treatment.exclusions)
                    for rel in proposal.graph.relationships:
                        if rel.source_id == node.id and rel.relation == "flows_around":
                            subject = nodes[rel.target_id]
                            sb = node_bounds(subject, treatments[subject.id])
                            exclusions.append(
                                silhouette_path(
                                    store, context.project_id, subject.source_asset_id, sb
                                )
                            )
                    operations.append(
                        m.FlowTextIntoShapeOp(
                            layer_id=node.id,
                            text_content=derived.text,
                            style_name=style,
                            boundary=treatment.path,
                            exclusion_paths=exclusions,
                        )
                    )
                if treatment.glyph_transforms:
                    operations.append(
                        m.SetGlyphTransformsOp(
                            layer_id=node.id, transforms=treatment.glyph_transforms
                        )
                    )
            elif node.role in ("image", "subject", "texture"):
                if node.source_asset_id not in allowed_photos:
                    raise ValueError("concept image is outside the supplied story assets")
                if node.role == "subject":
                    silhouette_path(store, context.project_id, node.source_asset_id, b)
                source_image = Image.open(
                    BytesIO(store.read_blob(context.project_id, node.source_asset_id))
                )
                source_ppi = (
                    min(source_image.width / b.width_mm, source_image.height / b.height_mm) * 25.4
                )
                if source_ppi < 150 and treatment.image_treatment == "native":
                    raise ValueError(
                        f"Photo {node.id} has {source_ppi:.0f} source PPI: choose a smaller frame or a deliberate grain/halftone treatment"
                    )
                operations.append(
                    m.AddImageOp(layer_id=node.id, asset_id=node.source_asset_id, bounds=b)
                )
                if treatment.image_treatment in ("monochrome", "halftone"):
                    operations.append(
                        m.ColorAdjustOp(layer_id=node.id, saturation=0, contrast=1.15)
                    )
                if treatment.image_treatment == "grain":
                    operations.append(
                        m.ApplyFilterOp(
                            layer_id=node.id, filter=m.GrainFilter(strength=0.2, random_seed=7)
                        )
                    )
                if treatment.image_treatment == "halftone":
                    operations.append(
                        m.ApplyFilterOp(
                            layer_id=node.id, filter=m.HalftoneFilter(dot_spacing_mm=0.7)
                        )
                    )
            elif node.role == "vector":
                if node.source_asset_id in builds:
                    build = builds[node.source_asset_id]
                    if not build.traced:
                        raise ValueError("vector concept slot requires traced vector artifact")
                    path = transform_path(
                        build.traced.path,
                        AffineMM(
                            a=b.width_mm / build.traced.source_width_px,
                            d=b.height_mm / build.traced.source_height_px,
                            e_mm=b.x_mm,
                            f_mm=b.y_mm,
                        ),
                    )
                elif treatment.path:
                    path = treatment.path
                else:
                    unsupported.append(
                        m.UnsupportedFeature(
                            feature=node.id,
                            reason="vector node has no resolved path artifact",
                            proposed_fallback=None,
                        )
                    )
                    continue
                resolved_paths[node.id] = path
                operations.append(
                    m.AddPathOp(
                        layer_id=node.id,
                        path=path,
                        fill_color=treatment.fill_color
                        or identity.guidelines.palette_roles["accent"],
                    )
                )
            else:
                unsupported.append(
                    m.UnsupportedFeature(
                        feature=node.id,
                        reason="group/mask node needs explicit executable membership or mask binding",
                        proposed_fallback=None,
                    )
                )
                continue
            operations.extend(
                [
                    m.SetOpacityOp(layer_id=node.id, opacity=treatment.opacity),
                    m.SetBlendModeOp(layer_id=node.id, blend_mode=treatment.blend_mode),
                ]
            )
            if treatment.rotation_deg:
                operations.append(
                    m.TransformLayerOp(layer_id=node.id, rotation_deg=treatment.rotation_deg)
                )
            if treatment.gradient:
                operations.append(treatment.gradient)
            elements.append(
                m.ExtractedVisualElement(
                    id=concept_id + "-" + node.id,
                    concept_node_id=node.id,
                    mapped_layer_id=node.id,
                    mapped_asset_id=node.source_asset_id,
                    mapping_confidence=1,
                )
            )
        executable = {e.concept_node_id for e in elements}
        for z, node_id in enumerate(z_order(proposal)):
            if node_id in executable:
                operations.append(m.SetZIndexOp(layer_id=node_id, z_index=z))
        for rel in proposal.graph.relationships:
            if rel.source_id not in executable or rel.target_id not in executable:
                continue
            if rel.relation == "clips_to":
                target = nodes[rel.target_id]
                if target.role == "vector" and target.id in resolved_paths:
                    path = resolved_paths[target.id]
                elif target.role == "text":
                    d = text[target.id]
                    path = SpatialAssistant.text_mask(
                        m.TextLayer(
                            id=target.id,
                            name=target.id,
                            semantic_role="mask-source",
                            z_index=0,
                            bounds=bounds[target.id],
                            text_content=d.text,
                            style_name=node_styles[target.id],
                            derived_text_id=d.id,
                        ),
                        engine,
                    )
                else:
                    raise ValueError(
                        "clip relationship target must be resolved vector or text geometry"
                    )
                operations.append(m.ClipToPathOp(target_layer_id=rel.source_id, path=path))
        empty = m.Scene(
            id=concept_id,
            spread_id=concept_id,
            version="initial",
            width_mm=420,
            height_mm=297,
            design_language_id=identity.bible.id,
            created_at=utcnow(),
        )
        document = CanvasDocument.from_scene(empty)
        document.typography = typography
        document.background_color = identity.guidelines.palette_roles["paper"]
        executor = Executor(
            SceneRepository(store, context.project_id), Renderer(store, context.project_id)
        )
        assistant = SpatialAssistant(executor)
        policy = assistant.policy(document)
        validator = Validator(empty, policy)
        for op in operations:
            if op.op not in executor.supported_operations:
                unsupported.append(
                    m.UnsupportedFeature(
                        feature=op.op,
                        reason="renderer operation unavailable",
                        proposed_fallback=None,
                    )
                )
                continue
            getattr(validator, REGISTRY[op.op].handler)(op)
        from editorial_studio.spatial.anchors import anchor_operations

        anchors = anchor_operations(
            validator.layers, proposal.spatial_intent, store, context.project_id
        )
        for op in anchors:
            getattr(validator, REGISTRY[op.op].handler)(op)
        operations.extend(anchors)
        skeleton = empty.model_copy(update={"layers": list(validator.layers.values())})
        brief = m.ConceptBrief(
            id=concept_id,
            project_id=context.project_id,
            spread_id=concept_id,
            visual_metaphor=proposal.visual_metaphor,
            compositional_structure=proposal.compositional_structure,
            photography_treatment=proposal.photography_treatment,
            narrative_expression=proposal.narrative_expression,
        )
        sketch = sketch_graph(store, context, proposal, concept_id)
        hybrid = m.HybridConceptOutput(
            concept_brief=brief,
            spatial_concept_graph=proposal.graph,
            sketch=sketch,
            artifact_requirements=proposal.artifact_requirements,
            required_capabilities=proposal.required_capabilities,
        )
        from editorial_studio.creative.recipes import DynamicRecipeGenerator

        recipe = DynamicRecipeGenerator().from_operations(
            concept_id + "-recipe",
            operations,
            supported_operations=executor.supported_operations,
            capability_ids=proposal.required_capabilities,
            rationale=proposal.narrative_expression,
        )
        result = CompiledConcept(
            id=concept_id,
            project_id=context.project_id,
            story_id=story.id,
            identity_id=identity.id,
            proposal=proposal,
            hybrid=hybrid,
            compiler=m.ConceptCompilerOutput(
                concept_brief_id=concept_id,
                target_scene_skeleton=skeleton,
                extracted_visual_elements=elements,
                unsupported_features=unsupported,
            ),
            recipe=recipe,
            typography=typography,
            background_color=document.background_color,
            provider_call_id=provider_call_id,
            identity_bible=identity.bible,
            tokens=identity.tokens,
            pairing=identity.pairing,
            authorship="reference_adapted"
            if reference_program_id
            else "model"
            if provider_call_id
            else "authored",
            reference_program_id=reference_program_id,
        )
        store.put_records(("concept", concept_id, context.project_id, result))
        tool.output_asset_ids.extend(
            [sketch.asset_id, store.json_blob(context.project_id, result).id]
        )
        return result
