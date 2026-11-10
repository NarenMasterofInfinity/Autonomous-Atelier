"""Resumable concept → typed compiler → artifacts → scene → independent critic passes."""

import json

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.artifacts.inspection import image_input
from editorial_studio.artifacts.service import build_artifact
from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import compile_concept, photo_sources, story_sources
from editorial_studio.creative.critics import configuration, review_spread
from editorial_studio.creative.models import (
    CompiledConcept,
    ConceptProposal,
    CreativeAttempt,
    CreativeBuildCheckpoint,
    CreativeSpread,
)
from editorial_studio.llm.contracts import TextRequest
from editorial_studio.photos.models import IngestedStory
from editorial_studio.settings import load_settings
from editorial_studio.spatial.assistant import SpatialAssistant
from editorial_studio.telemetry.tools import tool_span


def build_creative_spread(
    gateway,
    context,
    story_id,
    identity_id,
    *,
    mandate="Find the visual metaphor in the story.",
    with_visual_critics=True,
    proposal: ConceptProposal | None = None,
    proposal_call_id: str | None = None,
    identity_snapshot: ProvisionalIdentity | None = None,
    reference_program_id: str | None = None,
):
    store = gateway.store
    project = context.project_id
    prior = store.get("creative_spread", context.run_id, CreativeSpread)
    if prior:
        frozen_kind = store.get("concept", prior.concept_id, CompiledConcept)
        if frozen_kind is None or frozen_kind.reference_program_id != reference_program_id:
            raise ValueError("Creative run is bound to a different reference program")
        if proposal is not None:
            frozen = store.get("concept", prior.concept_id, CompiledConcept)
            if frozen is None or frozen.proposal != proposal:
                raise ValueError("authored run ID is already bound to a different proposal")
        if (
            prior.project_id != project
            or prior.story_id != story_id
            or prior.identity_id != identity_id
        ):
            raise PermissionError("creative run belongs to another project")
        from editorial_studio.creative.models import CreativeReview

        review = store.get("creative_review", prior.review_id, CreativeReview)
        if review is not None and review.execution.verdict != m.CriticVerdict.ACCEPT:
            candidates = [
                candidate
                for candidate in store.list("creative_candidate", CreativeSpread, project)
                if candidate.run_id == context.run_id
                and candidate.story_id == story_id
                and candidate.identity_id == identity_id
            ]
            valid = [
                candidate
                for candidate in candidates
                if store.get(
                    "creative_review", candidate.review_id, CreativeReview
                ).execution.verdict
                == m.CriticVerdict.ACCEPT
            ]
            if not valid:
                raise ValueError("creative run has no technically valid revision to recover")
            with tool_span(store, context, "recover_last_technically_valid_revision") as tool:
                prior = valid[-1].model_copy(update={"id": context.run_id})
                store.put_records(("creative_spread", prior.id, project, prior))
                tool.output_asset_ids.append(store.json_blob(project, prior).id)
        from editorial_studio.creative.evidence import creative_assets

        creative_assets(store, prior)
        return prior
    checkpoint = store.get("creative_build", context.run_id, CreativeBuildCheckpoint)
    if checkpoint is None:
        cfg = configuration()
        settings = load_settings()
        identity = identity_snapshot or store.get("identity", identity_id, ProvisionalIdentity)
        if identity is None or identity.project_id != project:
            raise PermissionError("identity not in project")
        if identity.id != identity_id:
            raise ValueError("identity snapshot ID differs from the requested identity")
        checkpoint = CreativeBuildCheckpoint(
            id=context.run_id,
            project_id=project,
            story_id=story_id,
            identity_id=identity_id,
            identity_snapshot_json=identity.model_dump_json(),
            mandate=mandate,
            prompt_template=cfg["concept_prompt"],
            prompt_version=cfg["version"],
            model=settings.text_model,
            reasoning_effort=cfg.get(
                "concept_reasoning_effort", settings.creative_reasoning_effort
            ),
            max_output_tokens=cfg["max_output_tokens"],
            maximum_repairs=cfg["maximum_repairs"],
            with_visual_critics=with_visual_critics,
            reference_program_id=reference_program_id,
        )
        store.put_records(("creative_build", checkpoint.id, project, checkpoint))
    if checkpoint.project_id != project or (checkpoint.story_id, checkpoint.identity_id) != (
        story_id,
        identity_id,
    ):
        raise PermissionError("creative checkpoint input mismatch")
    identity = ProvisionalIdentity.model_validate_json(checkpoint.identity_snapshot_json)
    if checkpoint.reference_program_id != reference_program_id:
        raise ValueError("Creative checkpoint is bound to a different reference program")
    story = store.get("story", story_id, IngestedStory)
    if story is None or story.project_id != project:
        raise PermissionError("story not in project")
    sources = story_sources(store, project, story)
    photos = photo_sources(store, project, story)
    feedback = "None."
    last = None
    last_technically_valid = None
    for number in range(checkpoint.maximum_repairs + 1):
        attempt_id = f"{context.run_id}-a{number}"
        attempt = store.get("creative_attempt", attempt_id, CreativeAttempt)
        if attempt and attempt.spread_id:
            last = store.get("creative_candidate", attempt.spread_id, CreativeSpread)
            if last:
                if last.state == "approved_for_identity_review":
                    break
                from editorial_studio.creative.models import CreativeReview

                review = store.get("creative_review", last.review_id, CreativeReview)
                if review.execution.verdict == m.CriticVerdict.ACCEPT:
                    last_technically_valid = last
                feedback = review.decision.model_dump_json()
                continue
        if attempt and attempt.error:
            feedback = attempt.error
            continue
        ctx = context.model_copy(
            update={"spread_id": attempt_id, "prompt_version": checkpoint.prompt_version}
        )
        compiled = store.get("concept", attempt_id, CompiledConcept)
        if compiled is None:
            if attempt is None:
                attempt = CreativeAttempt(id=attempt_id, project_id=project, run_id=context.run_id)
                if proposal is not None:
                    attempt.proposal = proposal
                    attempt.provider_call_id = proposal_call_id
                else:
                    from editorial_studio.canvas.typography.engine import TypographyEngine
                    from editorial_studio.canvas.typography.fonts import FontRegistry
                    from editorial_studio.design_system.models import PairingCatalog
                    from editorial_studio.design_system.system import DesignSystem

                    system = DesignSystem(
                        tokens=identity.tokens,
                        pairing_catalog=PairingCatalog(pairings=[identity.pairing]),
                        font_configuration=identity.typography,
                    )
                    typography = system.typography(identity.bible)
                    engine = TypographyEngine(FontRegistry(configuration=typography))
                    text_rows = []
                    for role, derived in sources:
                        row = {
                            "role": role,
                            "id": derived.id,
                            "text": derived.text,
                            "source_char_count": len(derived.text),
                        }
                        if role == "headline":
                            native = engine.layout_paragraph(
                                m.TextLayer(
                                    id="measure",
                                    name="measure",
                                    semantic_role=role,
                                    z_index=0,
                                    bounds=m.BoundsMM(
                                        x_mm=0, y_mm=0, width_mm=10000, height_mm=1000
                                    ),
                                    text_content=derived.text,
                                    style_name=identity.bible.id + ".headline",
                                )
                            )
                            row["minimum_headline_path_length_mm"] = round(
                                native.result.logical_bounds.width_mm + 5, 2
                            )
                        if role in ("body", "deck", "headline"):
                            measurements = []
                            for measure_width in (68, 74, 85, 100, 140, 160, 180):
                                measured = engine.layout_paragraph(
                                    m.TextLayer(
                                        id="measure-" + role,
                                        name="measure",
                                        semantic_role=role,
                                        z_index=0,
                                        bounds=m.BoundsMM(
                                            x_mm=0, y_mm=0, width_mm=measure_width, height_mm=10000
                                        ),
                                        text_content=derived.text,
                                        style_name=identity.bible.id + "." + role,
                                    )
                                )
                                measurements.append(
                                    {
                                        "width_mm": measure_width,
                                        "natural_height_mm": round(
                                            measured.result.logical_bounds.height_mm, 2
                                        ),
                                    }
                                )
                            row["rectangular_copyfit"] = measurements
                        text_rows.append(row)
                    text = json.dumps(text_rows, ensure_ascii=False)
                    photo_info = []
                    from io import BytesIO

                    from PIL import Image

                    for asset in photos:
                        image = Image.open(BytesIO(store.read_blob(project, asset)))
                        photo_info.append(
                            {
                                "asset_id": asset,
                                "width_px": image.width,
                                "height_px": image.height,
                                "isolated_alpha": image.mode == "RGBA"
                                and image.getchannel("A").getextrema() != (255, 255),
                            }
                        )
                    prompt = checkpoint.prompt_template.format(
                        mandate=checkpoint.mandate,
                        identity=identity.bible.model_dump_json(),
                        text=text,
                        photos=photo_info,
                        feedback=feedback,
                    )
                    prompt += "\nAllowed capability IDs are CAP_01 through CAP_10 only; use [] when none is required. Photos below 150 PPI at intended size require a grain or halftone image_treatment, or a smaller frame. Set image_treatment on each treatment; native is fine for text/vector nodes. Avoid group/mask graph nodes. Artifact requests may be empty."
                    call = gateway.invoke(
                        ctx.model_copy(update={"agent_name": "CreativeConceptGenerator"}),
                        TextRequest(
                            model=checkpoint.model,
                            prompt=prompt,
                            reasoning_effort=checkpoint.reasoning_effort,
                            max_output_tokens=checkpoint.max_output_tokens,
                            images=[image_input(store, project, a) for a in photos[:3]],
                        ),
                        output_model=ConceptProposal,
                    )
                    attempt.proposal = ConceptProposal.model_validate_json(call.visible_text)
                    attempt.provider_call_id = call.call_id
                store.put_records(("creative_attempt", attempt.id, project, attempt))
            try:
                artifacts = [
                    build_artifact(
                        gateway,
                        ctx.model_copy(
                            update={
                                "agent_name": "ArtifactPlanner",
                                "stage": "M6",
                                "parent_call_id": attempt.provider_call_id,
                            }
                        ),
                        request,
                        photos[:2],
                    )
                    for request in attempt.proposal.artifact_requirements
                ]
                compiled = compile_concept(
                    store,
                    ctx,
                    story,
                    identity,
                    attempt.proposal,
                    concept_id=attempt_id,
                    provider_call_id=attempt.provider_call_id,
                    artifacts=artifacts,
                    reference_program_id=checkpoint.reference_program_id,
                )
                if compiled.compiler.unsupported_features:
                    raise ValueError(
                        "; ".join(f.reason for f in compiled.compiler.unsupported_features)
                    )
            except ValueError as error:
                attempt.error = str(error)
                store.put_records(("creative_attempt", attempt.id, project, attempt))
                feedback = attempt.error
                if proposal is not None:
                    raise
                continue
        if (
            compiled.project_id != project
            or compiled.story_id != story.id
            or compiled.identity_id != identity.id
        ):
            raise ValueError("compiled concept input bindings differ from this run")
        if compiled.compiler.unsupported_features:
            raise ValueError("compiled concept still has unsupported features")
        repository = SceneRepository(store, project)
        executor = Executor(repository, Renderer(store, project))
        assistant = SpatialAssistant(executor)
        try:
            try:
                version = repository.head(attempt_id)
            except KeyError:
                scene = compiled.compiler.target_scene_skeleton.model_copy(
                    update={"layers": [], "version": "initial", "parent_version": None}
                )
                document = CanvasDocument.from_scene(scene)
                document.typography = compiled.typography
                document.enforce_text_provenance = True
                document.background_color = compiled.background_color
                version = executor.initialize(document, ctx)
            if version.version == "initial":
                version = assistant.apply(compiled.recipe.operations, attempt_id, ctx)
            else:
                patch = (
                    store.get("scene_patch", version.patch_id, m.ScenePatch)
                    if version.patch_id
                    else None
                )
                if (
                    version.run_id != context.run_id
                    or patch is None
                    or patch.operations != compiled.recipe.operations
                ):
                    raise ValueError("committed creative scene differs from frozen recipe")
        except ValueError as error:
            attempt.error = str(error)
            store.put_records(("creative_attempt", attempt.id, project, attempt))
            feedback = attempt.error
            if proposal is not None:
                raise
            continue
        with tool_span(store, ctx, "bind_rendered_source_coverage") as tool:
            ledger = ProvenanceLedger(store, project)
            for operation in compiled.recipe.operations:
                if isinstance(operation, m.AddTextOp):
                    ledger.bind(
                        operation.derived_text_id, [operation.layer_id], scene_id=attempt_id
                    )
            tool.output_asset_ids.append(store.json_blob(project, compiled.recipe).id)
        critic_context = ctx.model_copy(update={"parent_call_id": compiled.provider_call_id})
        review = review_spread(
            gateway,
            critic_context,
            compiled,
            version,
            story,
            with_visual_critics=checkpoint.with_visual_critics,
        )
        last = CreativeSpread(
            id=attempt_id,
            project_id=project,
            story_id=story.id,
            identity_id=identity.id,
            scene_id=attempt_id,
            scene_version=version.version,
            concept_id=compiled.id,
            review_id=review.id,
            png_asset_id=version.png_asset_id,
            pdf_asset_id=version.pdf_asset_id,
            document_asset_id=version.document_asset_id,
            metadata_asset_id=version.metadata_asset_id,
            state="approved_for_identity_review"
            if review.decision.verdict == m.CriticVerdict.ACCEPT
            else "revision_required",
            run_id=context.run_id,
        )
        if review.execution.verdict == m.CriticVerdict.ACCEPT:
            last_technically_valid = last
        attempt.spread_id = last.id
        store.put_records(
            ("creative_candidate", last.id, project, last),
            ("creative_attempt", attempt.id, project, attempt),
        )
        if (
            last.state == "approved_for_identity_review"
            or review.decision.stagnation_detected
            or proposal is not None
            or review.decision.verdict == m.CriticVerdict.REPLAN
        ):
            break
        feedback = review.decision.model_dump_json()
    if last is not None:
        from editorial_studio.creative.models import CreativeReview

        last_review = store.get("creative_review", last.review_id, CreativeReview)
        if last_review.execution.verdict != m.CriticVerdict.ACCEPT:
            last = last_technically_valid
    if last is None:
        raise ValueError(
            "No concept cleared technical rendering after bounded attempts: " + feedback
        )
    result = last.model_copy(update={"id": context.run_id})
    store.put_records(("creative_spread", context.run_id, project, result))
    return result
