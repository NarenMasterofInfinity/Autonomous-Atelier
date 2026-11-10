import base64

import pytest
from PIL import Image

from editorial_studio.art_direction.service import build_identity, review_identity
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import compile_concept, story_sources
from editorial_studio.creative.critics import stagnated
from editorial_studio.creative.identity import (
    approve_final_identity,
    package_identity,
)
from editorial_studio.creative.models import (
    CompiledConcept,
    ConceptProposal,
    ConceptTypography,
    CreativeReview,
    CriticAssessment,
    NodeTreatment,
    TextRange,
)
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.llm.contracts import ProviderResult
from editorial_studio.llm.gateway import Gateway
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story, png
from editorial_studio.spatial.proofs import build_capability_proofs


@pytest.fixture
def creative_inputs(store, context):
    identity = build_identity(store, context.model_copy(update={"run_id": "identity"}), dpi=72)
    photo = PhotoInput(
        filename="source.png",
        data_base64=base64.b64encode(png(Image.new("RGB", (256, 256), "#9e8470"))).decode(),
        source_uri="fixture:creative",
        credit="Original fixture",
    )
    story = ingest_story(
        store,
        context,
        StoryInput(
            id="creative-source",
            title="The shape of quiet",
            deck="A story about the space around familiar things.",
            body="A room changes as the light moves across it. A chair, a doorway, and a cup each offer a different beginning. The editor follows these small changes and gives each one enough space to be seen.",
            author="Fixture",
            photos=[photo],
        ),
    )
    return identity, story


def proposal_for(store, context, identity, story, alternate=False):
    from editorial_studio.creative.compiler import photo_sources

    source = {role: d for role, d in story_sources(store, "project", story)}
    regions = {
        "headline": (0.05, 0.12, 0.43, 0.2),
        "deck": (0.54, 0.10, 0.40, 0.14),
        "body": (0.54, 0.40, 0.40, 0.48),
        "photo": (0.05, 0.40, 0.43, 0.48),
    }
    if alternate:
        regions = {
            "headline": (0.54, 0.10, 0.40, 0.24),
            "deck": (0.05, 0.35, 0.40, 0.15),
            "body": (0.05, 0.51, 0.40, 0.4),
            "photo": (0.54, 0.42, 0.40, 0.50),
        }
    nodes = []
    treatments = []
    for role in ("headline", "deck", "body"):
        r = regions[role]
        nodes.append(
            m.ConceptNode(
                id=role,
                role="text",
                derived_text_id=source[role].id,
                target_region=m.NormalizedRegion(x=r[0], y=r[1], width=r[2], height=r[3]),
                z_order_hint=2,
            )
        )
        treatments.append(NodeTreatment(node_id=role, style_role=role))
    r = regions["photo"]
    nodes.append(
        m.ConceptNode(
            id="photo",
            role="image",
            source_asset_id=photo_sources(store, "project", story)[0],
            target_region=m.NormalizedRegion(x=r[0], y=r[1], width=r[2], height=r[3]),
            z_order_hint=0,
        )
    )
    treatments.append(NodeTreatment(node_id="photo", image_treatment="grain"))
    return ConceptProposal(
        visual_metaphor="Light describes a pause.",
        compositional_structure="Asymmetric image and reading regions.",
        photography_treatment="Deliberate grain for a small-source study.",
        narrative_expression="Separate the first glance from the slower reading.",
        graph=m.SpatialConceptGraph(nodes=nodes, relationships=[]),
        treatments=treatments,
        spatial_intent=m.SpatialIntent(mode="guided"),
    )


def accepted():
    return CriticAssessment(
        verdict="ACCEPT",
        score=0.8,
        findings=[],
        rationale="Independent fixture verdict; no human approval.",
    )


def test_source_frames_partition_exactly_and_reject_gaps_overlaps_and_foreign_ranges(
    store, context, creative_inputs
):
    from editorial_studio.creative.compiler import source_partitions

    identity, story = creative_inputs
    proposal = proposal_for(store, context, identity, story)
    title = next(t for t in proposal.treatments if t.node_id == "headline")
    title.text_range = TextRange(start_char=0, end_char=9)
    for start in (8, 10):
        bad = proposal.model_copy(deep=True)
        bad.graph.nodes.append(bad.graph.nodes[0].model_copy(update={"id": "rest"}))
        bad.treatments.append(
            NodeTreatment(
                node_id="rest",
                style_role="headline",
                text_range=TextRange(start_char=start, end_char=18),
            )
        )
        with pytest.raises(ValueError, match="every source character"):
            source_partitions(store, context.project_id, story, bad)
    proposal.treatments[-1].text_range = TextRange(start_char=0, end_char=1)
    with pytest.raises(ValueError, match="text node"):
        source_partitions(store, context.project_id, story, proposal)


