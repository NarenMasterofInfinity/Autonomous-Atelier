import base64

import pytest
from PIL import Image
from test_m8_tournament import inputs as inputs
from test_m8_tournament import proposal
from test_m9_issue import issue_inputs as issue_inputs

from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.typography.fonts import FontConfiguration, TypeStyle
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import utcnow
from editorial_studio.creative.compiler import source_partitions, story_sources
from editorial_studio.creative.models import CompiledConcept
from editorial_studio.creative.service import build_creative_spread
from editorial_studio.llm.gateway import Gateway
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story, png
from editorial_studio.reference_studio.fitting import fit_program
from editorial_studio.reference_studio.models import AuthoredReference, EditorialFamily
from editorial_studio.reference_studio.programs import capture_program
from editorial_studio.reference_studio.quality import analyze_layout
from editorial_studio.reference_studio.service import build_compositions


class Offline:
    namespace = "offline-program-test"

    def execute(self, *args):
        raise AssertionError("Program fitting must not call a provider")


@pytest.fixture
def authored(store, context, inputs, pricing):
    identity, story = inputs
    gateway = Gateway(store, Offline(), pricing)
    ctx = context.model_copy(update={"run_id": "authored-reference"})
    spread = build_creative_spread(
        gateway,
        ctx,
        story.id,
        identity.id,
        proposal=proposal(store, context, story, 0),
        with_visual_critics=False,
    )
    family = EditorialFamily(
        id="test-family",
        version=1,
        name="Test",
        principle="Photo and title",
        reference_ids=["test-external"],
        capability_ids=[],
        suitability=["short title"],
        composition_rules=["Keep a readable hierarchy"],
    )
    ref = AuthoredReference(
        id="authored-proof",
        project_id=context.project_id,
        family_id=family.id,
        family_version=1,
        title="Test reference",
        story_id=story.id,
        spread=spread,
        brief=family.principle,
        reference_ids=family.reference_ids,
        family_snapshot_json=family.model_dump_json(),
    )
    store.put_records(("authored_reference", ref.id, context.project_id, ref))
    return gateway, identity, story, ref


def changed_story(store, context, story, *, body=None):
    sources = dict(story_sources(store, context.project_id, story))
    return ingest_story(
        store,
        context,
        StoryInput(
            id="changed",
            title="An ordinary moment",
            deck=sources["deck"].text,
            body=body or sources["body"].text,
            author="Original test variation",
            photos=[
                PhotoInput(
                    filename="same-selected-photo.png",
                    data_base64=base64.b64encode(
                        png(Image.new("RGB", (256, 256), "#bcae92"))
                    ).decode(),
                    source_uri="fixture:original",
                    credit="Original fixture",
                )
            ],
        ),
    )


def test_capture_removes_story_inputs_and_preserves_native_design(store, context, authored):
    _, identity, story, ref = authored
    program = capture_program(store, ref)
    assert program.characteristics.layer_order
    assert program.characteristics.source_metrics["display_ink_fraction"] > 0
    assert all(
        n.derived_text_id is None or n.derived_text_id.startswith("input-")
        for n in program.proposal.graph.nodes
    )
    assert all(
        n.source_asset_id is None or n.source_asset_id.startswith("input-")
        for n in program.proposal.graph.nodes
    )
    new = changed_story(store, context, story)
    adapted, ratio = fit_program(store, context.project_id, new, program)
    placements = source_partitions(store, context.project_id, new, adapted)
    assert placements and 0.72 <= ratio <= 1.08
    original = {n.id: n.target_region for n in program.proposal.graph.nodes}
    assert all(n.target_region == original[n.id] for n in adapted.graph.nodes)
    assert {n.derived_text_id for n in adapted.graph.nodes if n.role == "text"} == {
        d.id for _, d in story_sources(store, context.project_id, new)
    }


