"""Reference programs → native adaptation → render admission → optional art-direction choice."""

import json
from io import BytesIO

import pymupdf
from PIL import Image, ImageDraw

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.artifacts.inspection import vision_input
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import story_sources, z_order
from editorial_studio.creative.evidence import creative_assets, digest
from editorial_studio.creative.models import CreativeReview, TextRange
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.llm.contracts import TextRequest
from editorial_studio.photos.models import IngestedStory
from editorial_studio.photos.pipeline import png
from editorial_studio.reference_studio.fitting import fit_program
from editorial_studio.reference_studio.inspection import native_views
from editorial_studio.reference_studio.models import (
    AuthoredReference,
    LayoutFinding,
    ProgramCandidate,
    ProgramRejection,
    ReferenceChoice,
    ReferenceComposition,
)
from editorial_studio.reference_studio.page_roles import cover_program
from editorial_studio.reference_studio.programs import capture_program
from editorial_studio.reference_studio.quality import analyze_layout
from editorial_studio.settings import load_settings
from editorial_studio.spatial.skills import rect
from editorial_studio.telemetry.tools import tool_span


def composition_assets(store, result):
    assets = set(result.program_asset_ids)
    for candidate in result.candidates:
        assets.update(creative_assets(store, candidate.spread))
        if candidate.native_views:
            assets.update(candidate.native_views.assets.values())
    assets.update(a for a in (result.proof_book_asset_id, result.contact_sheet_asset_id) if a)
    for asset in assets:
        store.read_blob(result.project_id, asset)
    return sorted(assets)


def reading_backing(proposal, quality, sources, paper):
    """A local palette-matched caption/readability field; no moving or shrinking copy."""
    proposal = proposal.model_copy(deep=True)
    engine = TypographyEngine(FontRegistry(configuration=proposal.typography.freeze()))
    treatments = {t.node_id: t for t in proposal.treatments}
    nodes = {n.id: n for n in proposal.graph.nodes}
    order = z_order(proposal)
    changed = False
    for finding in quality.findings:
        if finding.code != "text_contrast" or finding.severity != "error":
            continue
        key = finding.layers[0]
        t = treatments[key]
        node = nodes[key]
        if t.style_role not in ("deck", "body") or t.layout != "rect":
            continue
        source = sources[t.style_role].text
        span = t.text_range or TextRange(start_char=0, end_char=len(source))
        r = node.target_region
        layer = m.TextLayer(
            id=key,
            name=key,
            semantic_role=t.style_role,
            z_index=0,
            bounds=m.BoundsMM(
                x_mm=r.x * 420, y_mm=r.y * 297, width_mm=r.width * 420, height_mm=r.height * 297
            ),
            text_content=source[span.start_char : span.end_char],
            style_name=t.style_name,
        )
        box = engine.measure_text(layer).ink_bounds
        x, y = max(0, box.x_mm - 1), max(0, box.y_mm - 1)
        w, h = min(420 - x, box.width_mm + 2), min(297 - y, box.height_mm + 2)
        backing = "legibility-" + key
        proposal.graph.nodes.append(
            m.ConceptNode(
                id=backing,
                role="vector",
                z_order_hint=0,
                target_region=m.NormalizedRegion(
                    x=x / 420, y=y / 297, width=w / 420, height=h / 297
                ),
            )
        )
        proposal.treatments.append(
            type(t)(node_id=backing, path=rect(x, y, w, h), fill_color=paper)
        )
        order.insert(order.index(key), backing)
        changed = True
    for node in proposal.graph.nodes:
        node.z_order_hint = order.index(node.id)
    return proposal if changed else None


