"""Technical validity, visual art judgment and concept fidelity remain separate critics."""

import hashlib
from io import BytesIO

import numpy as np
import yaml
from PIL import Image

from editorial_studio.artifacts.inspection import image_input, inspect_render
from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import utcnow
from editorial_studio.creative.compiler import source_partitions, story_sources
from editorial_studio.creative.models import ComparativeAssessment, CreativeReview, CriticAssessment
from editorial_studio.llm.contracts import TextRequest
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.tools import tool_span


def configuration():
    return yaml.safe_load((ROOT / "config/creative.yaml").read_text())


def finding(category, description, fix, layers=None, severity="HIGH"):
    return m.CritiqueFinding(
        category=category,
        severity=severity,
        description=description,
        actionable_fix=fix,
        target_layer_ids=layers or [],
    )


def execution_critic(store, project, compiled, version, story):
    document = CanvasDocument.model_validate_json(
        store.read_blob(project, version.document_asset_id)
    )
    metadata = RenderMetadata.model_validate_json(
        store.read_blob(project, version.metadata_asset_id)
    )
    findings = []
    by_id = {layer.id: layer for layer in document.scene.layers}
    treatments = {t.node_id: t for t in compiled.proposal.treatments}
    expected = {op.layer_id: op for op in compiled.recipe.operations if isinstance(op, m.AddTextOp)}
    if {layer.id for layer in document.scene.layers if isinstance(layer, m.TextLayer)} != set(
        expected
    ):
        findings.append(
            finding(
                "source_coverage",
                "Rendered text objects differ from the compiled source partition.",
                "Restore the exact compiled text layers.",
            )
        )
    for node_id, (role, derived, start, end) in source_partitions(
        store, project, story, compiled.proposal
    ).items():
        layers = [
            layer
            for layer in document.scene.layers
            if isinstance(layer, m.TextLayer) and layer.id == node_id
        ]
        if (
            len(layers) != 1
            or layers[0].text_content != derived.text[start:end]
            or node_id not in expected
            or layers[0].derived_text_id != expected[node_id].derived_text_id
        ):
            findings.append(
                finding(
                    "source_coverage",
                    "Source derivation is omitted, duplicated or changed.",
                    "Restore complete source-bound text.",
                )
            )
        for layer in layers:
            p = next(p for p in document.presentations if p.layer_id == layer.id)
            style = next(s for s in compiled.typography.styles if s.name == layer.style_name)
            if role == "body" and style.font_size_pt < compiled.tokens.minimum_body_pt:
                findings.append(
                    finding(
                        "body_size",
                        "Reading type is below the identity floor.",
                        "Restore the body size and reallocate copy.",
                        [layer.id],
                    )
                )
            if role == "body" and (
                p.glyph_transforms or abs(p.transform.a) < 0.999 or abs(p.transform.d) < 0.999
            ):
                findings.append(
                    finding(
                        "body_scale",
                        "Reading text has been geometrically shrunk or distorted.",
                        "Use the original reading size and a new region.",
                        [layer.id],
                    )
                )
            if layer.opacity < 0.95 and role == "body":
                findings.append(
                    finding(
                        "body_visibility",
                        "Body copy has reduced opacity.",
                        "Restore reading contrast.",
                        [layer.id],
                    )
                )
            bounds = layer.bounds
            if (
                bounds.x_mm < 0
                or bounds.y_mm < 0
                or bounds.x_mm + bounds.width_mm > 420.01
                or bounds.y_mm + bounds.height_mm > 297.01
            ):
                findings.append(
                    finding(
                        "canvas",
                        "Source text frame extends beyond the spread.",
                        "Reallocate its complete source copy.",
                        [layer.id],
                    )
                )
            if role == "body" and bounds.x_mm < 220 and bounds.x_mm + bounds.width_mm > 200:
                findings.append(
                    finding(
                        "fold",
                        "Reading text crosses the fold-safe region.",
                        "Move reading copy away from the fold or justify and inspect the rule break.",
                        [layer.id],
                        severity="MEDIUM",
                    )
                )
    for layout in metadata.text_layouts:
        for f in layout.result.findings:
            findings.append(
                finding(
                    "typography",
                    f.detail,
                    "Revise the text region or authored treatment.",
                    [layout.result.text_layer_id],
                    severity=f.severity.value,
                )
            )
    for node in compiled.proposal.graph.nodes:
        layer = by_id.get(node.id)
        if isinstance(layer, m.ImageLayer):
            image = Image.open(BytesIO(store.read_blob(project, layer.asset_id)))
            ppi = (
                min(image.width / layer.bounds.width_mm, image.height / layer.bounds.height_mm)
                * 25.4
            )
            if ppi < 150 and treatments[node.id].image_treatment == "native":
                findings.append(
                    finding(
                        "source_ppi",
                        f"Photo has {ppi:.0f} native PPI at this frame.",
                        "Use a smaller frame or an intentional stylized treatment.",
                        [node.id],
                    )
                )
            elif ppi < 250:
                findings.append(
                    finding(
                        "source_ppi",
                        f"Photo has {ppi:.0f} source PPI; visual crop inspection remains required.",
                        "Inspect native source detail before print approval.",
                        [node.id],
                        severity="MEDIUM",
                    )
                )
    for rel in compiled.proposal.graph.relationships:
        a, b = by_id.get(rel.source_id), by_id.get(rel.target_id)
        if a is None or b is None:
            findings.append(
                finding(
                    "concept_object",
                    "Concept relationship has an unresolved object.",
                    "Resolve its artifact or revise the concept.",
                )
            )
            continue
        if (
            rel.relation == "behind"
            and a.z_index >= b.z_index
            or rel.relation == "above"
            and a.z_index <= b.z_index
        ):
            findings.append(
                finding(
                    "depth",
                    "Authored foreground/background order was not realized.",
                    "Recompile the depth relationship.",
                    [a.id, b.id],
                )
            )
    failed = any(f.severity in (m.Severity.HIGH, m.Severity.CRITICAL) for f in findings)
    return CriticAssessment(
        verdict="REVISE" if failed else "ACCEPT",
        score=0 if failed else 1,
        findings=findings,
        rationale="Deterministic source, typography, placement and sampling checks. This is not an artistic score.",
    )