def test_program_service_replay_and_rejects_infeasible_body_without_shrinking(
    store, context, authored
):
    gateway, identity, story, ref = authored
    ctx = context.model_copy(update={"run_id": "program-adaptation"})
    result = build_compositions(
        gateway, ctx, story.id, identity.id, [ref.id], origin=context.project_id
    )
    assert result.state == "ready_for_visual_review" and result.selected_program_id
    assert not result.human_approval
    assert (
        build_compositions(gateway, ctx, story.id, identity.id, [ref.id], origin=context.project_id)
        == result
    )
    c = store.get("concept", result.candidates[0].spread.concept_id, CompiledConcept)
    assert c.authorship == "reference_adapted" and c.reference_program_id
    with pytest.raises(ValueError, match="different selection settings"):
        build_compositions(
            gateway,
            ctx,
            story.id,
            identity.id,
            [ref.id],
            origin=context.project_id,
            art_director=True,
        )
    huge = changed_story(
        store, context, story, body="This copy cannot fit its reading frame. " * 500
    )
    rejected = build_compositions(
        gateway,
        context.model_copy(update={"run_id": "too-long"}),
        huge.id,
        identity.id,
        [ref.id],
        origin=context.project_id,
    )
    assert rejected.state == "no_admissible_candidate" and rejected.selected_program_id is None
    assert rejected.proof_book_asset_id is None and rejected.rejections


def test_visibility_detects_a_hidden_word_and_collision_using_real_raster(store):
    from editorial_studio.canvas.typography.fonts import FontRegistry

    cfg = FontConfiguration(
        fonts=FontRegistry().config.fonts,
        styles=[
            TypeStyle(
                name="headline",
                font_id="DejaVuSans",
                font_size_pt=60,
                color="#222222",
                min_paragraph_lines=1,
            )
        ],
    )
    title = m.TextLayer(
        id="headline",
        name="Headline",
        semantic_role="headline",
        z_index=0,
        bounds=m.BoundsMM(x_mm=20, y_mm=20, width_mm=370, height_mm=65),
        text_content="VISIBLE HIDDEN",
        style_name="headline",
    )
    cover = store.put_blob("project", png(Image.new("RGB", (20, 20), "#eeeeee")), "image/png")
    image = m.ImageLayer(
        id="cover",
        name="Opaque occluder",
        semantic_role="photo",
        z_index=2,
        bounds=m.BoundsMM(x_mm=110, y_mm=15, width_mm=200, height_mm=80),
        asset_id=cover.id,
    )
    scene = m.Scene(
        id="visibility",
        spread_id="visibility",
        version="initial",
        width_mm=420,
        height_mm=297,
        design_language_id="test",
        created_at=utcnow(),
        layers=[title, image],
    )
    document = CanvasDocument.from_scene(scene)
    document.typography = cfg
    document.background_color = "#eeeeee"
    from editorial_studio.creative.models import ConceptProposal, NodeTreatment

    plan = ConceptProposal(
        visual_metaphor="test",
        compositional_structure="test",
        photography_treatment="test",
        narrative_expression="test",
        graph=m.SpatialConceptGraph(
            nodes=[
                m.ConceptNode(
                    id="headline",
                    role="text",
                    derived_text_id="test",
                    target_region=m.NormalizedRegion(x=0.05, y=0.05, width=0.9, height=0.3),
                    z_order_hint=0,
                ),
                m.ConceptNode(
                    id="cover",
                    role="image",
                    source_asset_id=cover.id,
                    target_region=m.NormalizedRegion(x=0.3, y=0.05, width=0.4, height=0.3),
                    z_order_hint=1,
                ),
            ],
            relationships=[],
        ),
        treatments=[
            NodeTreatment(node_id="headline", style_role="headline"),
            NodeTreatment(node_id="cover"),
        ],
        spatial_intent=m.SpatialIntent(mode="guided"),
    )
    q = analyze_layout(store, "project", document, plan, dpi=48)
    assert not q.passed and any(f.code == "hidden_word" for f in q.findings)
    image.visible = False
    second = title.model_copy(update={"id": "second", "z_index": 3})
    document.scene.layers.append(second)
    from editorial_studio.canvas.models import LayerPresentation

    document.presentations.append(
        LayerPresentation(layer_id=second.id, source_bounds=second.bounds)
    )
    q = analyze_layout(store, "project", document, plan, dpi=48)
    assert any(f.code == "text_collision" for f in q.findings)


