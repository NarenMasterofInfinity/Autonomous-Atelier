import base64

import pymupdf
import pytest
from PIL import Image
from test_m8_tournament import proposal

from editorial_studio.art_direction.service import build_identity
from editorial_studio.contracts import models as m
from editorial_studio.creative.issue import build_issue, printer_map, revise_issue
from editorial_studio.creative.issue_models import IssueBlueprint, IssueCorrection, IssueSlot
from editorial_studio.creative.models import CriticAssessment
from editorial_studio.llm.contracts import ProviderResult
from editorial_studio.llm.gateway import Gateway
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story, png


def blueprint():
    pairs = [(12, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11)]
    phases = ["cover", "opening", "feature", "essay", "interlude", "closing"]
    return IssueBlueprint(
        title="A close look",
        throughline="An original acceptance fixture",
        slots=[
            IssueSlot(
                id=f"slot-{i}",
                story_id=f"story-{i + 1}",
                phase=phases[i],
                left_page=left,
                right_page=right,
                visual_energy=5 - i % 4,
                visual_metaphor=f"Metaphor {i}",
                narrative_goal="Follow the actual objects",
                composition_mandate="Respect the source and change the reading rhythm",
            )
            for i, (left, right) in enumerate(pairs)
        ],
    )


@pytest.fixture
def issue_inputs(store, context):
    identity = build_identity(
        store, context.model_copy(update={"run_id": "issue-identity"}), dpi=72
    )
    stories = []
    for i in range(6):
        stories.append(
            ingest_story(
                store,
                context,
                StoryInput(
                    id=f"source-{i}",
                    title=f"Source {i}",
                    deck=f"An original fixture for story {i}.",
                    body=f"This is the complete body of original story {i}. The reader follows a table, a chair and a doorway as their arrangement changes.",
                    author="Original fixture",
                    photos=[
                        PhotoInput(
                            filename=f"photo-{i}.png",
                            data_base64=base64.b64encode(
                                png(Image.new("RGB", (5000, 5000), (120 + i * 10, 100, 70)))
                            ).decode(),
                            source_uri="fixture:original",
                            credit="Original fixture",
                        )
                    ],
                ),
            )
        )
    return identity, stories


class IssueProvider:
    namespace = "m9-independent-fixture"

    def __init__(self, store, context, stories):
        self.store, self.context, self.stories = store, context, stories
        self.calls = 0
        self.index = 0
        self.composer_prompts = []
        self.composer_images = []

    def execute(self, request, progress):
        self.calls += 1
        name = request.output_contract.rsplit(".", 1)[-1]
        if name == "IssueBlueprint":
            output = blueprint()
        elif name == "ConceptProposal":
            self.composer_prompts.append(request.prompt)
            self.composer_images.append(len(request.images))
            output = proposal(self.store, self.context, self.stories[self.index], self.index)
            next(t for t in output.treatments if t.node_id == "photo").image_treatment = "native"
            if self.index == 0:
                next(n for n in output.graph.nodes if n.id == "photo").target_region.x = 0
            self.index += 1
        elif name == "CriticAssessment":
            output = CriticAssessment(
                verdict="ACCEPT",
                score=0.8,
                findings=[],
                rationale="Independent fixture judgment; not owner approval",
            )
        else:
            raise AssertionError(name)
        return ProviderResult(visible_text=output.model_dump_json())


def test_issue_has_twelve_physical_pages_actual_visual_history_and_replay_safety(
    store, context, issue_inputs, pricing
):
    identity, stories = issue_inputs
    provider = IssueProvider(store, context, stories)
    gateway = Gateway(store, provider, pricing)
    result = build_issue(gateway, context, [s.id for s in stories], identity.id)
    assert len(result.spreads) == 6 and len(result.page_map.pages) == 12
    assert provider.calls == 20 and not result.human_approval
    assert provider.composer_images[1] > provider.composer_images[0]
    assert '"photo_frame_fraction"' in provider.composer_prompts[-1]
    assert result.spreads[0].bible_before.version != result.spreads[-1].bible_after.version
    for before, after in zip(result.spreads, result.spreads[1:], strict=False):
        assert before.bible_after == after.bible_before
        assert before.contact_sheet_asset_id != after.contact_sheet_asset_id
    with pymupdf.open(
        stream=store.read_blob(context.project_id, result.reader_pdf_asset_id), filetype="pdf"
    ) as pdf:
        assert len(pdf) == 12 and all(
            abs(page.rect.width * 25.4 / 72 - 210) < 0.001 for page in pdf
        )
        assert "Source 0" in pdf[0].get_text()
        assert "Source 0" not in pdf[11].get_text()
        assert all(page.get_fonts(full=True) for page in pdf if page.get_text().strip())
    assert result.page_map.pages[0].side == m.PageSide.RIGHT
    assert result.page_map.pages[-1].side == m.PageSide.LEFT
    assert build_issue(gateway, context, [s.id for s in stories], identity.id) == result
    assert provider.calls == 20
    revision = revise_issue(
        gateway,
        context.model_copy(update={"run_id": "issue-revised"}),
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
    assert provider.calls == 23  # revised mandate requires a fresh coherence assessment
    assert "Current revision" in revision.blueprint.slots[2].composition_mandate
    assert revision.spreads[2].source == "native_repair"
    assert revision.spreads[2].spread.scene_id != result.spreads[2].spread.scene_id
    for index in (0, 1, 3, 4, 5):
        assert revision.spreads[index].source == "retained"
        assert revision.spreads[index].spread == result.spreads[index].spread
    assert revision.spreads[0].bible_after.version != result.spreads[0].bible_after.version
    assert store.get("issue", result.id, type(result)) == result
    with pytest.raises(ValueError, match="stale"):
        revise_issue(gateway, context, result.id, "wrong", [])
    with pytest.raises(ValueError, match="different inputs"):
        build_issue(gateway, context, [s.id for s in reversed(stories)], identity.id)
    assert provider.calls == 23
    (
        store.root / context.project_id / "blobs" / result.spreads[0].spread.metadata_asset_id
    ).unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        build_issue(gateway, context, [s.id for s in stories], identity.id)
    assert provider.calls == 23


def test_architect_rejects_missing_duplicate_and_misordered_pages():
    value = blueprint().model_dump()
    value["slots"][0]["left_page"] = 1
    with pytest.raises(ValueError, match="covers"):
        IssueBlueprint.model_validate(value)
    value = blueprint().model_dump()
    value["slots"][1]["story_id"] = value["slots"][0]["story_id"]
    with pytest.raises(ValueError, match="unique"):
        IssueBlueprint.model_validate(value)
    sheets = printer_map()
    assert (
        sheets[0].front_left,
        sheets[0].front_right,
        sheets[0].back_left,
        sheets[0].back_right,
    ) == (12, 1, 2, 11)
    assert (
        sheets[-1].front_left,
        sheets[-1].front_right,
        sheets[-1].back_left,
        sheets[-1].back_right,
    ) == (8, 5, 6, 7)