def test_split_source_frames_render_with_frozen_styles_and_complete_coverage(
    store, context, creative_inputs, pricing, provider_factory
):
    from editorial_studio.canvas.models import CanvasDocument
    from editorial_studio.design_system.models import PairingCatalog
    from editorial_studio.design_system.system import DesignSystem

    identity, story = creative_inputs
    proposal = proposal_for(store, context, identity, story)
    system = DesignSystem(
        tokens=identity.tokens, pairing_catalog=PairingCatalog(pairings=[identity.pairing])
    )
    proposal.typography = ConceptTypography.from_configuration(system.typography(identity.bible))
    custom = proposal.typography.styles[0].model_copy(
        update={"name": "display-fragment", "font_size_pt": 24}
    )
    proposal.typography.styles.append(custom)
    title = next(t for t in proposal.treatments if t.node_id == "headline")
    title.style_name = custom.name
    title.text_range = TextRange(start_char=0, end_char=9)
    rest = proposal.graph.nodes[0].model_copy(
        update={
            "id": "rest",
            "target_region": m.NormalizedRegion(x=0.05, y=0.30, width=0.43, height=0.10),
        }
    )
    proposal.graph.nodes.append(rest)
    proposal.treatments.append(
        NodeTreatment(
            node_id="rest",
            style_role="headline",
            style_name=custom.name,
            text_range=TextRange(start_char=9, end_char=18),
        )
    )
    provider = provider_factory([])
    spread = build_creative_spread(
        Gateway(store, provider, pricing),
        context,
        story.id,
        identity.id,
        proposal=proposal,
        with_visual_critics=False,
    )
    document = CanvasDocument.model_validate_json(
        store.read_blob(context.project_id, spread.document_asset_id)
    )
    layers = {layer.id: layer for layer in document.scene.layers}
    assert layers["headline"].text_content + layers["rest"].text_content == "The shape of quiet"
    assert layers["headline"].derived_text_id != layers["rest"].derived_text_id
    assert document.typography == proposal.typography.freeze()
    assert provider.calls == 0
    assert (
        not ProvenanceLedger(store, context.project_id)
        .coverage(story.title_block_id)
        .unassigned_ranges
    )
    review = store.get("creative_review", spread.review_id, CreativeReview)
    assert review.execution.verdict == m.CriticVerdict.ACCEPT
    assert all(f.category != "source_coverage" for f in review.execution.findings)
    changed = proposal.model_copy(deep=True)
    changed.visual_metaphor = "A different authored direction"
    with pytest.raises(ValueError, match="different proposal"):
        build_creative_spread(
            Gateway(store, provider, pricing),
            context,
            story.id,
            identity.id,
            proposal=changed,
            with_visual_critics=False,
        )


def test_concept_schema_keeps_font_axes_closed_and_freezes_legacy_font_maps():
    from editorial_studio.canvas.typography.fonts import FontConfiguration, FontRegistry
    from editorial_studio.llm.schema import strict_schema

    schema = strict_schema(ConceptProposal)

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
                assert set(value.get("required", [])) == set(value.get("properties", {}))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    original = FontRegistry().config
    typed = ConceptTypography.from_configuration(original)
    assert typed.freeze() == original
    # Early authored snapshots stored the renderer's axis maps. They remain
    # readable while model-facing schemas use a closed list of typed settings.
    assert ConceptTypography.model_validate(original.model_dump()).freeze() == original
    assert isinstance(typed.freeze(), FontConfiguration)


def test_compiler_rejects_unknown_styles_and_small_reading_type(store, context, creative_inputs):
    identity, story = creative_inputs
    proposal = proposal_for(store, context, identity, story)
    proposal.treatments[0].style_name = "unregistered"
    with pytest.raises(ValueError, match="unknown frozen style"):
        compile_concept(store, context, story, identity, proposal, concept_id="unknown-style")
    proposal.treatments[0].style_name = identity.bible.id + ".caption"
    proposal.treatments[2].style_name = identity.bible.id + ".caption"
    with pytest.raises(ValueError, match="reading floor"):
        compile_concept(store, context, story, identity, proposal, concept_id="small-body")