def test_capture_refuses_cross_project_evidence(store, context, authored):
    gateway, identity, story, ref = authored
    with pytest.raises(PermissionError, match="outside selected source"):
        build_compositions(
            gateway,
            context.model_copy(update={"run_id": "bad-scope"}),
            story.id,
            identity.id,
            [ref.id],
            origin="wrong-project",
        )


def test_title_line_rhythm_is_a_constraint_not_just_box_containment(store, context, authored):
    _, _, story, ref = authored
    program = capture_program(store, ref)
    title = next(s for s in program.slots if s.role == "headline")
    node = next(n for n in program.proposal.graph.nodes if n.id == title.node_id)
    node.target_region.width = 0.13
    node.target_region.height = 0.4
    title.display_line_count = 1
    with pytest.raises(ValueError, match="headline cannot fit"):
        fit_program(store, context.project_id, story, program)
    title.display_line_count = None
    adapted, _ = fit_program(store, context.project_id, story, program)
    assert source_partitions(store, context.project_id, story, adapted)


def test_photo_filled_letters_are_visible_even_when_source_text_is_transparent(
    store, context, inputs, pricing
):
    identity, story = inputs
    plan = proposal(store, context, story, 0)
    headline = next(n for n in plan.graph.nodes if n.id == "headline")
    image = next(n for n in plan.graph.nodes if n.id == "photo")
    image.target_region = headline.target_region.model_copy()
    next(t for t in plan.treatments if t.node_id == "headline").opacity = 0
    plan.graph.relationships.append(
        m.ConceptRelationship(
            source_id="photo",
            target_id="headline",
            relation="clips_to",
            rationale="The real photograph fills the source-bound glyphs",
        )
    )
    gateway = Gateway(store, Offline(), pricing)
    spread = build_creative_spread(
        gateway,
        context.model_copy(update={"run_id": "photo-lettering"}),
        story.id,
        identity.id,
        proposal=plan,
        with_visual_critics=False,
    )
    doc = CanvasDocument.model_validate_json(
        store.read_blob(context.project_id, spread.document_asset_id)
    )
    compiled = store.get("concept", spread.concept_id, CompiledConcept)
    quality = analyze_layout(store, context.project_id, doc, compiled.proposal, dpi=48)
    assert not any(
        f.code in ("hidden_text", "hidden_word") and "headline" in f.layers
        for f in quality.findings
    )


def test_multiple_letter_windows_share_the_same_native_photo_plane(store, context, authored):
    _, _, story, ref = authored
    program = capture_program(store, ref)
    image = next(n for n in program.proposal.graph.nodes if n.role == "image")
    other = image.model_copy(deep=True, update={"id": "photo-other"})
    other.target_region = other.target_region.model_copy(
        update={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.5}
    )
    program.proposal.graph.nodes.append(other)
    treatment = next(t for t in program.proposal.treatments if t.node_id == image.id)
    program.proposal.treatments.append(treatment.model_copy(update={"node_id": other.id}))
    slot = next(s for s in program.slots if s.node_id == image.id)
    program.slots.append(slot.model_copy(update={"node_id": other.id}))
    program.photo_fill_groups = [[image.id, other.id]]
    source = dict(story_sources(store, context.project_id, story))
    target = ingest_story(
        store,
        context,
        StoryInput(
            id="high-resolution-copy",
            title=source["headline"].text,
            deck=source["deck"].text,
            body=source["body"].text,
            author="Original high resolution fixture",
            photos=[
                PhotoInput(
                    filename="photo.png",
                    data_base64=base64.b64encode(
                        png(Image.new("RGB", (2000, 2000), "#bcae92"))
                    ).decode(),
                    source_uri="fixture:original",
                    credit="Original fixture",
                )
            ],
        ),
    )
    adapted, _ = fit_program(store, context.project_id, target, program)
    fields = [n for n in adapted.graph.nodes if n.id in program.photo_fill_groups[0]]
    assert fields[0].target_region == fields[1].target_region
    assert fields[0].source_asset_id == fields[1].source_asset_id


