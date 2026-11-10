"""Six rendered candidates and a replay-safe, blinded visual knockout bracket."""

import hashlib
import json
import re
from io import BytesIO
from itertools import combinations

import pymupdf
import yaml
from PIL import Image, ImageDraw

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.artifacts.inspection import image_input
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontConfiguration, FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import photo_sources, story_sources
from editorial_studio.creative.identity import structural_distance
from editorial_studio.creative.models import (
    ComparativeAssessment,
    CompiledConcept,
    ConceptProposal,
    ConceptTypography,
    CreativeReview,
)
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.creative.tournament_models import (
    CandidateAttempt,
    CandidateBinding,
    ConceptDirections,
    TournamentBuild,
    TournamentMatch,
    TournamentResult,
)
from editorial_studio.design_system.models import PairingCatalog
from editorial_studio.design_system.system import DesignSystem
from editorial_studio.llm.contracts import CallContext, TextRequest
from editorial_studio.llm.gateway import InvalidModelOutput
from editorial_studio.photos.models import IngestedStory
from editorial_studio.photos.pipeline import png
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.tools import tool_span


def configuration():
    return yaml.safe_load((ROOT / "config/tournament.yaml").read_text())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def provider_materials(materials):
    """Use short exact handles at the model boundary; retain full hashes locally."""
    visible = json.loads(json.dumps(materials))
    bindings = {}
    for row in visible["copy"]:
        key = "text-" + row["role"]
        bindings[key] = row["derived_text_id"]
        row["derived_text_id"] = key
    for index, row in enumerate(visible["photos"]):
        key = f"photo-{index + 1}"
        bindings[key] = row["asset_id"]
        row["asset_id"] = key
    return visible, bindings


def resolve_proposal(proposal, bindings):
    resolved = proposal.model_copy(deep=True)
    for node in resolved.graph.nodes:
        if node.derived_text_id in bindings:
            node.derived_text_id = bindings[node.derived_text_id]
        if node.source_asset_id in bindings:
            node.source_asset_id = bindings[node.source_asset_id]
    return resolved