def visual_change(store, project, old_asset, new_asset):
    def array(asset):
        return (
            np.asarray(
                Image.open(BytesIO(store.read_blob(project, asset)))
                .convert("RGB")
                .resize((200, 140)),
                dtype="float32",
            )
            / 255
        )

    return float(np.mean(np.abs(array(old_asset) - array(new_asset))))


def stagnated(comparisons, window=3):
    return len(comparisons) >= window and all(
        value in ("previous", "tie") for value in comparisons[-window:]
    )


def review_spread(gateway, context, compiled, version, story, *, with_visual_critics=True):
    store = gateway.store
    project = context.project_id
    record_id = hashlib.sha256(
        (project + compiled.id + version.version + str(with_visual_critics)).encode()
    ).hexdigest()
    old = store.get("creative_review", record_id, CreativeReview)
    if old:
        return old
    cfg = configuration()
    settings = load_settings()
    calls = []
    with tool_span(store, context, "execution_critic") as tool:
        execution = execution_critic(store, project, compiled, version, story)
        tool.output_asset_ids.append(store.json_blob(project, execution).id)
    metadata = RenderMetadata.model_validate_json(
        store.read_blob(project, version.metadata_asset_id)
    )
    inspection = inspect_render(
        store,
        context,
        version.png_asset_id,
        dpi=metadata.dpi,
        crop=compiled.proposal.inspection_crop,
    )
    artistic = None
    fidelity = None
    comparison = None
    change = None
    history = [
        r
        for r in store.list("creative_review", CreativeReview, project)
        if r.run_id == context.run_id and r.scene_version != version.version
    ]
    if with_visual_critics and execution.verdict == m.CriticVerdict.ACCEPT:
        effective_bible = compiled.identity_bible
        if effective_bible is None:
            from editorial_studio.art_direction.models import ProvisionalIdentity
            from editorial_studio.creative.models import CreativeBuildCheckpoint

            checkpoint = store.get("creative_build", context.run_id, CreativeBuildCheckpoint)
            if checkpoint:
                effective_bible = ProvisionalIdentity.model_validate_json(
                    checkpoint.identity_snapshot_json
                ).bible
        prompt = cfg["artistic_prompt"].format(
            concept=compiled.proposal.model_dump_json(),
            identity=effective_bible.model_dump_json()
            if effective_bible
            else compiled.tokens.model_dump_json(),
            rule_breaks=[r.model_dump() for r in compiled.proposal.spatial_intent.rule_breaks],
        )
        prompt += "\nExact source copy for semantic and readability context: " + str(
            [
                {"role": role, "text": derived.text}
                for role, derived in story_sources(store, project, story)
            ]
        )
        images = [
            image_input(store, project, a)
            for a in (
                inspection.full_asset_id,
                inspection.thumbnail_asset_id,
                inspection.crop_asset_id,
            )
        ]
        call = gateway.invoke(
            context.model_copy(update={"agent_name": "ArtisticCritic"}),
            TextRequest(
                model=settings.text_model,
                prompt=prompt,
                reasoning_effort=cfg.get(
                    "artistic_reasoning_effort", settings.creative_reasoning_effort
                ),
                max_output_tokens=cfg["critic_max_output_tokens"],
                images=images,
            ),
            output_model=CriticAssessment,
        )
        artistic = CriticAssessment.model_validate_json(call.visible_text)
        calls.append(call.call_id)
        prompt = cfg["fidelity_prompt"].format(concept=compiled.hybrid.model_dump_json())
        call = gateway.invoke(
            context.model_copy(update={"agent_name": "ConceptFidelityEvaluator"}),
            TextRequest(
                model=settings.text_model,
                prompt=prompt,
                reasoning_effort=cfg.get("fidelity_reasoning_effort", settings.reasoning_effort),
                max_output_tokens=cfg["critic_max_output_tokens"],
                images=[
                    image_input(store, project, a)
                    for a in (
                        compiled.hybrid.sketch.asset_id,
                        inspection.full_asset_id,
                        inspection.crop_asset_id,
                    )
                ],
            ),
            output_model=CriticAssessment,
        )
        fidelity = CriticAssessment.model_validate_json(call.visible_text)
        calls.append(call.call_id)
        if history:
            previous = history[-1]
            swap = int(record_id[0], 16) % 2
            assets = [previous.inspection.full_asset_id, inspection.full_asset_id]
            if swap:
                assets.reverse()
            call = gateway.invoke(
                context.model_copy(update={"agent_name": "ArtisticCritic"}),
                TextRequest(
                    model=settings.text_model,
                    prompt="Compare image A and image B as editorial spreads. Prefer the one with stronger hierarchy, readability, image integration and restraint, or return tie. Identify concrete differences; no assumed improvement from revision order.",
                    reasoning_effort=cfg.get(
                        "fidelity_reasoning_effort", settings.reasoning_effort
                    ),
                    max_output_tokens=cfg["critic_max_output_tokens"],
                    images=[image_input(store, project, a) for a in assets],
                ),
                output_model=ComparativeAssessment,
            )
            judged = ComparativeAssessment.model_validate_json(call.visible_text)
            calls.append(call.call_id)
            comparison = (
                "tie"
                if judged.preferred_image == "tie"
                else "current"
                if judged.preferred_image == ("A" if swap else "B")
                else "previous"
            )
            change = visual_change(
                store, project, previous.inspection.full_asset_id, inspection.full_asset_id
            )
    verdicts = [execution.verdict] + [a.verdict for a in (artistic, fidelity) if a]
    priority = {v: i for i, v in enumerate(m.CriticVerdict)}
    verdict = max(verdicts, key=lambda v: priority[v])
    if not with_visual_critics and verdict == m.CriticVerdict.ACCEPT:
        verdict = m.CriticVerdict.REVISE
    prior_comparisons = [
        getattr(r, "comparative_preference", None)
        for r in history
        if r.execution.verdict == m.CriticVerdict.ACCEPT
    ]
    stalled = execution.verdict == m.CriticVerdict.ACCEPT and stagnated(
        [v for v in prior_comparisons + [comparison] if v], cfg["stagnation_window"]
    )
    if stalled:
        verdict = m.CriticVerdict.RECONCEPT
    decision = m.ReviewDecision(
        verdict=verdict,
        execution_findings=execution.findings,
        artistic_findings=artistic.findings if artistic else [],
        concept_fidelity_findings=fidelity.findings if fidelity else [],
        rule_break_evaluations=artistic.rule_break_evaluations if artistic else [],
        target_edit_instructions="; ".join(
            f.actionable_fix for a in (execution, artistic, fidelity) if a for f in a.findings
        )
        or ("Visual critics still required." if not with_visual_critics else None),
        stagnation_detected=stalled,
    )
    result = CreativeReview(
        id=record_id,
        project_id=project,
        concept_id=compiled.id,
        run_id=context.run_id,
        scene_id=version.scene_id,
        scene_version=version.version,
        inspection=inspection,
        execution=execution,
        artistic=artistic,
        fidelity=fidelity,
        decision=decision,
        model_call_ids=calls,
        visual_change_from_previous=change,
        comparative_preference=comparison,
    )
    event = m.WorkflowEvent(
        event_id=record_id,
        project_id=project,
        run_id=context.run_id,
        spread_id=version.scene_id,
        timestamp=utcnow(),
        payload=m.DecisionEvent(decision_id=result.id, verdict=decision.verdict),
    )
    store.put_records(
        ("creative_review", result.id, project, result), ("event", event.event_id, project, event)
    )
    return result