def test_reference_composition_form_queues_without_provider_calls(store, authored):
    from streamlit.testing.v1 import AppTest

    from editorial_studio.core.jobs import BuildReferenceCompositionCommand, Queue

    gateway, identity, story, _ = authored
    source = f"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import editorial_studio.app as app
import editorial_studio.ui.reference_composition as reference_ui
from editorial_studio.settings import Settings
app.load_settings=lambda:Settings(data_root=Path({str(store.root)!r}))
with patch.object(reference_ui,"references",lambda store:[SimpleNamespace(id="reference-1",design_id="01",title="Reference",status="authored_for_review")]):
    app.main()
"""
    app = AppTest.from_string(source, default_timeout=20).run()
    app.sidebar.text_input[0].set_value(story.project_id).run()
    next(b for b in app.button if b.label == "Queue reference composition").click().run()
    assert not app.exception
    jobs = Queue(store).list(story.project_id)
    assert len(jobs) == 1
    command = jobs[0].command.payload
    assert isinstance(command, BuildReferenceCompositionCommand)
    assert command.story_id == story.id and command.identity_id == identity.id
    assert command.reference_ids == ["reference-1"] and command.art_director
    app.run()
    assert len(Queue(store).list(story.project_id)) == 1


def test_issue_preserves_admitted_program_pages_and_native_recheck(
    store, context, authored, issue_inputs, pricing
):
    from test_m9_issue import IssueProvider

    from editorial_studio.creative.issue import build_issue, revise_issue
    from editorial_studio.creative.issue_models import IssueCorrection
    from editorial_studio.reference_studio.models import ReferenceComposition

    local, _, _, reference = authored
    identity, stories = issue_inputs
    plan = proposal(store, context, stories[0], 0)
    next(t for t in plan.treatments if t.node_id == "photo").image_treatment = "native"
    spread = build_creative_spread(
        local,
        context.model_copy(update={"run_id": "issue-source-reference"}),
        stories[0].id,
        identity.id,
        proposal=plan,
        with_visual_critics=False,
    )
    reference = reference.model_copy(
        update={"id": "issue-reference", "story_id": stories[0].id, "spread": spread}
    )
    store.put_records(("authored_reference", reference.id, context.project_id, reference))
    provider = IssueProvider(store, context, stories)
    gateway = Gateway(store, provider, pricing)
    ctx = context.model_copy(update={"run_id": "issue-from-programs"})
    result = build_issue(
        gateway,
        ctx,
        [s.id for s in stories],
        identity.id,
        reference_ids=[reference.id],
        reference_project=context.project_id,
        reference_art_director=False,
    )
    assert provider.calls == 2 and provider.index == 0
    assert len(result.page_map.pages) == 12
    for index, entry in enumerate(result.spreads):
        assert entry.source == "reference_program"
        composition = store.get(
            "reference_composition", ctx.run_id + f"-reference-{index}", ReferenceComposition
        )
        selected = next(
            c for c in composition.candidates if c.program_id == composition.selected_program_id
        )
        assert entry.spread == selected.spread
        if entry.slot.phase == "cover":
            assert composition.page_role == "cover"
            compiled = store.get("concept", entry.spread.concept_id, CompiledConcept)
            for node in compiled.proposal.graph.nodes:
                treatment = next(t for t in compiled.proposal.treatments if t.node_id == node.id)
                if node.role == "text":
                    if treatment.style_role == "headline":
                        assert node.target_region.x >= 0.5
                    elif treatment.style_role in ("body", "deck"):
                        assert node.target_region.x + node.target_region.width <= 0.5
    revision = revise_issue(
        gateway,
        context.model_copy(update={"run_id": "program-issue-recheck"}),
        result.id,
        result.evidence_fingerprint,
        [
            IssueCorrection(
                slot_id=result.spreads[2].slot.id,
                instruction="Recheck native fit",
                regenerate=False,
            )
        ],
    )
    assert provider.calls == 3 and provider.index == 0
    assert all(
        new.spread == old.spread for new, old in zip(revision.spreads, result.spreads, strict=True)
    )


def test_issue_selection_varies_families_without_admitting_failed_candidates():
    from types import SimpleNamespace as Row

    from editorial_studio.reference_studio.issue_selection import select_sequence

    def candidate(key, family, passed=True):
        return Row(
            program_id=key, family_id=family, quality=Row(passed=passed), minimum_display_ratio=1
        )

    runs = [
        Row(
            selected_program_id="serif",
            candidates=[
                candidate("serif", "serif"),
                candidate("depth", "depth"),
                candidate("bad", "other", False),
            ],
        ),
        Row(
            selected_program_id="serif",
            candidates=[candidate("serif", "serif"), candidate("overlay", "overlay")],
        ),
        Row(selected_program_id="letter", candidates=[candidate("letter", "letter")]),
        Row(selected_program_id="reverse", candidates=[candidate("reverse", "reverse")]),
        Row(selected_program_id="serif", candidates=[candidate("serif", "serif")]),
        Row(selected_program_id="overlay", candidates=[candidate("overlay", "overlay")]),
    ]
    selected = select_sequence(runs)
    assert len({c.family_id for c in selected}) == 5
    assert selected[0].program_id == "depth"
    assert all(c.quality.passed for c in selected)
    assert all(a.family_id != b.family_id for a, b in zip(selected, selected[1:], strict=False))
    with pytest.raises(ValueError, match="Every issue slot"):
        select_sequence([Row(candidates=[candidate("failed", "unique", False)])])


def test_body_partition_prefers_complete_paragraphs_when_both_fit(store, context, authored):
    from editorial_studio.reference_studio.models import CompositionSlot

    _, _, story, reference = authored
    program = capture_program(store, reference)
    body = next(n for n in program.proposal.graph.nodes if n.id == "body")
    body.target_region = m.NormalizedRegion(x=22 / 420, y=0.5, width=88 / 420, height=0.4)
    program.proposal.graph.nodes.append(
        body.model_copy(
            update={
                "id": "body-second",
                "target_region": m.NormalizedRegion(x=112 / 420, y=0.5, width=88 / 420, height=0.4),
            }
        )
    )
    treatment = next(t for t in program.proposal.treatments if t.node_id == "body")
    program.proposal.treatments.append(treatment.model_copy(update={"node_id": "body-second"}))
    slot = next(s for s in program.slots if s.role == "body")
    slot.source_fraction = 0.5
    program.slots.append(
        CompositionSlot(node_id="body-second", role="body", source_order=1, source_fraction=0.5)
    )
    paragraphs = [
        "A launch photograph holds opposing movements in one frame. The vehicle rises while the plume spreads across the ground.",
        "Look again at the space around that movement. The sky gives the rising form its outline and the ground supplies a measure.",
    ]
    target = changed_story(store, context, story, body="\n\n".join(paragraphs))
    adapted, _ = fit_program(store, context.project_id, target, program)
    span = next(t.text_range for t in adapted.treatments if t.node_id == "body")
    assert span.end_char == len(paragraphs[0]) + 2