def material(store, project, story, identity, cfg):
    system = DesignSystem(
        tokens=identity.tokens,
        pairing_catalog=PairingCatalog(pairings=[identity.pairing]),
        font_configuration=identity.typography,
    )
    base = system.typography(identity.bible)
    fonts = list(base.fonts)
    catalog = ROOT / cfg["font_catalog"]
    if catalog.exists():
        extra = yaml.safe_load(catalog.read_text())
        for row in extra["fonts"]:
            if (ROOT / row["path"]).exists():
                from editorial_studio.canvas.typography.fonts import FontSpec

                font = FontSpec.model_validate(row)
                if font.id not in {f.id for f in fonts}:
                    fonts.append(font)
    from editorial_studio.canvas.typography.fonts import TypeStyle

    ink = next(token.hex_color for token in identity.bible.palette if token.name == "ink")
    typography = FontConfiguration(
        fonts=fonts,
        styles=base.styles
        + [
            TypeStyle(
                name="studio.display",
                font_id=identity.pairing.headline_font_id,
                font_size_pt=128,
                line_spacing=1,
                color=ink,
                min_paragraph_lines=1,
            ),
            TypeStyle(
                name="studio.word",
                font_id=identity.pairing.headline_font_id,
                font_size_pt=200,
                line_spacing=1,
                color=ink,
                min_paragraph_lines=1,
            ),
        ],
    )
    engine = TypographyEngine(FontRegistry(configuration=typography))
    copy = []
    for role, derived in story_sources(store, project, story):
        fits = []
        for width in (68, 74, 90, 140, 180):
            layer = m.TextLayer(
                id="measure",
                name="measure",
                semantic_role=role,
                z_index=0,
                text_content=derived.text,
                derived_text_id=derived.id,
                style_name=identity.bible.id + "." + role,
                bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=width, height_mm=10000),
            )
            measured = engine.layout_paragraph(layer)
            fits.append(
                {"width_mm": width, "height_mm": round(measured.result.logical_bounds.height_mm, 2)}
            )
        copy.append(
            {
                "role": role,
                "derived_text_id": derived.id,
                "text": derived.text,
                "characters": len(derived.text),
                "default_style_fits": fits,
            }
        )
        text = derived.text
        copy[-1]["word_ranges"] = (
            [
                {"start_char": match.start(), "end_char": match.end(), "text": match.group()}
                for match in re.finditer(r"\S+\s*", text)
            ]
            if role == "headline"
            else []
        )
        if role == "headline" and cfg.get("preserve_display_scale"):
            measured_words = []
            display_faces = {
                identity.pairing.headline_font_id,
                identity.pairing.body_font_id,
                *(f.id for f in fonts if f.slant == "italic"),
            }
            samples = [
                (f.id, size)
                for f in fonts
                if f.id in display_faces
                for size in (
                    (90, 128, 180, 220) if f.id == identity.pairing.headline_font_id else (90, 180)
                )
            ]
            for word in copy[-1]["word_ranges"]:
                for font_id, size in samples:
                    style = TypeStyle(
                        name=f"word-measure-{font_id}-{size}",
                        font_id=font_id,
                        font_size_pt=size,
                        color=ink,
                        line_spacing=1,
                        min_paragraph_lines=1,
                    )
                    engine.fonts.styles[style.name] = style
                    layer = m.TextLayer(
                        id="word-measure",
                        name="Native display measurement",
                        semantic_role="headline",
                        z_index=0,
                        text_content=word["text"],
                        style_name=style.name,
                        bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=2000, height_mm=2000),
                    )
                    box = engine.layout_paragraph(layer).result.logical_bounds
                    measured_words.append(
                        {
                            "text": word["text"],
                            "font_id": style.font_id,
                            "font_size_pt": size,
                            "line_spacing": 1,
                            "min_paragraph_lines": 1,
                            "native_width_mm": round(box.width_mm, 2),
                            "native_height_mm": round(box.height_mm, 2),
                        }
                    )
            copy[-1]["native_display_word_boxes"] = measured_words
        cursor = 0
        paragraphs = []
        for part in text.splitlines(keepends=True):
            if part.strip():
                paragraphs.append(
                    {"start_char": cursor, "end_char": cursor + len(part), "text": part}
                )
            elif paragraphs:
                paragraphs[-1]["end_char"] += len(part)
                paragraphs[-1]["text"] += part
            cursor += len(part)
        copy[-1]["paragraph_ranges"] = paragraphs
    photos = photo_sources(store, project, story)
    info = []
    for asset in photos:
        im = Image.open(BytesIO(store.read_blob(project, asset)))
        info.append(
            {
                "asset_id": asset,
                "width_px": im.width,
                "height_px": im.height,
                "maximum_width_mm_at_300ppi": round(im.width * 25.4 / 300, 2),
                "maximum_height_mm_at_300ppi": round(im.height * 25.4 / 300, 2),
                "isolated_alpha": im.mode == "RGBA"
                and im.getchannel("A").getextrema() != (255, 255),
            }
        )
    reference = None
    if cfg.get("quality_reference") and (ROOT / cfg["quality_reference"]).is_file():
        with tool_span(
            store,
            CallContext(
                project_id=project,
                run_id="m8-reference",
                agent_name="MaterialPreparation",
                stage="M8",
            ),
            "capture_quality_reference",
        ) as tool:
            reference = store.put_blob(
                project, (ROOT / cfg["quality_reference"]).read_bytes(), "image/png"
            ).id
            tool.output_asset_ids.append(reference)
    from editorial_studio.reference_studio.conditioning import capture

    style_images, style_cards = capture(store, project, cfg)
    return {
        "copy": copy,
        "photos": info,
        "available_typography": ConceptTypography.from_configuration(typography).model_dump(
            mode="json"
        ),
        "identity": identity.bible.model_dump(mode="json"),
        "quality_reference_asset_id": reference,
        "style_reference_asset_ids": style_images,
        "editorial_style_examples": style_cards,
    }, photos


def candidate_assets(store, project, binding):
    version = SceneRepository(store, project).version(binding.scene_id, binding.scene_version)
    expected = (
        binding.png_asset_id,
        binding.pdf_asset_id,
        binding.document_asset_id,
        binding.metadata_asset_id,
    )
    if expected != (
        version.png_asset_id,
        version.pdf_asset_id,
        version.document_asset_id,
        version.metadata_asset_id,
    ):
        raise ValueError("candidate evidence differs from its frozen scene")
    from editorial_studio.creative.evidence import creative_assets
    from editorial_studio.creative.models import CreativeSpread

    spread = store.get("creative_spread", binding.spread_id, CreativeSpread)
    if (
        spread is None
        or spread.project_id != project
        or spread.scene_version != binding.scene_version
    ):
        raise ValueError("candidate spread binding changed")
    return creative_assets(store, spread)