def test_gradient_cannot_mutate_a_different_concept_node():
    with pytest.raises(ValueError, match="own concept node"):
        NodeTreatment(
            node_id="photo",
            gradient=m.GradientMaskOp(
                target_layer_id="other",
                gradient_type="linear",
                start=m.PointMM(x_mm=0, y_mm=0),
                end=m.PointMM(x_mm=10, y_mm=0),
                stops=[m.GradientStop(offset=0, opacity=1), m.GradientStop(offset=1, opacity=0)],
            ),
        )


def test_compiler_rejects_missing_source_unknown_asset_and_depth_cycle(
    store, context, creative_inputs
):
    identity, story = creative_inputs
    proposal = proposal_for(store, context, identity, story)
    bad = proposal.model_copy(deep=True)
    bad.graph.nodes[0].derived_text_id = "invented"
    with pytest.raises(ValueError, match="every source"):
        compile_concept(store, context, story, identity, bad, concept_id="bad")
    bad = proposal.model_copy(deep=True)
    bad.graph.nodes[-1].source_asset_id = "invented"
    with pytest.raises(ValueError, match="outside"):
        compile_concept(store, context, story, identity, bad, concept_id="bad2")
    bad = proposal.model_copy(deep=True)
    bad.graph.relationships = [
        m.ConceptRelationship(
            source_id="headline", target_id="photo", relation="behind", rationale="Depth"
        ),
        m.ConceptRelationship(
            source_id="photo", target_id="headline", relation="behind", rationale="Contradiction"
        ),
    ]
    with pytest.raises(ValueError, match="cycle"):
        compile_concept(store, context, story, identity, bad, concept_id="bad3")


def test_full_typed_pipeline_and_two_visual_critics_bind_exact_source(
    store, context, creative_inputs, pricing, provider_factory
):
    identity, story = creative_inputs
    proposal = proposal_for(store, context, identity, story)
    provider = provider_factory(
        [
            ProviderResult(visible_text=proposal.model_dump_json()),
            ProviderResult(visible_text=accepted().model_dump_json()),
            ProviderResult(visible_text=accepted().model_dump_json()),
        ]
    )
    gateway = Gateway(store, provider, pricing)
    spread = build_creative_spread(gateway, context, story.id, identity.id)
    assert spread.state == "approved_for_identity_review" and provider.calls == 3
    review = store.get("creative_review", spread.review_id, CreativeReview)
    assert (
        review.execution.verdict == m.CriticVerdict.ACCEPT
        and review.artistic
        and review.fidelity
        and not review.human_approval
    )
    compiled = store.get("concept", spread.concept_id, CompiledConcept)
    assert compiled.hybrid.sketch.asset_id and not compiled.compiler.unsupported_features
    assert compiled.recipe.operations and compiled.recipe.dependency_order
    for block in [story.title_block_id, story.deck_block_id, story.body_block_id]:
        assert not ProvenanceLedger(store, "project").coverage(block).unassigned_ranges
    assert (
        build_creative_spread(gateway, context, story.id, identity.id) == spread
        and provider.calls == 3
    )


def test_local_only_review_never_approves_artistry_and_recovery_does_not_rerender(
    store, context, creative_inputs, pricing, provider_factory, monkeypatch
):
    identity, story = creative_inputs
    proposal = proposal_for(store, context, identity, story)
    provider = provider_factory([])
    gateway = Gateway(store, provider, pricing)
    import editorial_studio.creative.service as service

    original = service.review_spread

    def crash(*args, **kwargs):
        raise RuntimeError("interruption after scene commit")

    monkeypatch.setattr(service, "review_spread", crash)
    with pytest.raises(RuntimeError):
        build_creative_spread(
            gateway, context, story.id, identity.id, proposal=proposal, with_visual_critics=False
        )
    before = SceneRepository(store, "project").head("run-a0")
    monkeypatch.setattr(service, "review_spread", original)
    from editorial_studio.canvas.executor import Executor

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected rerender")

    monkeypatch.setattr(Executor, "apply", forbidden)
    spread = build_creative_spread(
        gateway, context, story.id, identity.id, proposal=proposal, with_visual_critics=False
    )
    assert (
        spread.scene_version == before.version
        and spread.state == "revision_required"
        and provider.calls == 0
    )


