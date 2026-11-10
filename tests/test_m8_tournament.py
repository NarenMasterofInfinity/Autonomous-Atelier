import base64

import pytest
from PIL import Image

from editorial_studio.art_direction.service import build_identity
from editorial_studio.contracts import models as m
from editorial_studio.creative.compiler import photo_sources, story_sources
from editorial_studio.creative.models import (
    ComparativeAssessment,
    ConceptProposal,
    CriticAssessment,
    NodeTreatment,
)
from editorial_studio.creative.tournament import build_tournament
from editorial_studio.creative.tournament_models import (
    ConceptDirection,
    ConceptDirections,
)
from editorial_studio.llm.contracts import ProviderResult
from editorial_studio.llm.gateway import Gateway
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story, png


@pytest.fixture
def inputs(store, context):
    identity = build_identity(store, context.model_copy(update={"run_id": "identity"}), dpi=72)
    story = ingest_story(
        store,
        context,
        StoryInput(
            id="story",
            title="The shape of quiet",
            deck="A study in familiar things.",
            body="A room changes with the light. The editor follows the edge of a table and the outline of a chair, looking for a place to begin.",
            author="Original test fixture",
            photos=[
                PhotoInput(
                    filename="photo.png",
                    data_base64=base64.b64encode(
                        png(Image.new("RGB", (256, 256), "#bcae92"))
                    ).decode(),
                    source_uri="fixture:original",
                    credit="Original fixture",
                )
            ],
        ),
    )
    return identity, story


def directions():
    return ConceptDirections(
        concepts=[
            ConceptDirection(
                name=f"Direction {i}",
                visual_metaphor=f"Metaphor {i}",
                photography_role="Observed material",
                narrative_expression=f"Narrative {i}",
            )
            for i in range(2)
        ]
    )