def tournament_assets(store, result):
    assets = {result.contact_sheet_asset_id, result.proof_book_asset_id}
    for binding in result.candidates:
        assets.update(candidate_assets(store, result.project_id, binding))
    for asset in assets:
        store.read_blob(result.project_id, asset)
    return sorted(assets)


def build_tournament(
    gateway,
    context,
    story_id,
    identity_id,
    *,
    mandate="Find the story's strongest visual expression.",
    continuation_configuration=None,
):
    from editorial_studio.creative.planning import VERSION, prepare_proposal

    store, project = gateway.store, context.project_id
    old = store.get("tournament", context.run_id, TournamentResult)
    checkpoint = store.get("tournament_build", context.run_id, TournamentBuild)
    if checkpoint and (
        checkpoint.project_id,
        checkpoint.story_id,
        checkpoint.identity_id,
        checkpoint.mandate,
    ) != (project, story_id, identity_id, mandate):
        raise ValueError("tournament ID is bound to different inputs")
    if old:
        if old.project_id != project:
            raise PermissionError("tournament outside project")
        tournament_assets(store, old)
        return old
    if checkpoint is None:
        identity = store.get("identity", identity_id, ProvisionalIdentity)
        if identity is None or identity.project_id != project:
            raise PermissionError("identity outside project")
        checkpoint = TournamentBuild(
            id=context.run_id,
            project_id=project,
            story_id=story_id,
            identity_id=identity_id,
            identity_snapshot_json=identity.model_dump_json(),
            mandate=mandate,
            configuration_json=json.dumps(configuration(), sort_keys=True),
            model=load_settings().text_model,
        )
        store.put_records(("tournament_build", checkpoint.id, project, checkpoint))
    if (
        continuation_configuration is not None
        and checkpoint.continuation_configuration_json is None
    ):
        checkpoint.continuation_configuration_json = json.dumps(
            continuation_configuration, sort_keys=True
        )
        store.put_records(("tournament_build", checkpoint.id, project, checkpoint))
    cfg = json.loads(checkpoint.continuation_configuration_json or checkpoint.configuration_json)
    identity = ProvisionalIdentity.model_validate_json(checkpoint.identity_snapshot_json)
    story = store.get("story", story_id, IngestedStory)
    if story is None or story.project_id != project:
        raise PermissionError("story outside project")
    if checkpoint.materials_json is None:
        materials, photos = material(store, project, story, identity, cfg)
        checkpoint.materials_json = json.dumps(materials, sort_keys=True)
        checkpoint.photo_ids = photos
        store.put_records(("tournament_build", checkpoint.id, project, checkpoint))
    materials = json.loads(checkpoint.materials_json)
    photos = checkpoint.photo_ids
    visible_materials, bindings = provider_materials(materials)
    reference = materials.get("quality_reference_asset_id")
    visual_references = materials.get("style_reference_asset_ids", []) + (
        [reference] if reference else []
    )
    if checkpoint.directions is None:
        call = gateway.invoke(
            context.model_copy(
                update={"agent_name": "CreativeConceptGenerator", "prompt_version": cfg["version"]}
            ),
            TextRequest(
                model=checkpoint.model,
                prompt=cfg["direction_prompt"]
                + "\nMandate: "
                + mandate
                + "\nMaterials: "
                + json.dumps(materials),
                images=[image_input(store, project, a) for a in photos[:3] + visual_references],
                reasoning_effort=cfg["reasoning_effort"],
                max_output_tokens=cfg["direction_max_output_tokens"],
            ),
            output_model=ConceptDirections,
        )
        checkpoint.directions = ConceptDirections.model_validate_json(call.visible_text)
        checkpoint.directions_call_id = call.call_id
        store.put_records(("tournament_build", checkpoint.id, project, checkpoint))
    candidates = []
    compiled_candidates = []
    for ci, direction in enumerate(checkpoint.directions.concepts):
        for vi in range(3):
            slot = f"{context.run_id}-c{ci + 1}v{vi + 1}"
            feedback = "None."
            accepted = None
            for attempt_index in range(cfg["maximum_repairs"] + 1):
                attempt_id = f"{slot}-r{attempt_index}"
                attempt = store.get("candidate_attempt", attempt_id, CandidateAttempt)
                if attempt and attempt.error and attempt.resolution_version == VERSION:
                    feedback = attempt.error
                    continue
                if attempt is None:
                    attempt = CandidateAttempt(
                        id=attempt_id,
                        project_id=project,
                        tournament_id=context.run_id,
                        concept_index=ci,
                        variation_index=vi,
                        attempt_index=attempt_index,
                    )
                if attempt.spread is not None and not attempt.error:
                    saved = attempt.spread
                    accepted = CandidateBinding(
                        slot_id=slot,
                        concept_index=ci,
                        variation_index=vi,
                        spread_id=saved.id,
                        scene_id=saved.scene_id,
                        scene_version=saved.scene_version,
                        concept_id=saved.concept_id,
                        review_id=saved.review_id,
                        png_asset_id=saved.png_asset_id,
                        pdf_asset_id=saved.pdf_asset_id,
                        document_asset_id=saved.document_asset_id,
                        metadata_asset_id=saved.metadata_asset_id,
                    )
                    candidate_assets(store, project, accepted)
                    compiled_candidates.append(
                        store.get("concept", saved.concept_id, CompiledConcept)
                    )
                    break
                if attempt.proposal_json is None:
                    failed = [
                        c
                        for c in store.list("call", m.ProviderCallRecord, project)
                        if c.run_id == attempt_id
                        and c.agent_name == "Composer"
                        and c.status == "failed"
                        and c.response_payload_asset_id
                    ]
                    if failed:
                        attempt.error = "Provider output failed the declared contract; use compact typography overrides and exact short handles."
                        attempt.provider_call_id = failed[-1].call_id
                        attempt.resolution_version = VERSION
                        store.put_records(("candidate_attempt", attempt.id, project, attempt))
                        feedback = attempt.error
                        continue
                if attempt.proposal_json is None:
                    previous = [
                        {
                            "concept": c.proposal.visual_metaphor,
                            "structure": c.proposal.compositional_structure,
                            "regions": [n.model_dump(mode="json") for n in c.proposal.graph.nodes],
                        }
                        for c in compiled_candidates
                    ]
                    prompt = (
                        cfg["proposal_prompt"]
                        + "\nFrozen concept: "
                        + direction.model_dump_json()
                        + "\nVariation mandate: "
                        + cfg["mandates"][vi]
                        + "\nOverall mandate: "
                        + mandate
                        + "\nMaterials: "
                        + json.dumps(visible_materials)
                        + "\nAlready completed arrangements to differ from: "
                        + json.dumps(previous)
                        + "\nCorrection feedback: "
                        + feedback
                    )
                    ctx = context.model_copy(
                        update={
                            "run_id": attempt_id,
                            "spread_id": attempt_id,
                            "agent_name": "Composer",
                            "parent_call_id": checkpoint.directions_call_id,
                            "prompt_version": cfg["version"],
                        }
                    )
                    try:
                        call = gateway.invoke(
                            ctx,
                            TextRequest(
                                model=checkpoint.model,
                                prompt=prompt,
                                images=[
                                    image_input(store, project, a)
                                    for a in photos[:3] + visual_references
                                ],
                                reasoning_effort=cfg.get(
                                    "proposal_reasoning_effort", cfg["reasoning_effort"]
                                ),
                                max_output_tokens=cfg["proposal_max_output_tokens"],
                            ),
                            output_model=ConceptProposal,
                        )
                    except InvalidModelOutput as error:
                        attempt.error = (
                            str(error)
                            + "; use compact typography overrides and exact short handles."
                        )
                        attempt.resolution_version = VERSION
                        store.put_records(("candidate_attempt", attempt.id, project, attempt))
                        feedback = attempt.error
                        continue
                    attempt.proposal_json = call.visible_text
                    attempt.provider_call_id = call.call_id
                    store.put_records(("candidate_attempt", attempt.id, project, attempt))
                try:
                    fit_context = context.model_copy(
                        update={
                            "run_id": attempt_id,
                            "spread_id": attempt_id,
                            "agent_name": "NativeTypographyPlanner",
                            "stage": "M8",
                            "parent_call_id": attempt.provider_call_id,
                        }
                    )
                    raw = ConceptProposal.model_validate_json(attempt.proposal_json)
                    if cfg.get("preserve_display_scale"):
                        available = {
                            s["name"]: s["font_size_pt"]
                            for s in materials["available_typography"]["styles"]
                        }
                        if raw.typography:
                            available.update(
                                {s.name: s.font_size_pt for s in raw.typography.styles}
                            )
                        headlines = [t for t in raw.treatments if t.style_role == "headline"]
                        chosen = max(headlines, key=lambda t: available.get(t.style_name, 42))
                        intended = available.get(chosen.style_name, 42)
                        if intended < 90:
                            raise ValueError(
                                "M10A needs a decisive display style of at least 90pt; reallocate the headline rather than making a small label."
                            )
                        chosen.minimum_display_pt = max(
                            chosen.minimum_display_pt or 0, intended * 0.80
                        )
                    proposal = prepare_proposal(
                        store,
                        fit_context,
                        raw,
                        materials,
                        minimum_image_ppi=cfg.get("minimum_image_ppi"),
                        resize_images=bool(cfg.get("minimum_image_ppi")),
                        maximum_image_reduction=0.10 if cfg.get("minimum_image_ppi") else None,
                    )
                    attempt.resolution_version = VERSION
                    attempt.error = None
                    if (
                        proposal.visual_metaphor != direction.visual_metaphor
                        or proposal.narrative_expression != direction.narrative_expression
                    ):
                        raise ValueError(
                            "preserve the frozen concept's visual_metaphor and narrative_expression verbatim"
                        )
                    spread = build_creative_spread(
                        gateway,
                        context.model_copy(
                            update={
                                "run_id": attempt_id + "-fit1",
                                "spread_id": attempt_id + "-fit1",
                                "stage": "M8",
                                "agent_name": "Composer",
                                "parent_call_id": attempt.provider_call_id,
                            }
                        ),
                        story_id,
                        identity_id,
                        proposal=proposal,
                        proposal_call_id=attempt.provider_call_id,
                        identity_snapshot=identity,
                    )
                    compiled = store.get("concept", spread.concept_id, CompiledConcept)
                    distances = [structural_distance(compiled, c) for c in compiled_candidates]
                    if distances and min(distances) < cfg["minimum_structural_distance"]:
                        raise ValueError(
                            "spatial variation is too similar to an existing candidate; change actual image/text regions or topology"
                        )
                    review = store.get("creative_review", spread.review_id, CreativeReview)
                    if review.execution.verdict != m.CriticVerdict.ACCEPT:
                        raise ValueError("candidate failed execution checks")
                    attempt.spread = spread
                    store.put_records(("candidate_attempt", attempt.id, project, attempt))
                    accepted = CandidateBinding(
                        slot_id=slot,
                        concept_index=ci,
                        variation_index=vi,
                        spread_id=spread.id,
                        scene_id=spread.scene_id,
                        scene_version=spread.scene_version,
                        concept_id=spread.concept_id,
                        review_id=spread.review_id,
                        png_asset_id=spread.png_asset_id,
                        pdf_asset_id=spread.pdf_asset_id,
                        document_asset_id=spread.document_asset_id,
                        metadata_asset_id=spread.metadata_asset_id,
                    )
                    compiled_candidates.append(compiled)
                    break
                except ValueError as error:
                    attempt.resolution_version = VERSION
                    attempt.error = str(error)
                    feedback = str(error)
                    store.put_records(("candidate_attempt", attempt.id, project, attempt))
            if accepted is None:
                raise ValueError(f"Candidate {slot} exhausted bounded repairs: {feedback}")
            candidates.append(accepted)
    by_id = {c.slot_id: c for c in candidates}
    bracket = sorted(by_id, key=lambda key: digest(context.run_id + key))
    matches = []
    round_number = 0
    while len(bracket) > 1:
        next_round = []
        for index in range(0, len(bracket), 2):
            if index + 1 == len(bracket):
                next_round.append(bracket[index])
                continue
            left, right = bracket[index : index + 2]
            match_id = f"{context.run_id}-round{round_number}-m{index // 2}"
            if int(digest(match_id)[0], 16) % 2:
                left, right = right, left
            match = store.get("tournament_match", match_id, TournamentMatch)
            if match is None:
                a, b = by_id[left], by_id[right]
                ra = store.get("creative_review", a.review_id, CreativeReview)
                rb = store.get("creative_review", b.review_id, CreativeReview)
                ctx = context.model_copy(
                    update={
                        "agent_name": "PairwiseVisualJudge",
                        "spread_id": match_id,
                        "prompt_version": cfg["version"],
                    }
                )
                call = gateway.invoke(
                    ctx,
                    TextRequest(
                        model=checkpoint.model,
                        prompt=cfg["comparison_prompt"]
                        + "\nSource: "
                        + json.dumps(materials["copy"]),
                        reasoning_effort=cfg["reasoning_effort"],
                        max_output_tokens=cfg["comparison_max_output_tokens"],
                        images=[
                            image_input(store, project, x)
                            for x in (
                                ra.inspection.full_asset_id,
                                rb.inspection.full_asset_id,
                                ra.inspection.crop_asset_id,
                                rb.inspection.crop_asset_id,
                            )
                        ],
                    ),
                    output_model=ComparativeAssessment,
                )
                assessment = ComparativeAssessment.model_validate_json(call.visible_text)
                tie = None
                if assessment.preferred_image == "tie":
                    winner = min((left, right), key=lambda key: digest(match_id + key))
                    tie = "Stable hash draw; no claim of aesthetic superiority."
                else:
                    winner = left if assessment.preferred_image == "A" else right
                match = TournamentMatch(
                    id=match_id,
                    project_id=project,
                    tournament_id=context.run_id,
                    candidate_a=left,
                    candidate_b=right,
                    winner_id=winner,
                    assessment=assessment,
                    provider_call_id=call.call_id,
                    tie_break=tie,
                )
                store.put_records(("tournament_match", match.id, project, match))
            if (match.candidate_a, match.candidate_b) != (left, right):
                raise ValueError("saved bracket inputs changed")
            next_round.append(match.winner_id)
            matches.append(match)
        bracket = next_round
        round_number += 1
    with tool_span(store, context, "assemble_candidate_tournament") as tool:
        sheet = Image.new("RGB", (1800, 920), "#e6e3dc")
        draw = ImageDraw.Draw(sheet)
        book = pymupdf.open()
        for index, candidate in enumerate(candidates):
            image = Image.open(BytesIO(store.read_blob(project, candidate.png_asset_id))).convert(
                "RGB"
            )
            image.thumbnail((580, 410))
            x = (index % 3) * 600 + 10
            y = (index // 3) * 460 + 32
            sheet.paste(image, (x, y))
            draw.text(
                (x, y - 22),
                candidate.slot_id + (" / WINNER" if candidate.slot_id == bracket[0] else ""),
                fill="#22211f",
            )
            with pymupdf.open(
                stream=store.read_blob(project, candidate.pdf_asset_id), filetype="pdf"
            ) as pdf:
                book.insert_pdf(pdf)
        contact = store.put_blob(project, png(sheet), "image/png")
        pdf = store.put_blob(project, book.tobytes(garbage=4, deflate=True), "application/pdf")
        book.close()
        winner_review = store.get("creative_review", by_id[bracket[0]].review_id, CreativeReview)
        result = TournamentResult(
            id=context.run_id,
            project_id=project,
            story_id=story_id,
            identity_id=identity_id,
            directions=checkpoint.directions,
            candidates=candidates,
            matches=matches,
            winner_id=bracket[0],
            contact_sheet_asset_id=contact.id,
            proof_book_asset_id=pdf.id,
            minimum_structural_distance=min(
                structural_distance(a, b) for a, b in combinations(compiled_candidates, 2)
            ),
            state="selected"
            if winner_review.decision.verdict == m.CriticVerdict.ACCEPT
            else "revision_required",
        )
        store.put_records(("tournament", result.id, project, result))
        tool.output_asset_ids.extend([contact.id, pdf.id, store.json_blob(project, result).id])
    return result