def test_comparative_stagnation_uses_preferences_not_artistic_scores():
    assert not stagnated(["tie", "previous"])
    assert stagnated(["tie", "previous", "tie"])
    assert not stagnated(["tie", "previous", "current"])


def test_final_identity_requires_human_two_stage_review_and_exact_proofs(
    store, context, creative_inputs, pricing, provider_factory
):
    identity, story = creative_inputs
    gateway = Gateway(
        store,
        provider_factory(
            [ProviderResult(visible_text=accepted().model_dump_json()) for _ in range(4)]
        ),
        pricing,
    )
    first = build_creative_spread(
        gateway,
        context.model_copy(update={"run_id": "first"}),
        story.id,
        identity.id,
        proposal=proposal_for(store, context, identity, story),
    )
    second = build_creative_spread(
        gateway,
        context.model_copy(update={"run_id": "second"}),
        story.id,
        identity.id,
        proposal=proposal_for(store, context, identity, story, True),
    )
    caps = build_capability_proofs(store, context.model_copy(update={"run_id": "caps"}), dpi=72)
    package_context = context.model_copy(update={"run_id": "final-package"})
    package = package_identity(
        store, package_context, identity.id, [first.id, second.id], [p.id for p in caps]
    )
    assert package.bible.approval_state == "provisional" and package.review_verdict is None
    with pytest.raises(ValueError, match="provisional identity approval"):
        approve_final_identity(
            store,
            context,
            package.id,
            expected_revision=0,
            actor="Test reviewer",
            note="Fixture review",
            verdict="approved",
            reviewed_techniques=True,
        )
    review_identity(
        store,
        context.model_copy(update={"run_id": "provisional-review"}),
        identity.id,
        expected_revision=0,
        actor="Test reviewer",
        verdict="approved",
        note="Fixture baseline review",
    )
    with pytest.raises(ValueError, match="technique contact sheet"):
        approve_final_identity(
            store,
            context,
            package.id,
            expected_revision=0,
            actor="Test reviewer",
            note="Fixture review",
            verdict="approved",
            reviewed_techniques=False,
        )
    from editorial_studio.art_direction.models import ProvisionalIdentity

    source_identity = store.get("identity", identity.id, ProvisionalIdentity)
    changed = source_identity.model_copy(deep=True)
    changed.bible.conceptual_identity = "A different publication direction."
    store.put_records(("identity", identity.id, "project", changed))
    with pytest.raises(ValueError, match="identity snapshot changed"):
        approve_final_identity(
            store,
            context,
            package.id,
            expected_revision=0,
            actor="Reviewer",
            note="Stale direction.",
            verdict="approved",
            reviewed_techniques=True,
        )
    store.put_records(("identity", identity.id, "project", source_identity))
    with pytest.raises(PermissionError):
        package_identity(
            store, package_context, identity.id, [second.id, first.id], [p.id for p in caps]
        )
    approved = approve_final_identity(
        store,
        context.model_copy(update={"run_id": "final-review"}),
        package.id,
        expected_revision=0,
        actor="Test reviewer",
        note="Fixture review, all rendered proofs inspected.",
        verdict="approved",
        reviewed_techniques=True,
    )
    assert approved.bible.approval_state == "final" and approved.review_actor == "Test reviewer"
    # A second reviewed package owns the canonical publication even if an earlier one is revoked.
    other = package_identity(
        store,
        context.model_copy(update={"run_id": "second-package"}),
        identity.id,
        [first.id, second.id],
        [p.id for p in caps],
    )
    approve_final_identity(
        store,
        context.model_copy(update={"run_id": "second-package-review"}),
        other.id,
        expected_revision=0,
        actor="Second reviewer",
        note="Reviewed the same immutable proof set as a separate publication.",
        verdict="approved",
        reviewed_techniques=True,
    )
    approve_final_identity(
        store,
        context.model_copy(update={"run_id": "revoke-first"}),
        package.id,
        expected_revision=1,
        actor="Test reviewer",
        note="Superseded by the second reviewed package.",
        verdict="revision_required",
        reviewed_techniques=False,
    )
    from editorial_studio.creative.evidence import FinalBiblePublication

    publication = store.get("final_bible_publication", identity.bible.id, FinalBiblePublication)
    assert publication.package_id == other.id and publication.bible.approval_state == "final"

    with pytest.raises(ValueError, match="stale"):
        approve_final_identity(
            store,
            context,
            package.id,
            expected_revision=0,
            actor="Test reviewer",
            note="Old review",
            verdict="approved",
            reviewed_techniques=True,
        )


