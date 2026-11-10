"""Issue architecture, actual visual history and twelve-page reader proofs."""

import hashlib
import json
from io import BytesIO

import pymupdf
import yaml
from PIL import Image, ImageDraw
from shapely.geometry import box
from shapely.ops import unary_union

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.artifacts.inspection import image_input, vision_input
from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import story_sources
from editorial_studio.creative.issue_models import (
    IssueBlueprint,
    IssueBuild,
    IssueComposeAttempt,
    IssueCorrection,
    IssueResult,
    IssueSpread,
    PrinterSheet,
)
from editorial_studio.creative.models import (
    CompiledConcept,
    ConceptProposal,
    CreativeReview,
    CreativeSpread,
    CriticAssessment,
)
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.creative.tournament import configuration as tournament_configuration
from editorial_studio.creative.tournament import (
    material,
    provider_materials,
    tournament_assets,
)
from editorial_studio.creative.tournament_models import TournamentResult
from editorial_studio.llm.contracts import TextRequest
from editorial_studio.llm.gateway import InvalidModelOutput
from editorial_studio.photos.models import IngestedStory
from editorial_studio.photos.pipeline import png
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.tools import tool_span

PT = 72 / 25.4


def configuration():
    return yaml.safe_load((ROOT / "config/issue.yaml").read_text())


