import base64

import numpy as np
import pytest
from PIL import Image

from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.contracts.models import BoundsMM, EditType, SourceSpan
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import (
    analyze_photo,
    assess_placement,
    conditional_upscale,
    ingest_story,
    png,
)


def test_low_quality_source_and_maps_and_ppi(store, context):
    asset = store.put_blob("project", png(Image.new("RGB", (100, 100), "#999999")), "image/png")
    p = analyze_photo(
        store, context, asset.id, source_uri="fixture:flat", credit="Original fixture"
    )
    assert any("low_sharpness" in f for f in p.findings)
    assert any("low_contrast" in f for f in p.findings)
    assert Image.open(
        __import__("io").BytesIO(store.read_blob("project", p.saliency_asset_id))
    ).size == (100, 100)
    small = assess_placement(p, BoundsMM(x_mm=0, y_mm=0, width_mm=10, height_mm=10))
    assert small.status == "native" and small.effective_ppi == 254
    large = assess_placement(p, BoundsMM(x_mm=0, y_mm=0, width_mm=100, height_mm=50))
    assert large.status == "stylize_or_reduce" and large.visible_source_fraction == 0.5
    with pytest.raises(ValueError):
        conditional_upscale(store, context, p, large.frame, inspected=True)


def test_ten_photo_stories_ingested_idempotently_with_independent_coverage(store, context):
    ledger = ProvenanceLedger(store, "project")
    for i in range(10):
        pixels = np.random.default_rng(i).integers(0, 256, (150, 200, 3), dtype=np.uint8)
        photo = PhotoInput(
            filename=f"{i}.png",
            data_base64=base64.b64encode(png(Image.fromarray(pixels))).decode(),
            source_uri=f"fixture:{i}",
            credit="Original deterministic test image",
        )
        story = StoryInput(
            id=f"story-{i}",
            title=f"Title {i}",
            deck="A source deck.",
            body=f"Original story number {i}. Complete source copy.",
            author="Fixture",
            photos=[photo],
        )
        saved = ingest_story(store, context, story)
        assert ingest_story(store, context, story) == saved
        block = ledger.get(saved.body_block_id)
        assert block.source_text == story.body and block.derived_texts[0].text == story.body
        assert ledger.coverage(block.id).unassigned_ranges == [(0, len(story.body))]
    from editorial_studio.photos.models import IngestedStory

    assert len(store.list("story", IngestedStory, "project")) == 10


def test_provenance_rejects_fabricated_spans_and_keeps_revisions(store, context):
    ledger = ProvenanceLedger(store, "project")
    b = ledger.source("s", "body", "Original words.", [])
    s = SourceSpan(
        source_block_id=b.id, source_revision_id=b.source_revision_id, start_char=0, end_char=8
    )
    with pytest.raises(ValueError):
        ledger.derive("Changed!", EditType.EXCERPT, [s])
    d = ledger.derive("Original", EditType.EXCERPT, [s])
    from editorial_studio.canvas.executor import Executor
    from editorial_studio.canvas.models import CanvasDocument
    from editorial_studio.canvas.renderer import Renderer
    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.contracts.models import Scene, TextLayer
    from editorial_studio.core.storage import utcnow

    scene = Scene(
        id="binding",
        spread_id="binding",
        version="v1",
        width_mm=420,
        height_mm=297,
        design_language_id="proof",
        created_at=utcnow(),
        layers=[
            TextLayer(
                id="headline",
                name="Headline",
                semantic_role="headline",
                z_index=0,
                bounds=BoundsMM(x_mm=20, y_mm=20, width_mm=100, height_mm=30),
                text_content=d.text,
                style_name="body",
                derived_text_id=d.id,
            )
        ],
    )
    Executor(SceneRepository(store, "project"), Renderer(store, "project")).initialize(
        CanvasDocument.from_scene(scene), context, dpi=72
    )
    ledger.bind(d.id, ["headline"], scene_id="binding")
    assert ledger.coverage(b.id).represented_ranges == [(0, 8)]
    assert ledger.coverage(b.id).unassigned_ranges == [(8, 15)]
    new = ledger.source("s", "body", "Revised words.", [])
    assert new.id != b.id and ledger.get(b.id).source_text == "Original words."
    with pytest.raises(PermissionError):
        ProvenanceLedger(store, "other").get(b.id)