def test_dynamic_recipe_dependencies_and_incompatible_text_modes():
    from editorial_studio.contracts.operation_registry import REGISTRY
    from editorial_studio.creative.recipes import DynamicRecipeGenerator, RecipeModule

    generator = DynamicRecipeGenerator()
    op = m.SetOpacityOp(layer_id="photo", opacity=0.7)
    first = RecipeModule(id="a", skill_id="opacity", operations=[op], depends_on=["b"])
    second = RecipeModule(id="b", skill_id="opacity", operations=[op], depends_on=["a"])
    with pytest.raises(ValueError, match="cycle"):
        generator.generate(
            "cycle",
            [first, second],
            supported_operations=set(REGISTRY),
            capability_ids=[],
            rationale="Fixture",
        )
    first.depends_on = []
    first.incompatible_skill_ids = ["blend"]
    second.skill_id = "blend"
    second.depends_on = []
    with pytest.raises(ValueError, match="incompatible"):
        generator.generate(
            "bad",
            [first, second],
            supported_operations=set(REGISTRY),
            capability_ids=[],
            rationale="Fixture",
        )


def test_critic_revision_requires_explicit_human_override(
    store, context, creative_inputs, pricing, provider_factory
):
    identity, story = creative_inputs
    revise = CriticAssessment(
        verdict="REVISE",
        score=0.5,
        findings=[
            m.CritiqueFinding(
                category="hierarchy",
                severity="MEDIUM",
                description="The opening needs more tension.",
                actionable_fix="Reconsider the image/type relationship.",
            )
        ],
        rationale="Fixture artistic revision.",
    )
    provider = provider_factory(
        [
            ProviderResult(visible_text=assessment.model_dump_json())
            for assessment in (revise, accepted(), revise, accepted())
        ]
    )
    gateway = Gateway(store, provider, pricing)
    first = build_creative_spread(
        gateway,
        context.model_copy(update={"run_id": "override-a"}),
        story.id,
        identity.id,
        proposal=proposal_for(store, context, identity, story),
    )
    second = build_creative_spread(
        gateway,
        context.model_copy(update={"run_id": "override-b"}),
        story.id,
        identity.id,
        proposal=proposal_for(store, context, identity, story, True),
    )
    caps = build_capability_proofs(
        store, context.model_copy(update={"run_id": "override-caps"}), dpi=72
    )
    package = package_identity(
        store,
        context.model_copy(update={"run_id": "override-package"}),
        identity.id,
        [first.id, second.id],
        [p.id for p in caps],
    )
    assert package.requires_critic_override and package.review_verdict is None
    review_identity(
        store,
        context.model_copy(update={"run_id": "baseline-approval"}),
        identity.id,
        expected_revision=0,
        actor="QA reviewer",
        note="Fixture baseline approval.",
        verdict="approved",
    )
    with pytest.raises(ValueError, match="explicit override"):
        approve_final_identity(
            store,
            context,
            package.id,
            expected_revision=0,
            actor="QA reviewer",
            note="Fixture artistic review.",
            verdict="approved",
            reviewed_techniques=True,
        )
    approved = approve_final_identity(
        store,
        context,
        package.id,
        expected_revision=0,
        actor="QA reviewer",
        note="Fixture: retained the quieter hierarchy deliberately after inspecting all proofs.",
        verdict="approved",
        reviewed_techniques=True,
        override_critic_recommendations=True,
    )
    assert approved.critic_override_recorded and approved.bible.approval_state == "final"


def test_creative_ui_only_queues_a_typed_job(store, context, creative_inputs):
    from streamlit.testing.v1 import AppTest

    from editorial_studio.core.jobs import BuildCreativeSpreadCommand, Queue

    source = f"""
import editorial_studio.app as app
from editorial_studio.settings import Settings
from pathlib import Path
app.load_settings=lambda:Settings(data_root=Path({str(store.root)!r}))
app.main()
"""
    app = AppTest.from_string(source, default_timeout=20).run()
    app.sidebar.text_input[0].set_value("project").run()
    assert not app.exception
    next(
        button for button in app.button if button.label == "Queue creative composition"
    ).click().run()
    assert not app.exception
    jobs = Queue(store).list("project")
    assert (
        len(jobs) == 1
        and isinstance(jobs[0].command.payload, BuildCreativeSpreadCommand)
        and jobs[0].status == "queued"
    )