def build_compositions(
    gateway,
    context,
    story_id,
    identity_id,
    reference_ids,
    *,
    origin="m10a-references",
    art_director=False,
    page_role="spread",
):
    store, project = gateway.store, context.project_id
    if (
        not reference_ids
        or len(reference_ids) > 12
        or len(set(reference_ids)) != len(reference_ids)
    ):
        raise ValueError("Choose one to twelve distinct authored references")
    old = store.get("reference_composition", context.run_id, ReferenceComposition)
    if old:
        if (
            old.reference_project != origin
            or old.art_director_requested != art_director
            or old.page_role != page_role
        ):
            raise ValueError("Composition run is bound to different selection settings")
        if (old.project_id, old.story_id, old.identity_id, old.reference_ids) != (
            project,
            story_id,
            identity_id,
            reference_ids,
        ):
            raise ValueError("Composition run is bound to different inputs")
        composition_assets(store, old)
        return old
    story = store.get("story", story_id, IngestedStory)
    identity = store.get("identity", identity_id, ProvisionalIdentity)
    if (
        story is None
        or identity is None
        or story.project_id != project
        or identity.project_id != project
    ):
        raise PermissionError("Composition inputs outside project")
    programs = []
    for key in reference_ids:
        ref = store.get("authored_reference", key, AuthoredReference)
        if ref is None or ref.project_id != origin:
            raise PermissionError("Reference outside selected source project")
        programs.append(capture_program(store, ref))
    if page_role not in ("spread", "cover"):
        raise ValueError("Unknown composition page role")
    rejections = []
    if page_role == "cover":
        cover_programs = []
        for program in programs:
            try:
                cover_programs.append(cover_program(program))
            except ValueError as error:
                rejections.append(ProgramRejection(program_id=program.id, reason=str(error)))
        programs = cover_programs
    with tool_span(store, context, "freeze_reference_composition_programs") as tool:
        program_assets = [store.json_blob(project, p).id for p in programs]
        tool.output_asset_ids.extend(program_assets)
    fingerprint = digest(
        {
            "programs": [p.model_dump(mode="json") for p in programs],
            "story": story.model_dump(mode="json"),
            "identity": identity.model_dump(mode="json"),
        }
    )
    candidates = []
    sources = dict(story_sources(store, project, story))
    for index, program in enumerate(programs):
        try:
            proposal, ratio = fit_program(
                store, project, story, program, minimum_body_pt=identity.tokens.minimum_body_pt
            )
            effective = identity.model_copy(deep=True)
            effective.bible.conceptual_identity = (
                program.name + "; retain its captured image/type relationships."
            )
            effective.bible.signature_behaviors = [
                "Preserve the captured composition's scale, layering, palette and reading geography."
            ]
            effective.bible.photographic_character = [
                "Use the already selected photograph and matched alpha; preserve source pixels."
            ]
            effective.guidelines.palette_roles["paper"] = program.characteristics.background_color
            for token in effective.bible.palette:
                if token.name == "paper":
                    token.hex_color = program.characteristics.background_color
            child = context.model_copy(
                update={
                    "run_id": context.run_id + f"-p{index}",
                    "agent_name": "ReferenceProgramComposer",
                }
            )
            spread = build_creative_spread(
                gateway,
                child,
                story_id,
                identity_id,
                proposal=proposal,
                identity_snapshot=effective,
                with_visual_critics=False,
                reference_program_id=program.id,
            )
            document = CanvasDocument.model_validate_json(
                store.read_blob(project, spread.document_asset_id)
            )
            quality = analyze_layout(store, project, document, proposal)
            errors = [f for f in quality.findings if f.severity == "error"]
            if errors and all(f.code == "text_contrast" for f in errors):
                repaired = reading_backing(
                    proposal, quality, sources, program.characteristics.background_color
                )
                if repaired:
                    proposal = repaired
                    spread = build_creative_spread(
                        gateway,
                        child.model_copy(update={"run_id": child.run_id + "-contrast"}),
                        story_id,
                        identity_id,
                        proposal=proposal,
                        identity_snapshot=effective,
                        with_visual_critics=False,
                        reference_program_id=program.id,
                    )
                    document = CanvasDocument.model_validate_json(
                        store.read_blob(project, spread.document_asset_id)
                    )
                    quality = analyze_layout(store, project, document, proposal)
            baseline = program.characteristics.source_metrics
            by_id = {node.id: node for node in proposal.graph.nodes}
            for group in program.photo_fill_groups:
                if len({by_id[key].target_region.model_dump_json() for key in group}) > 1:
                    quality.findings.append(
                        LayoutFinding(
                            code="separate_photo_windows",
                            severity="review",
                            layers=group,
                            detail="Source resolution prevents a shared photographic plane; inspect whether recognizable landmarks repeat.",
                        )
                    )
            retained = quality.display_ink_fraction / max(0.0001, baseline["display_ink_fraction"])
            if retained < 0.60:
                quality.findings.append(
                    LayoutFinding(
                        code="display_mass_lost",
                        layers=[],
                        detail=f"Only {retained:.1%} of the reference's display ink area remains",
                    )
                )
            if (
                baseline["display_photo_overlap_fraction"] > 0.02
                and quality.display_photo_overlap_fraction
                < baseline["display_photo_overlap_fraction"] * 0.6
            ):
                quality.findings.append(
                    LayoutFinding(
                        code="image_type_integration_lost",
                        layers=[],
                        detail="Actual display/photo overlap fell below 60% of the reference relationship",
                    )
                )
            if (
                quality.background_fraction > baseline["background_fraction"] + 0.10
                and retained < 0.85
            ):
                quality.findings.append(
                    LayoutFinding(
                        code="unexplained_empty_field",
                        layers=[],
                        detail="Background grew while the reference's display mass was lost",
                    )
                )
            quality.passed = not any(f.severity == "error" for f in quality.findings)
            review = store.get("creative_review", spread.review_id, CreativeReview)
            if review.execution.verdict != m.CriticVerdict.ACCEPT:
                raise ValueError("Execution critic rejected the adapted source/typography")
            candidate = ProgramCandidate(
                program_id=program.id,
                family_id=program.family_id,
                reference_id=program.reference_id,
                spread=spread,
                quality=quality,
                minimum_display_ratio=ratio,
            )
            candidates.append(candidate)
            if not quality.passed:
                rejections.append(
                    ProgramRejection(
                        program_id=program.id,
                        reason="; ".join(
                            f.code + ": " + f.detail
                            for f in quality.findings
                            if f.severity == "error"
                        ),
                    )
                )
        except ValueError as error:
            rejections.append(ProgramRejection(program_id=program.id, reason=str(error)))
    admitted = [c for c in candidates if c.quality.passed]
    selected = admitted[0].program_id if admitted else None
    rationale = visual_review = None
    if art_director and admitted:
        shortlist = admitted[:6]
        call = gateway.invoke(
            context.model_copy(update={"agent_name": "ReferenceArtDirector"}),
            TextRequest(
                model=load_settings().text_model,
                reasoning_effort="medium",
                max_output_tokens=2500,
                prompt=f"Page role: {page_role}. For a wrap cover, the RIGHT half is front page 1 and must carry the full headline and principal photograph; the LEFT half is back page 12 with reading copy. Choose the strongest editorial composition for this story from the rendered candidates, considering readable title order, photographic integration and purposeful space. Return its exact program_id and a concrete rationale. Do not return geometry. This is a preference, not owner or professional approval. Story: "
                + json.dumps({k: v.text for k, v in sources.items()})
                + "\nImages in order: "
                + json.dumps(
                    [{"program_id": c.program_id, "family": c.family_id} for c in shortlist]
                ),
                images=[
                    vision_input(store, context, c.spread.png_asset_id, max_edge=1400)
                    for c in shortlist
                ],
            ),
            output_model=ReferenceChoice,
        )
        choice = ReferenceChoice.model_validate_json(call.visible_text)
        if choice.program_id not in {c.program_id for c in shortlist}:
            raise ValueError("Art director selected an unavailable program")
        selected = choice.program_id
        rationale = choice.rationale
    for candidate in admitted:
        document = CanvasDocument.model_validate_json(
            store.read_blob(project, candidate.spread.document_asset_id)
        )
        from editorial_studio.creative.models import CompiledConcept, CriticAssessment

        compiled = store.get("concept", candidate.spread.concept_id, CompiledConcept)
        candidate.native_views = native_views(
            store, project, candidate.spread, document, compiled.proposal
        )
    if art_director and admitted:
        candidate = next(c for c in admitted if c.program_id == selected)
        reference = store.get("authored_reference", candidate.reference_id, AuthoredReference)
        with tool_span(store, context, "freeze_visual_review_reference") as tool:
            reference_asset = store.put_blob(
                project, store.read_blob(origin, reference.spread.png_asset_id), "image/png"
            ).id
            tool.output_asset_ids.append(reference_asset)
        call = gateway.invoke(
            context.model_copy(update={"agent_name": "ReferenceCompositionCritic"}),
            TextRequest(
                model=load_settings().text_model,
                reasoning_effort="medium",
                max_output_tokens=3500,
                prompt="The first image is the target authored reference style. The second is a new adaptation, followed by native display, reading and image/type-junction crops of the adaptation. Review whether the new exact story copy fits that visual language: visible title order, image/type integration, contrast, body readability and preservation of its display scale and deliberate space. Identify concrete visible failures. Do not substitute a generic preference for denser or quieter layouts for the supplied style target; do not equate mere similarity with readability or quality. This is a reference-aware model review, not blind or professional approval. Exact new source: "
                + json.dumps({k: v.text for k, v in sources.items()}),
                images=[
                    vision_input(store, context, a, max_edge=1400)
                    for a in [
                        reference_asset,
                        candidate.spread.png_asset_id,
                        *candidate.native_views.assets.values(),
                    ]
                ],
            ),
            output_model=CriticAssessment,
        )
        visual_review = CriticAssessment.model_validate_json(call.visible_text)
    pdf_asset = sheet_asset = None
    if admitted:
        with tool_span(store, context, "assemble_reference_adaptations") as tool:
            sheet = Image.new("RGB", (1800, 460 * ((len(admitted) + 2) // 3)), "#e6e3dc")
            draw = ImageDraw.Draw(sheet)
            book = pymupdf.open()
            for index, candidate in enumerate(admitted):
                im = Image.open(
                    BytesIO(store.read_blob(project, candidate.spread.png_asset_id))
                ).convert("RGB")
                im.thumbnail((580, 410))
                x, y = index % 3 * 600 + 10, index // 3 * 460 + 32
                sheet.paste(im, (x, y))
                draw.text(
                    (x, y - 22),
                    candidate.family_id
                    + (" / preview" if candidate.program_id == selected else ""),
                    fill="#22211f",
                )
                with pymupdf.open(
                    stream=store.read_blob(project, candidate.spread.pdf_asset_id), filetype="pdf"
                ) as pdf:
                    book.insert_pdf(pdf)
            pdf_asset = store.put_blob(
                project, book.tobytes(garbage=4, deflate=True), "application/pdf"
            ).id
            sheet_asset = store.put_blob(project, png(sheet), "image/png").id
            tool.output_asset_ids.extend([pdf_asset, sheet_asset])
            book.close()
    result = ReferenceComposition(
        id=context.run_id,
        project_id=project,
        story_id=story_id,
        identity_id=identity_id,
        reference_project=origin,
        art_director_requested=art_director,
        page_role=page_role,
        reference_ids=reference_ids,
        program_asset_ids=program_assets,
        input_fingerprint=fingerprint,
        candidates=candidates,
        rejections=rejections,
        selected_program_id=selected,
        state="ready_for_visual_review" if admitted else "no_admissible_candidate",
        proof_book_asset_id=pdf_asset,
        contact_sheet_asset_id=sheet_asset,
        art_direction_rationale=rationale,
        visual_review=visual_review,
        review_mode="reference_aware" if art_director else "not_run",
    )
    composition_assets(store, result)
    store.put_records(("reference_composition", result.id, project, result))
    return result