def test_real_small_upscaler_preserves_source_sampling_risk(store, context):
    from editorial_studio.photos.pipeline import configuration
    from editorial_studio.settings import ROOT

    if not (ROOT / configuration()["upscaler"]["path"]).exists():
        pytest.skip("optional local weights absent")
    asset = store.put_blob("project", png(Image.new("RGB", (32, 32), "#777777")), "image/png")
    photo = analyze_photo(store, context, asset.id, source_uri="fixture:upscale", credit="Fixture")
    frame = BoundsMM(x_mm=0, y_mm=0, width_mm=4, height_mm=4)
    with pytest.raises(ValueError):
        conditional_upscale(store, context, photo, frame, inspected=False)
    result = conditional_upscale(store, context, photo, frame, inspected=True)
    assert result.placement.original_ppi == 203.2 and result.review_required
    from io import BytesIO

    assert Image.open(BytesIO(store.read_blob("project", result.output_asset_id))).size == (64, 64)


def test_queued_ingestion_is_local_and_records_maps(store, context, pricing, provider_factory):
    from editorial_studio.core.jobs import Command, IngestStoryCommand, Queue
    from editorial_studio.llm.gateway import Gateway
    from editorial_studio.settings import Settings
    from editorial_studio.worker import process_one

    p = PhotoInput(
        filename="a.png",
        data_base64=base64.b64encode(png(Image.new("RGB", (80, 80)))).decode(),
        source_uri="fixture:a",
        credit="Fixture",
    )
    story = StoryInput(id="queued", title="A", deck="B", body="C", author="Test", photos=[p])
    queue = Queue(store)
    queue.submit(Command(project_id="project", payload=IngestStoryCommand(story=story)))
    provider = provider_factory([])
    assert process_one(queue, Gateway(store, provider, pricing), "worker", Settings())
    assert queue.list()[0].status == "completed" and provider.calls == 0


def test_attachment_replacement_preserves_old_block_and_new_links(store):
    ledger = ProvenanceLedger(store, "project")
    old = ledger.source("s", "body", "Same copy.", ["old-photo"])
    new = ledger.source("s", "body", "Same copy.", ["new-photo"])
    assert old.id != new.id and ledger.get(old.id).attached_image_ids == ["old-photo"]
    assert ledger.get(new.id).attached_image_ids == ["new-photo"]


def test_source_creation_repairs_interrupted_verbatim_derivation(store, monkeypatch):
    ledger = ProvenanceLedger(store, "project")
    original = ledger.derive

    def crash(*args, **kwargs):
        raise RuntimeError("interruption")

    monkeypatch.setattr(ledger, "derive", crash)
    with pytest.raises(RuntimeError):
        ledger.source("s", "body", "Recovery copy.", [])
    monkeypatch.setattr(ledger, "derive", original)
    repaired = ledger.source("s", "body", "Recovery copy.", [])
    assert len(repaired.derived_texts) == 1 and repaired.derived_texts[0].text == "Recovery copy."


def test_published_text_cannot_change_without_a_new_provenance_revision(store, context):
    from editorial_studio.canvas.executor import Executor
    from editorial_studio.canvas.models import CanvasDocument
    from editorial_studio.canvas.renderer import Renderer
    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.contracts import models as m
    from editorial_studio.core.storage import utcnow
    from editorial_studio.spatial.assistant import SpatialAssistant
    from editorial_studio.spatial.skills import rect

    ledger = ProvenanceLedger(store, "project")
    block = ledger.source("s", "body", "Original source copy.", [])
    derived = block.derived_texts[0]
    scene = m.Scene(
        id="provenance-proof",
        spread_id="provenance-proof",
        version="initial",
        width_mm=420,
        height_mm=297,
        design_language_id="proof",
        created_at=utcnow(),
        layers=[
            m.TextLayer(
                id="body",
                name="Body",
                semantic_role="body",
                z_index=0,
                bounds=BoundsMM(x_mm=20, y_mm=20, width_mm=150, height_mm=100),
                text_content=derived.text,
                style_name="body",
                derived_text_id=derived.id,
            )
        ],
    )
    doc = CanvasDocument.from_scene(scene)
    doc.enforce_text_provenance = True
    repo = SceneRepository(store, "project")
    executor = Executor(repo, Renderer(store, "project"))
    version = executor.initialize(doc, context, dpi=72)
    with pytest.raises(ValueError, match="provenance-aware"):
        SpatialAssistant(executor).apply(
            [
                m.FlowTextIntoShapeOp(
                    layer_id="body",
                    text_content="Changed source copy.",
                    style_name="body",
                    boundary=rect(20, 20, 150, 100),
                )
            ],
            "provenance-proof",
            context,
            dpi=72,
        )
    assert repo.head("provenance-proof") == version