def proposal(store, context, story, index):
    layouts = [
        [
            (0.54, 0.05, 0.42, 0.23),
            (0.54, 0.30, 0.42, 0.12),
            (0.54, 0.48, 0.42, 0.4),
            (0.02, 0.05, 0.42, 0.8),
        ],
        [
            (0.04, 0.05, 0.42, 0.23),
            (0.04, 0.30, 0.42, 0.12),
            (0.04, 0.48, 0.42, 0.4),
            (0.54, 0.05, 0.42, 0.75),
        ],
        [
            (0.04, 0.05, 0.92, 0.23),
            (0.04, 0.30, 0.42, 0.12),
            (0.54, 0.30, 0.42, 0.28),
            (0.04, 0.60, 0.92, 0.35),
        ],
        [
            (0.04, 0.43, 0.42, 0.20),
            (0.54, 0.43, 0.42, 0.10),
            (0.54, 0.58, 0.42, 0.35),
            (0.04, 0.04, 0.92, 0.36),
        ],
        [
            (0.04, 0.04, 0.42, 0.22),
            (0.54, 0.05, 0.42, 0.12),
            (0.54, 0.30, 0.42, 0.63),
            (0.04, 0.35, 0.42, 0.60),
        ],
        [
            (0.36, 0.04, 0.60, 0.22),
            (0.54, 0.30, 0.42, 0.12),
            (0.54, 0.45, 0.42, 0.5),
            (0.04, 0.04, 0.28, 0.30),
        ],
    ]
    source = dict(story_sources(store, context.project_id, story))
    nodes = []
    treatments = []
    for i, role in enumerate(("headline", "deck", "body", "photo")):
        x, y, w, h = layouts[index][i]
        node = m.ConceptNode(
            id=role,
            role="image" if role == "photo" else "text",
            target_region=m.NormalizedRegion(x=x, y=y, width=w, height=h),
            z_order_hint=0 if role == "photo" else 2,
            source_asset_id=photo_sources(store, context.project_id, story)[0]
            if role == "photo"
            else None,
            derived_text_id=source[role].id if role != "photo" else None,
        )
        nodes.append(node)
        treatments.append(
            NodeTreatment(
                node_id=role,
                style_role=role if role != "photo" else "body",
                image_treatment="grain" if role == "photo" else "native",
            )
        )
    direction = directions().concepts[index // 3]
    return ConceptProposal(
        visual_metaphor=direction.visual_metaphor,
        narrative_expression=direction.narrative_expression,
        photography_treatment="Grain for low-resolution fixture",
        compositional_structure=f"Measured arrangement {index}",
        graph=m.SpatialConceptGraph(nodes=nodes, relationships=[]),
        treatments=treatments,
        spatial_intent=m.SpatialIntent(mode="guided"),
    )


class TournamentProvider:
    namespace = "m8-independent-fixture"

    def __init__(self, store, context, story):
        self.store, self.context, self.story = store, context, story
        self.calls = 0
        self.proposals = 0
        self.comparison_prompts = []

    def execute(self, request, progress):
        self.calls += 1
        name = request.output_contract.rsplit(".", 1)[-1]
        if name == "ConceptDirections":
            output = directions()
        elif name == "ConceptProposal":
            output = proposal(self.store, self.context, self.story, self.proposals)
            self.proposals += 1
        elif name == "ComparativeAssessment":
            assert len(request.images) == 4
            self.comparison_prompts.append(request.prompt)
            output = ComparativeAssessment(
                preferred_image="A", rationale="Fixture visual preference", concrete_changes=[]
            )
        elif name == "CriticAssessment":
            output = CriticAssessment(
                verdict="ACCEPT",
                score=0.8,
                findings=[],
                rationale="Independent fixture judgment, not human approval",
            )
        else:
            raise AssertionError(name)
        return ProviderResult(visible_text=output.model_dump_json())


def test_six_distinct_rendered_slots_five_blinded_matches_and_idempotent_replay(
    store, context, inputs, pricing
):
    identity, story = inputs
    provider = TournamentProvider(store, context, story)
    gateway = Gateway(store, provider, pricing)
    result = build_tournament(gateway, context, story.id, identity.id)
    assert len(result.candidates) == 6 and len(result.matches) == 5
    assert provider.calls == 24 and provider.proposals == 6
    assert result.minimum_structural_distance >= 0.035 and result.state == "selected"
    assert not result.human_approval
    assert all(
        "Metaphor" not in prompt and "Fixture visual preference" not in prompt
        for prompt in provider.comparison_prompts
    )
    assert len({c.png_asset_id for c in result.candidates}) == 6
    assert build_tournament(gateway, context, story.id, identity.id) == result
    assert provider.calls == 24
    with pytest.raises(ValueError, match="different inputs"):
        build_tournament(gateway, context, story.id, identity.id, mandate="Changed input")
    # Authored style conditioning requires scoped, reviewed, complete evidence.
    # It supplies only imagery and principles to the model, not scene coordinates.
    from editorial_studio.creative.models import CreativeSpread
    from editorial_studio.reference_studio.conditioning import capture
    from editorial_studio.reference_studio.models import AuthoredReference, EditorialFamily

    spread = store.get("creative_spread", result.candidates[0].spread_id, CreativeSpread)
    family = EditorialFamily(
        id="fixture-family",
        version=1,
        name="Fixture",
        principle="Photographic hierarchy",
        reference_ids=["source-fixture"],
        capability_ids=[],
        suitability=["portrait"],
        composition_rules=["Integrate typography with the photograph"],
    )
    reference = AuthoredReference(
        id="fixture-reference",
        project_id=context.project_id,
        family_id=family.id,
        family_version=1,
        title="Fixture study",
        story_id=story.id,
        spread=spread,
        brief="Original fixture",
        reference_ids=family.reference_ids,
        family_snapshot_json=family.model_dump_json(),
    )
    cfg = {
        "authored_reference_ids": [reference.id],
        "authored_reference_project": context.project_id,
    }
    store.put_records(("authored_reference", reference.id, context.project_id, reference))
    with pytest.raises(ValueError, match="explicit visual review"):
        capture(store, "other-project", cfg)
    reference.status = "visually_reviewed"
    reference.reviewer = "Model fixture review"
    store.put_records(("authored_reference", reference.id, context.project_id, reference))
    before = photo_sources(store, context.project_id, story)
    images, cards = capture(store, "other-project", cfg)
    assert len(images) == len(cards) == 1
    assert store.read_blob("other-project", images[0]) == store.read_blob(
        context.project_id, spread.png_asset_id
    )
    assert cards[0]["input_role"] == "visual_reference_only_not_a_story_asset"
    assert not cards[0]["human_approval"] and "spread" not in cards[0] and "graph" not in cards[0]
    assert photo_sources(store, context.project_id, story) == before
    assert provider.calls == 24
    with pytest.raises(PermissionError, match="outside selected project"):
        capture(store, context.project_id, {**cfg, "authored_reference_project": "wrong-project"})
    # Missing committed evidence must not silently start another paid tournament.
    asset = store.root / context.project_id / "blobs" / result.candidates[0].metadata_asset_id
    asset.unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        build_tournament(gateway, context, story.id, identity.id)
    assert provider.calls == 24


def test_direction_and_candidate_grid_contracts_reject_duplicates():
    value = directions().model_dump()
    value["concepts"][1] = value["concepts"][0]
    with pytest.raises(ValueError, match="distinct"):
        ConceptDirections.model_validate(value)


def test_worker_transports_selected_references_and_preserves_legacy_default(store, monkeypatch):
    from types import SimpleNamespace

    from editorial_studio.core.jobs import BuildTournamentCommand, Command
    from editorial_studio.creative import tournament
    from editorial_studio.worker import process_pipeline_command

    received = []

    def build(*args, **kwargs):
        received.append(kwargs["continuation_configuration"])
        return directions()

    monkeypatch.setattr(tournament, "build_tournament", build)
    monkeypatch.setattr(tournament, "tournament_assets", lambda *args: [])
    for ids in ([], ["reviewed-reference"]):
        process_pipeline_command(
            SimpleNamespace(store=store),
            Command(
                project_id="fixture",
                payload=BuildTournamentCommand(
                    story_id="story",
                    identity_id="identity",
                    authored_reference_ids=ids,
                    authored_reference_project="reference-origin",
                ),
            ),
        )
    assert received[0] is None
    assert received[1]["authored_reference_ids"] == ["reviewed-reference"]
    assert received[1]["authored_reference_project"] == "reference-origin"
    assert received[1]["preserve_display_scale"] and received[1]["minimum_image_ppi"] == 300


def test_tournament_model_schema_is_closed():
    from editorial_studio.llm.schema import strict_schema

    schema = strict_schema(ConceptDirections)
    assert schema["additionalProperties"] is False
    assert all(
        value.get("additionalProperties") is False
        for value in schema["$defs"].values()
        if value.get("type") == "object"
    )