def fingerprint(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


def printer_map(page_count=12):
    if page_count != 12:
        raise ValueError("this issue contract requires twelve physical pages")
    return [
        PrinterSheet(
            sheet=i + 1,
            front_left=12 - 2 * i,
            front_right=1 + 2 * i,
            back_left=2 + 2 * i,
            back_right=11 - 2 * i,
        )
        for i in range(3)
    ]


def contact_sheet(store, project, spreads):
    image = Image.new("RGB", (1800, 920), "#e6e3dc")
    draw = ImageDraw.Draw(image)
    for index, entry in enumerate(spreads):
        tile = Image.open(BytesIO(store.read_blob(project, entry.spread.png_asset_id))).convert(
            "RGB"
        )
        tile.thumbnail((580, 410))
        x, y = (index % 3) * 600 + 10, (index // 3) * 460 + 32
        image.paste(tile, (x, y))
        draw.text(
            (x, y - 22),
            f"{entry.slot.left_page}/{entry.slot.right_page} · {entry.slot.phase}",
            fill="#22211f",
        )
    return store.put_blob(project, png(image), "image/png").id


def physical_pages(store, project, spreads):
    pages = []
    for entry in spreads:
        for side, number in [
            (m.PageSide.LEFT, entry.slot.left_page),
            (m.PageSide.RIGHT, entry.slot.right_page),
        ]:
            pages.append(
                m.PhysicalPage(
                    number=number,
                    side=side,
                    spread_id=entry.spread.scene_id,
                    is_cover=number in (1, 12),
                    folio_text=None if number in (1, 12) else str(number),
                )
            )
    mapping = m.PageMap(project_id=project, pages=sorted(pages, key=lambda page: page.number))
    by_scene = {entry.spread.scene_id: entry.spread for entry in spreads}
    pdf = pymupdf.open()
    for page in mapping.pages:
        spread = by_scene[page.spread_id]
        with pymupdf.open(
            stream=store.read_blob(project, spread.pdf_asset_id), filetype="pdf"
        ) as source:
            target = pdf.new_page(width=210 * PT, height=297 * PT)
            x = 0 if page.side == m.PageSide.LEFT else 210 * PT
            target.show_pdf_page(
                target.rect, source, 0, clip=pymupdf.Rect(x, 0, x + 210 * PT, 297 * PT)
            )
    blob = store.put_blob(project, pdf.tobytes(garbage=4, deflate=True), "application/pdf")
    # Review physical facing pairs beside one another. A grid of individual
    # reader pages places 4 and 5 on different rows, which a visual critic can
    # mistake for vertical misregistration of a perfectly continuous image.
    sheet = Image.new("RGB", (1800, 1380), "#e6e3dc")
    draw = ImageDraw.Draw(sheet)
    for index, (left, right) in enumerate([(12, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11)]):
        x, y = (index % 2) * 900 + 10, (index // 2) * 460 + 28
        for side, number in enumerate((left, right)):
            tile = Image.open(
                BytesIO(
                    pdf[number - 1]
                    .get_pixmap(matrix=pymupdf.Matrix(0.7, 0.7), alpha=False)
                    .tobytes("png")
                )
            ).convert("RGB")
            tile.thumbnail((430, 420))
            sheet.paste(tile, (x + side * tile.width, y))
        draw.text((x, y - 18), f"Physical PDF pages {left} | {right}", fill="#22211f")
    preview = store.put_blob(project, png(sheet), "image/png")
    pdf.close()
    return mapping, blob.id, preview.id


def issue_fingerprint(spreads, page_map):
    return fingerprint(
        {
            "spreads": [entry.model_dump(mode="json") for entry in spreads],
            "pages": page_map.model_dump(mode="json"),
        }
    )


def issue_assets(store, result):
    from editorial_studio.creative.evidence import creative_assets

    assets = {result.reader_pdf_asset_id, result.contact_sheet_asset_id}
    for entry in result.spreads:
        version = SceneRepository(store, result.project_id).version(
            entry.spread.scene_id, entry.spread.scene_version
        )
        if (
            version.png_asset_id,
            version.pdf_asset_id,
            version.document_asset_id,
            version.metadata_asset_id,
        ) != (
            entry.spread.png_asset_id,
            entry.spread.pdf_asset_id,
            entry.spread.document_asset_id,
            entry.spread.metadata_asset_id,
        ):
            raise ValueError("issue evidence differs from scene snapshot")
        assets.update(creative_assets(store, entry.spread))
        assets.update([entry.thumbnail_asset_id, entry.contact_sheet_asset_id])
    if result.evidence_fingerprint != issue_fingerprint(result.spreads, result.page_map):
        raise ValueError("issue evidence fingerprint mismatch")
    for asset in assets:
        store.read_blob(result.project_id, asset)
    return sorted(assets)


def advance_history(store, context, slot, spread, bible, index, source, prior):
    document = CanvasDocument.model_validate_json(
        store.read_blob(context.project_id, spread.document_asset_id)
    )
    metadata = RenderMetadata.model_validate_json(
        store.read_blob(context.project_id, spread.metadata_asset_id)
    )
    canvas = box(0, 0, 420, 297)

    def area(bounds):
        return box(
            bounds.x_mm, bounds.y_mm, bounds.x_mm + bounds.width_mm, bounds.y_mm + bounds.height_mm
        )

    images = [
        area(layer.bounds) for layer in document.scene.layers if isinstance(layer, m.ImageLayer)
    ]
    image_fraction = unary_union(images).intersection(canvas).area / canvas.area if images else 0
    compiled = store.get("concept", spread.concept_id, CompiledConcept)
    display_ids = {t.node_id for t in compiled.proposal.treatments if t.style_role == "headline"}
    headings = [
        area(layout.result.ink_bounds)
        for layout in metadata.text_layouts
        if layout.result.text_layer_id in display_ids
    ]
    ink_fraction = unary_union(headings).intersection(canvas).area / canvas.area if headings else 0
    after = bible.model_copy(deep=True)
    after.version = f"{context.run_id}-bible-{index + 1}"
    after.narrative_progression.append(
        m.IssuePhaseDirection(
            phase_name=f"{index + 1}:{slot.phase}",
            emotional_role=slot.narrative_goal,
            visual_behavior=f"Rendered photo-frame union {image_fraction:.3f}; display ink {ink_fraction:.3f}; selected scene {spread.scene_id}@{spread.scene_version}.",
        )
    )
    review = store.get("creative_review", spread.review_id, CreativeReview)
    entry = IssueSpread(
        id=f"{context.run_id}-history-{index}",
        project_id=context.project_id,
        issue_id=context.run_id,
        slot=slot,
        spread=spread,
        bible_before=bible,
        bible_after=after,
        thumbnail_asset_id=review.inspection.thumbnail_asset_id,
        contact_sheet_asset_id=review.inspection.thumbnail_asset_id,
        image_area_fraction=image_fraction,
        headline_ink_fraction=ink_fraction,
        source=source,
    )
    entry.contact_sheet_asset_id = contact_sheet(store, context.project_id, prior + [entry])
    store.put_records(("issue_history", entry.id, context.project_id, entry))
    return entry


def revise_issue(gateway, context, parent_id, expected_parent_fingerprint, corrections):
    parent = gateway.store.get("issue", parent_id, IssueResult)
    if parent is None or parent.project_id != context.project_id:
        raise PermissionError("parent issue outside project")
    issue_assets(gateway.store, parent)
    if parent.evidence_fingerprint != expected_parent_fingerprint:
        raise ValueError("stale parent issue fingerprint")
    corrections = [IssueCorrection.model_validate(c) for c in corrections]
    if len({c.slot_id for c in corrections}) != len(corrections) or not corrections:
        raise ValueError("corrections need unique issue slots")
    if not {c.slot_id for c in corrections} <= {s.id for s in parent.blueprint.slots}:
        raise ValueError("correction references unknown slot")
    replacements = {c.slot_id: c.replacement_story_id for c in corrections}
    stories = [replacements.get(s.id) or s.story_id for s in parent.blueprint.slots]
    return build_issue(
        gateway,
        context,
        stories,
        parent.identity_id,
        revision_of=parent_id,
        corrections=corrections,
    )


def build_issue(
    gateway,
    context,
    story_ids,
    identity_id,
    *,
    tournament_ids=None,
    reference_ids=None,
    reference_project="m10a-references",
    reference_art_director=True,
    prepared_composition_ids=None,
    revision_of=None,
    corrections=None,
):
    from editorial_studio.creative.planning import prepare_proposal

    store, project = gateway.store, context.project_id
    tournament_ids = tournament_ids or []
    reference_ids = reference_ids or []
    prepared_composition_ids = prepared_composition_ids or []
    corrections = corrections or []
    parent = store.get("issue", revision_of, IssueResult) if revision_of else None
    if revision_of and (parent is None or parent.project_id != project):
        raise PermissionError("parent issue outside project")
    if len(story_ids) != 6 or len(set(story_ids)) != 6:
        raise ValueError("a twelve-page issue needs six distinct story inputs")
    checkpoint = store.get("issue_build", context.run_id, IssueBuild)
    if checkpoint and (
        checkpoint.reference_ids,
        checkpoint.reference_project,
        checkpoint.reference_art_director,
        checkpoint.prepared_composition_ids,
    ) != (reference_ids, reference_project, reference_art_director, prepared_composition_ids):
        raise ValueError("issue ID is bound to different reference settings")
    if checkpoint and (
        checkpoint.project_id,
        checkpoint.story_ids,
        checkpoint.identity_id,
        checkpoint.tournament_ids,
        checkpoint.revision_of,
        checkpoint.corrections,
    ) != (project, story_ids, identity_id, tournament_ids, revision_of, corrections):
        raise ValueError("issue ID is bound to different inputs")
    old = store.get("issue", context.run_id, IssueResult)
    if old:
        if old.project_id != project:
            raise PermissionError("issue outside project")
        issue_assets(store, old)
        return old
    if checkpoint is None:
        identity = store.get("identity", identity_id, ProvisionalIdentity)
        if identity is None or identity.project_id != project:
            raise PermissionError("identity outside project")
        checkpoint = IssueBuild(
            id=context.run_id,
            project_id=project,
            identity_id=identity_id,
            story_ids=story_ids,
            tournament_ids=tournament_ids,
            reference_ids=reference_ids,
            reference_project=reference_project,
            reference_art_director=reference_art_director,
            prepared_composition_ids=prepared_composition_ids,
            identity_snapshot_json=identity.model_dump_json(),
            configuration_json=json.dumps(configuration(), sort_keys=True),
            model=load_settings().text_model,
            revision_of=revision_of,
            corrections=corrections,
        )
        if parent:
            parent_build = store.get("issue_build", parent.id, IssueBuild)
            checkpoint.identity_snapshot_json = parent_build.identity_snapshot_json
            checkpoint.blueprint = parent.blueprint.model_copy(deep=True)
            for slot, story_id in zip(checkpoint.blueprint.slots, story_ids, strict=True):
                slot.story_id = story_id
                correction = next((c for c in corrections if c.slot_id == slot.id), None)
                if correction:
                    slot.composition_mandate = (
                        "Current revision, superseding conflicting placement instructions: "
                        + correction.instruction
                    )
            checkpoint.architect_call_id = parent_build.architect_call_id
        reference = ROOT / tournament_configuration()["quality_reference"]
        if reference.is_file():
            checkpoint.reference_asset_id = store.put_blob(
                project, reference.read_bytes(), "image/png"
            ).id
        store.put_records(("issue_build", checkpoint.id, project, checkpoint))
    cfg = json.loads(checkpoint.configuration_json)
    base = ProvisionalIdentity.model_validate_json(checkpoint.identity_snapshot_json)
    stories = []
    for key in story_ids:
        story = store.get("story", key, IngestedStory)
        if story is None or story.project_id != project:
            raise PermissionError("story outside project")
        stories.append(story)
    winners = {}
    for key in tournament_ids:
        tournament = store.get("tournament", key, TournamentResult)
        if (
            tournament is None
            or tournament.project_id != project
            or tournament.story_id not in story_ids
            or tournament.identity_id != identity_id
        ):
            raise PermissionError("tournament inputs differ from issue")
        tournament_assets(store, tournament)
        binding = next(c for c in tournament.candidates if c.slot_id == tournament.winner_id)
        winners[tournament.story_id] = store.get(
            "creative_spread", binding.spread_id, CreativeSpread
        )
    aliases = {f"story-{i + 1}": story.id for i, story in enumerate(stories)}
    if checkpoint.blueprint is None:
        descriptions = [
            {
                "story_id": key,
                "copy": [
                    {"role": role, "text": derived.text}
                    for role, derived in story_sources(
                        store, project, next(s for s in stories if s.id == value)
                    )
                ],
                "has_tournament_winner": value in winners,
                "has_reference_library": bool(reference_ids),
            }
            for key, value in aliases.items()
        ]
        call = gateway.invoke(
            context.model_copy(
                update={"agent_name": "IssueArchitect", "prompt_version": cfg["version"]}
            ),
            TextRequest(
                model=checkpoint.model,
                prompt=cfg["architect_prompt"]
                + "\nIdentity: "
                + base.bible.model_dump_json()
                + "\nStories: "
                + json.dumps(descriptions),
                reasoning_effort=cfg["reasoning_effort"],
                max_output_tokens=cfg["architect_max_output_tokens"],
            ),
            output_model=IssueBlueprint,
        )
        blueprint = IssueBlueprint.model_validate_json(call.visible_text)
        for slot in blueprint.slots:
            slot.story_id = aliases.get(slot.story_id, slot.story_id)
        if {slot.story_id for slot in blueprint.slots} != set(story_ids):
            raise ValueError("architect omitted or invented a story")
        checkpoint.blueprint = blueprint
        checkpoint.architect_call_id = call.call_id
        store.put_records(("issue_build", checkpoint.id, project, checkpoint))
    reference_spreads = {}
    if reference_ids:
        from editorial_studio.reference_studio.issue_selection import select_sequence
        from editorial_studio.reference_studio.models import (
            CompositionProgram,
            ReferenceComposition,
        )
        from editorial_studio.reference_studio.service import build_compositions, composition_assets

        if parent and {c.slot_id for c in corrections} != {
            s.id for s in checkpoint.blueprint.slots
        }:
            raise ValueError(
                "Issue-wide reference reselection needs explicit corrections for all six slots"
            )
        prepared = {}
        for key in prepared_composition_ids:
            run = store.get("reference_composition", key, ReferenceComposition)
            if (
                run is None
                or (run.project_id, run.identity_id, run.reference_project)
                != (project, identity_id, reference_project)
                or not set(run.reference_ids) <= set(reference_ids)
                or run.story_id not in story_ids
            ):
                raise PermissionError("Prepared reference composition differs from issue inputs")
            if run.story_id in prepared:
                raise ValueError("Duplicate prepared composition for a story")
            composition_assets(store, run)
            prepared[run.story_id] = run
        runs = []
        for index, slot in enumerate(checkpoint.blueprint.slots):
            role = "cover" if slot.phase == "cover" else "spread"
            adapted = prepared.get(slot.story_id)
            if adapted is None or adapted.page_role != role:
                adapted = build_compositions(
                    gateway,
                    context.model_copy(
                        update={"run_id": context.run_id + f"-reference-{index}", "stage": "M10A"}
                    ),
                    slot.story_id,
                    identity_id,
                    reference_ids,
                    origin=reference_project,
                    art_director=reference_art_director,
                    page_role=role,
                )
            composition_assets(store, adapted)
            runs.append(adapted)
        selected = select_sequence(runs)
        selections = {
            slot.id: candidate.program_id
            for slot, candidate in zip(checkpoint.blueprint.slots, selected, strict=True)
        }
        if checkpoint.reference_selections and checkpoint.reference_selections != selections:
            raise ValueError("Reference sequence differs from the frozen issue selection")
        checkpoint.reference_selections = selections
        for slot, candidate, run in zip(checkpoint.blueprint.slots, selected, runs, strict=True):
            reference_spreads[slot.story_id] = candidate.spread
            program = next(
                p
                for p in (
                    CompositionProgram.model_validate_json(store.read_blob(project, asset))
                    for asset in run.program_asset_ids
                )
                if p.id == candidate.program_id
            )
            slot.composition_mandate = (
                "Preserve the selected captured composition: "
                + program.name
                + ". "
                + program.proposal.compositional_structure
                + " Mechanisms: "
                + ", ".join(program.characteristics.mechanisms)
                + (
                    ". Front page 1 on the right holds the entire headline and principal image; back page 12 on the left holds reading copy."
                    if slot.phase == "cover"
                    else ""
                )
                + ". Preserve exact source copy and selected photographs."
            )
        store.put_records(("issue_build", checkpoint.id, project, checkpoint))
    history = []
    bible = base.bible
    correction_map = {c.slot_id: c for c in corrections}
    for index, slot in enumerate(checkpoint.blueprint.slots):
        old_entry = store.get("issue_history", f"{context.run_id}-history-{index}", IssueSpread)
        if old_entry:
            if (
                old_entry.project_id != project
                or old_entry.slot != slot
                or old_entry.bible_before != bible
            ):
                raise ValueError("issue history diverges from the frozen sequence")
            history.append(old_entry)
            bible = old_entry.bible_after
            continue
        source = "composer"
        correction = correction_map.get(slot.id)
        if parent and correction is None:
            spread = parent.spreads[index].spread
            source = "retained"
        elif slot.story_id in reference_spreads and not (
            correction and correction.authored_proposal
        ):
            spread = reference_spreads[slot.story_id]
            source = "reference_program"
        elif (
            parent
            and correction
            and not correction.regenerate
            and not correction.authored_proposal
            and parent.spreads[index].spread.story_id == slot.story_id
            and store.get(
                "concept", parent.spreads[index].spread.concept_id, CompiledConcept
            ).reference_program_id
        ):
            from editorial_studio.canvas.models import CanvasDocument
            from editorial_studio.reference_studio.quality import analyze_layout

            spread = parent.spreads[index].spread
            compiled = store.get("concept", spread.concept_id, CompiledConcept)
            document = CanvasDocument.model_validate_json(
                store.read_blob(project, spread.document_asset_id)
            )
            if not analyze_layout(store, project, document, compiled.proposal).passed:
                raise ValueError(
                    "Reference composition no longer clears rendered readability; recompose it before issue reuse"
                )
            source = "retained"
        elif (parent and (not correction.regenerate or correction.authored_proposal)) or (
            slot.story_id in winners and slot.phase != "cover"
        ):
            selected = parent.spreads[index].spread if parent else winners[slot.story_id]
            compiled = store.get("concept", selected.concept_id, CompiledConcept)
            story = next(s for s in stories if s.id == slot.story_id)
            effective = base.model_copy(deep=True)
            effective.bible = bible
            mat, _ = material(
                store,
                project,
                story,
                effective,
                {**tournament_configuration(), "quality_reference": None},
            )
            ctx = context.model_copy(
                update={
                    "run_id": f"{context.run_id}-s{index}-selected",
                    "spread_id": f"{context.run_id}-s{index}-selected",
                    "parent_call_id": compiled.provider_call_id,
                    "agent_name": "Composer",
                }
            )
            prepared = prepare_proposal(
                store,
                ctx,
                correction.authored_proposal
                if correction and correction.authored_proposal
                else compiled.proposal,
                mat,
                minimum_image_ppi=300,
                resize_images=True,
            )
            prepared.visual_metaphor = slot.visual_metaphor
            prepared.narrative_expression = slot.narrative_goal
            spread = build_creative_spread(
                gateway,
                ctx,
                story.id,
                identity_id,
                proposal=prepared,
                proposal_call_id=None
                if correction and correction.authored_proposal
                else compiled.provider_call_id,
                identity_snapshot=effective,
            )
            source = (
                "authored_revision"
                if correction and correction.authored_proposal
                else ("native_repair" if parent else "tournament")
            )
        else:
            story = next(s for s in stories if s.id == slot.story_id)
            effective = base.model_copy(deep=True)
            effective.bible = bible
            mat, photos = material(
                store,
                project,
                story,
                effective,
                {**tournament_configuration(), "quality_reference": None},
            )
            visible, bindings = provider_materials(mat)
            references = ([history[-1].contact_sheet_asset_id] if history else []) + (
                [checkpoint.reference_asset_id] if checkpoint.reference_asset_id else []
            )
            feedback = correction.instruction if correction else "None"
            spread = None
            for repair in range(cfg["maximum_repairs"] + 1):
                key = f"{context.run_id}-s{index}-r{repair}"
                attempt = store.get("issue_compose_attempt", key, IssueComposeAttempt)
                if (
                    attempt
                    and attempt.proposal_json
                    and attempt.preparation_version != "native-issue-fit-v2"
                ):
                    attempt.error = None
                    attempt.preparation_version = "native-issue-fit-v2"
                    store.put_records(("issue_compose_attempt", key, project, attempt))
                if attempt and attempt.error:
                    feedback = attempt.error
                    continue
                if attempt is None:
                    attempt = IssueComposeAttempt(
                        id=key,
                        project_id=project,
                        issue_id=context.run_id,
                        slot_index=index,
                        preparation_version="native-issue-fit-v2",
                    )
                ctx = context.model_copy(
                    update={
                        "run_id": key,
                        "spread_id": key,
                        "agent_name": "Composer",
                        "parent_call_id": checkpoint.architect_call_id,
                        "prompt_version": cfg["version"],
                    }
                )
                if attempt.proposal_json is None:
                    failed = [
                        c
                        for c in store.list("call", m.ProviderCallRecord, project)
                        if c.run_id == key
                        and c.agent_name == "Composer"
                        and c.status == "failed"
                        and c.response_payload_asset_id
                    ]
                    if failed:
                        attempt.provider_call_id = failed[-1].call_id
                        attempt.error = (
                            "Known provider output failed its contract: "
                            + "; ".join(failed[-1].validation_errors)
                            + ". Every graph node needs exactly one matching treatment; use unique node IDs and exact short source handles."
                        )
                        store.put_records(("issue_compose_attempt", key, project, attempt))
                        feedback = attempt.error
                        continue
                    prior = [
                        {
                            "phase": entry.slot.phase,
                            "energy": entry.slot.visual_energy,
                            "photo_frame_fraction": entry.image_area_fraction,
                            "display_ink_fraction": entry.headline_ink_fraction,
                        }
                        for entry in history
                    ]
                    prompt = (
                        cfg["composer_prompt"]
                        + "\nIssue throughline: "
                        + checkpoint.blueprint.throughline
                        + "\nSlot: "
                        + slot.model_dump_json()
                        + "\nMaterials: "
                        + json.dumps(visible)
                        + "\nActual pacing history: "
                        + json.dumps(prior)
                        + "\nCorrection feedback: "
                        + feedback
                        + "\nRequired issue correction: "
                        + (correction.instruction if correction else "None")
                    )
                    try:
                        call = gateway.invoke(
                            ctx,
                            TextRequest(
                                model=checkpoint.model,
                                prompt=prompt,
                                images=[
                                    vision_input(store, ctx, a) for a in photos[:3] + references
                                ],
                                reasoning_effort=cfg["composer_reasoning_effort"],
                                max_output_tokens=tournament_configuration()[
                                    "proposal_max_output_tokens"
                                ],
                            ),
                            output_model=ConceptProposal,
                        )
                    except InvalidModelOutput as error:
                        attempt.error = (
                            str(error)
                            + "; every graph node needs exactly one matching treatment; use unique IDs and exact short source handles."
                        )
                        store.put_records(("issue_compose_attempt", key, project, attempt))
                        feedback = attempt.error
                        continue
                    attempt.proposal_json = call.visible_text
                    attempt.provider_call_id = call.call_id
                    store.put_records(("issue_compose_attempt", key, project, attempt))
                try:
                    proposal = prepare_proposal(
                        store,
                        ctx,
                        ConceptProposal.model_validate_json(attempt.proposal_json),
                        mat,
                        minimum_image_ppi=300,
                        resize_images=True,
                        maximum_image_reduction=0.10,
                    )
                    spread = build_creative_spread(
                        gateway,
                        ctx.model_copy(
                            update={"run_id": key + "-fit2", "spread_id": key + "-fit2"}
                        ),
                        story.id,
                        identity_id,
                        proposal=proposal,
                        proposal_call_id=attempt.provider_call_id,
                        identity_snapshot=effective,
                    )
                    break
                except ValueError as error:
                    feedback = str(error)
                    attempt.error = feedback
                    store.put_records(("issue_compose_attempt", key, project, attempt))
            if spread is None:
                raise ValueError(f"Issue slot {slot.id} exhausted bounded repairs: {feedback}")
        review = store.get("creative_review", spread.review_id, CreativeReview)
        if review.artistic and review.artistic.verdict == m.CriticVerdict.REPLAN:
            raise ValueError(
                f"Issue slot {slot.id} requires replanning: {review.artistic.rationale}"
            )
        with tool_span(store, context, "advance_issue_visual_history") as tool:
            entry = advance_history(store, context, slot, spread, bible, index, source, history)
            tool.output_asset_ids.extend(
                [
                    entry.thumbnail_asset_id,
                    entry.contact_sheet_asset_id,
                    store.json_blob(project, entry).id,
                ]
            )
        history.append(entry)
        bible = entry.bible_after
    with tool_span(store, context, "assemble_twelve_physical_pages") as tool:
        mapping, pdf, pages = physical_pages(store, project, history)
        sheet = history[-1].contact_sheet_asset_id
        tool.output_asset_ids.extend([pdf, pages, sheet])
    call = gateway.invoke(
        context.model_copy(
            update={"agent_name": "IssueArchitect", "prompt_version": cfg["version"]}
        ),
        TextRequest(
            model=checkpoint.model,
            prompt=cfg["coherence_prompt"] + "\nIssue: " + checkpoint.blueprint.model_dump_json(),
            images=[image_input(store, project, a) for a in (sheet, pages)],
            reasoning_effort=cfg["reasoning_effort"],
            max_output_tokens=cfg["coherence_max_output_tokens"],
        ),
        output_model=CriticAssessment,
    )
    coherence = CriticAssessment.model_validate_json(call.visible_text)
    result = IssueResult(
        id=context.run_id,
        project_id=project,
        identity_id=identity_id,
        blueprint=checkpoint.blueprint,
        page_map=mapping,
        printer_sheets=printer_map(),
        spreads=history,
        coherence=coherence,
        coherence_call_id=call.call_id,
        reader_pdf_asset_id=pdf,
        contact_sheet_asset_id=sheet,
        evidence_fingerprint=issue_fingerprint(history, mapping),
        state="review" if coherence.verdict == m.CriticVerdict.ACCEPT else "revision_required",
    )
    store.put_records(("issue", result.id, project, result))
    return result
