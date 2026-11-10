import base64
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from editorial_studio.artifacts.inspection import inspect_render
from editorial_studio.artifacts.service import build_artifact, detect_gaps, integrate_artifact
from editorial_studio.artifacts.tracing import config, trace_raster
from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import utcnow
from editorial_studio.llm.contracts import GeneratedImage, ImageRequest, ProviderResult
from editorial_studio.llm.gateway import Gateway
from editorial_studio.spatial.skills import rect


def motif(store):
    image = Image.new("RGB", (256, 256), "white")
    d = ImageDraw.Draw(image)
    d.ellipse((30, 30, 225, 225), fill="black")
    d.ellipse((80, 80, 175, 175), fill="white")
    out = BytesIO()
    image.save(out, format="PNG")
    return store.put_blob("project", out.getvalue(), "image/png").id


def request():
    return m.ArtifactRequest(
        id="motif",
        asset_type="vector",
        visual_role="orbit motif",
        generation_spec="One dark annulus.",
        target_region=m.NormalizedRegion(x=0.55, y=0.25, width=0.3, height=0.5),
        color_constraints=["#9e4d32"],
        preferred_generation_method="gpt-image-2",
        target_layer_dependency_id="target",
        integration_method="direct",
        output=m.VectorOutputSpec(),
        provenance_notes="Original acceptance fixture",
        visual_acceptance_checks=["closed contour", "retained hole"],
    )


def test_potrace_vector_fidelity_and_hole_from_independent_raster(store, context):
    from editorial_studio.settings import ROOT

    if not (ROOT / config()["potrace_path"]).exists():
        pytest.skip("local Potrace binary unavailable")
    source = motif(store)
    traced = trace_raster(store, context, source)
    assert traced.reconstructed_iou > 0.97
    from shapely.geometry import Point

    from editorial_studio.canvas.typography.paths import region

    shape = region(traced.path)
    assert shape.covers(Point(50, 128)) and not shape.covers(Point(128, 128))
    assert store.asset("project", traced.svg_asset_id).media_type == "image/svg+xml"


def test_gap_generation_context_classification_integration_and_inspection(
    store, context, pricing, provider_factory
):
    source = motif(store)
    req = request()
    provider = provider_factory(
        [ProviderResult(images=[GeneratedImage(data=store.read_blob("project", source))])]
    )
    gateway = Gateway(store, provider, pricing)
    assert detect_gaps([req], []) == [req]
    build = build_artifact(gateway, context, req, [source])
    assert provider.calls == 1 and build.provider_call_id
    assert build.traced and not detect_gaps([req], [build])
    assert build_artifact(gateway, context, req, [source]) == build and provider.calls == 1
    repo = SceneRepository(store, "project")
    executor = Executor(repo, Renderer(store, "project"))
    target = m.VectorLayer(
        id="target",
        name="Target",
        semantic_role="target",
        z_index=0,
        bounds=m.BoundsMM(x_mm=220, y_mm=70, width_mm=150, height_mm=150),
        path=rect(220, 70, 150, 150),
    )
    document = CanvasDocument.from_scene(
        m.Scene(
            id="artifact-proof",
            spread_id="artifact-proof",
            version="v1",
            width_mm=420,
            height_mm=297,
            design_language_id="m6",
            created_at=utcnow(),
            layers=[target],
        )
    )
    executor.initialize(document, context, dpi=72)
    version = integrate_artifact(store, context, executor, build, "artifact-proof")
    assert any(
        layer.id.startswith("artifact-") and isinstance(layer, m.VectorLayer)
        for layer in repo.load("artifact-proof").scene.layers
    )
    inspection = inspect_render(store, context, version.png_asset_id, dpi=144)
    assert (
        Image.open(BytesIO(store.read_blob("project", inspection.thumbnail_asset_id))).width <= 420
    )
    assert inspection.crop_box_px[2] > inspection.crop_box_px[0]
    assert integrate_artifact(store, context, executor, build, "artifact-proof") == version


def test_model_image_input_checks_project_hash_before_provider(
    store, context, pricing, provider_factory
):
    from editorial_studio.llm.contracts import ImageInput

    source = motif(store)
    provider = provider_factory([])
    gateway = Gateway(store, provider, pricing)
    with pytest.raises(ValueError, match="immutable asset"):
        gateway.invoke(
            context,
            ImageRequest(
                model="gpt-image-2",
                prompt="Motif",
                images=[
                    ImageInput(asset_id=source, data_base64=base64.b64encode(b"wrong").decode())
                ],
            ),
        )
    assert provider.calls == 0


def test_integration_recovers_commit_before_metadata_write_without_render_or_model_call(
    store, context, pricing, provider_factory, monkeypatch
):
    from editorial_studio.artifacts.models import ArtifactBuild

    source = motif(store)
    provider = provider_factory([])
    gateway = Gateway(store, provider, pricing)
    build = build_artifact(gateway, context, request(), [], source_raster_asset_id=source)
    repo = SceneRepository(store, "project")
    executor = Executor(repo, Renderer(store, "project"))
    target = m.VectorLayer(
        id="target",
        name="Target",
        semantic_role="target",
        z_index=0,
        bounds=m.BoundsMM(x_mm=220, y_mm=70, width_mm=150, height_mm=150),
        path=rect(220, 70, 150, 150),
    )
    executor.initialize(
        CanvasDocument.from_scene(
            m.Scene(
                id="recover-artifact",
                spread_id="recover-artifact",
                version="initial",
                width_mm=420,
                height_mm=297,
                design_language_id="m6",
                created_at=utcnow(),
                layers=[target],
            )
        ),
        context,
        dpi=72,
    )
    persist = store.put_records

    def crash(*entries):
        if any(kind == "artifact_build" and model.placed_scene_id for kind, _, _, model in entries):
            raise RuntimeError("interrupted after scene commit")
        return persist(*entries)

    monkeypatch.setattr(store, "put_records", crash)
    with pytest.raises(RuntimeError):
        integrate_artifact(store, context, executor, build, "recover-artifact")
    committed = repo.head("recover-artifact")
    monkeypatch.setattr(store, "put_records", persist)

    def no_render(*args, **kwargs):
        raise AssertionError("unexpected render")

    monkeypatch.setattr(executor, "_render_commit", no_render)
    saved = store.get("artifact_build", build.id, ArtifactBuild)
    assert saved.placed_version is None
    assert integrate_artifact(store, context, executor, saved, "recover-artifact") == committed
    assert provider.calls == 0 and len(repo.history("recover-artifact")) == 2
