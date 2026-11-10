import math
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageChops, ImageStat

from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.renderer import LayoutRejected, Renderer
from editorial_studio.canvas.repository import SceneRepository, VersionConflict
from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import REGISTRY, PatchRejected, RuntimePolicy
from editorial_studio.llm.contracts import CallContext


def solid_path(x=0, y=0, width=420, height=297):
    return m.PathGeometry(
        commands=[
            m.MoveTo(p=m.PointMM(x_mm=x, y_mm=y)),
            m.LineTo(p=m.PointMM(x_mm=x + width, y_mm=y)),
            m.LineTo(p=m.PointMM(x_mm=x + width, y_mm=y + height)),
            m.LineTo(p=m.PointMM(x_mm=x, y_mm=y + height)),
            m.ClosePath(),
        ]
    )


def document():
    scene = m.Scene(
        id="canvas",
        spread_id="spread",
        version="v1",
        width_mm=420,
        height_mm=297,
        design_language_id="m1-proof",
        created_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
        layers=[
            m.VectorLayer(
                id="background",
                name="Background",
                semantic_role="background",
                z_index=0,
                bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=420, height_mm=297),
                path=solid_path(),
                fill_color="#f4f0e8",
            ),
            m.TextLayer(
                id="title",
                name="Title",
                semantic_role="headline",
                z_index=1,
                bounds=m.BoundsMM(x_mm=20, y_mm=30, width_mm=350, height_mm=40),
                text_content="Quiet rooms, afternoon light",
                style_name="headline",
            ),
            m.TextLayer(
                id="body",
                name="Body",
                semantic_role="body",
                z_index=2,
                bounds=m.BoundsMM(x_mm=220, y_mm=100, width_mm=150, height_mm=100),
                text_content="An office becomes a place for reflection. Café conversations fade; the room remains. "
                * 4,
                style_name="body",
            ),
        ],
    )
    return CanvasDocument.from_scene(scene)


@pytest.fixture
def canvas(store):
    context = CallContext(
        project_id="project", run_id="m1-run", agent_name="CanvasVerifier", stage="M1"
    )
    renderer = Renderer(store, "project")
    repo = SceneRepository(store, "project")
    executor = Executor(repo, renderer)
    executor.initialize(document(), context, dpi=72)
    ids = {layer.id for layer in document().scene.layers}
    policy = RuntimePolicy(
        readable_layer_ids=ids,
        writable_layer_ids=ids,
        allowed_operations=set(REGISTRY),
        renderer_operations=set(REGISTRY),
        style_names={"headline", "body", "caption"},
    )
    return executor, repo, policy, context


def make_patch(repo, ops, modified, *, created=None, dependencies=None):
    return m.ScenePatch(
        patch_id="patch",
        target_scene_id="canvas",
        parent_version=repo.head("canvas").version,
        operations=ops,
        modified_layer_ids=modified,
        created_layer_ids=created or [],
        declared_dependencies=dependencies if dependencies is not None else modified,
    )


def test_continuous_canvas_dimensions_gutter_and_embedded_vector_text(store):
    result = Renderer(store, "project").render(document(), dpi=72)
    image = Image.open(BytesIO(result.png)).convert("RGB")
    assert image.size == (math.ceil(420 * 72 / 25.4), math.ceil(297 * 72 / 25.4))
    gutter = round(210 * 72 / 25.4)
    assert (
        image.getpixel((gutter - 1, 800))
        == image.getpixel((gutter, 800))
        == image.getpixel((gutter + 1, 800))
    )
    pdf = pymupdf.open(stream=result.pdf, filetype="pdf")
    assert len(pdf) == 1
    assert pdf[0].rect.width == pytest.approx(420 * 72 / 25.4, abs=0.001)
    assert "Quiet rooms" in pdf[0].get_text()
    assert pdf[0].get_fonts()
    for font in pdf[0].get_fonts():
        assert pdf.extract_font(font[0])[3], "Font must be embedded"


def test_preview_and_pdf_have_same_layout_and_close_pixels(store):
    result = Renderer(store, "project").render(document(), dpi=144)
    preview = Image.open(BytesIO(result.png)).convert("RGB")
    pdf = pymupdf.open(stream=result.pdf, filetype="pdf")
    pix = pdf[0].get_pixmap(dpi=144, alpha=False)
    raster = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    assert preview.size == raster.size
    assert max(ImageStat.Stat(ImageChops.difference(preview, raster)).mean) < 1.5
    assert all(layout.result.overflow_start_char is None for layout in result.metadata.text_layouts)


def test_patch_apply_is_rendered_persisted_and_snapshot_backed(canvas):
    executor, repo, policy, context = canvas
    old = repo.head("canvas")
    patch = make_patch(repo, [m.SetOpacityOp(layer_id="title", opacity=0.5)], ["title"])
    version = executor.apply(patch, policy, context, dpi=72)
    assert (
        version.parent_version == old.version and version.snapshot_asset_id == old.document_asset_id
    )
    assert repo.load("canvas").scene.layers[1].opacity == 0.5
    assert repo.store.read_blob("project", version.pdf_asset_id).startswith(b"%PDF")
    assert len(repo.history("canvas")) == 2


def test_stale_parent_and_missing_references_leave_head_unchanged(canvas):
    executor, repo, policy, context = canvas
    original = repo.head("canvas")
    patch = make_patch(repo, [m.SetOpacityOp(layer_id="title", opacity=0.5)], ["title"])
    executor.apply(patch, policy, context, dpi=72)
    current = repo.head("canvas")
    with pytest.raises(PatchRejected, match="stale"):
        executor.apply(patch, policy, context, dpi=72)
    missing = make_patch(repo, [m.SetOpacityOp(layer_id="absent", opacity=0.5)], ["absent"])
    with pytest.raises(PatchRejected, match="missing layer"):
        executor.apply(missing, policy, context, dpi=72)
    assert repo.head("canvas") == current and current.version != original.version


def test_overflow_rejects_entire_candidate(canvas):
    executor, repo, policy, context = canvas
    before = repo.head("canvas")
    patch = make_patch(
        repo,
        [
            m.SetOpacityOp(layer_id="title", opacity=0.2),
            m.AddTextOp(
                layer_id="overflow",
                text_content="Unplaced copy. " * 100,
                style_name="body",
                bounds=m.BoundsMM(x_mm=10, y_mm=10, width_mm=20, height_mm=3),
            ),
        ],
        ["title"],
        created=["overflow"],
    )
    with pytest.raises(LayoutRejected):
        executor.apply(patch, policy, context, dpi=72)
    assert repo.head("canvas") == before
    assert repo.load("canvas").scene.layers[1].opacity == 1


def test_renderer_failure_never_publishes_partial_scene(canvas, monkeypatch):
    executor, repo, policy, context = canvas
    before = repo.head("canvas")

    def fail(*args, **kwargs):
        raise RuntimeError("injected renderer failure")

    monkeypatch.setattr(executor.renderer, "render", fail)
    with pytest.raises(RuntimeError):
        executor.apply(
            make_patch(repo, [m.SetOpacityOp(layer_id="title", opacity=0.2)], ["title"]),
            policy,
            context,
        )
    assert repo.head("canvas") == before


def test_rollback_restores_editable_snapshot_as_a_new_version(canvas):
    executor, repo, policy, context = canvas
    original = repo.head("canvas")
    original_document = repo.load("canvas")
    changed = executor.apply(
        make_patch(repo, [m.SetOpacityOp(layer_id="title", opacity=0.2)], ["title"]),
        policy,
        context,
        dpi=72,
    )
    rolled = executor.rollback("canvas", original.version, changed.version, context, dpi=72)
    assert rolled.version not in {original.version, changed.version}
    assert rolled.parent_version == changed.version
    restored = repo.load("canvas")
    assert restored.scene.layers == original_document.scene.layers
    assert len(repo.history("canvas")) == 3


def test_disabled_operation_is_rejected_before_commit(canvas):
    executor, repo, policy, context = canvas
    before = repo.head("canvas")
    op = m.TextOnPathOp(
        layer_id="title", text_content="Quiet", style_name="headline", path=solid_path()
    )
    patch = make_patch(repo, [op], ["title"])
    policy.renderer_operations.discard("text_on_path")
    with pytest.raises(PatchRejected, match="capability unavailable"):
        executor.apply(patch, policy, context, dpi=72)
    assert repo.head("canvas") == before


def test_transforms_are_persisted_without_destroying_editable_text(canvas):
    executor, repo, policy, context = canvas
    patch = make_patch(
        repo, [m.TransformLayerOp(layer_id="title", dx_mm=10, rotation_deg=5)], ["title"]
    )
    executor.apply(patch, policy, context, dpi=72)
    doc = repo.load("canvas")
    assert doc.scene.layers[1].text_content == "Quiet rooms, afternoon light"
    state = next(p for p in doc.presentations if p.layer_id == "title")
    assert state.transform.b != 0 and state.source_bounds.x_mm == 20


def test_compare_and_swap_rejects_render_from_stale_parent(canvas):
    executor, repo, policy, context = canvas
    old = repo.load("canvas")
    executor.apply(
        make_patch(repo, [m.SetOpacityOp(layer_id="title", opacity=0.2)], ["title"]),
        policy,
        context,
        dpi=72,
    )
    old.scene.parent_version = "v1"
    old.scene.version = "stale-candidate"
    rendered = executor.renderer.render(old, dpi=72)
    with pytest.raises(VersionConflict):
        repo.commit(old, rendered, context, expected_parent="v1")


def test_golden_preview_matches_reviewed_fixture(store):
    result = Renderer(store, "project").render(document(), dpi=72)
    expected = Image.open(Path("tests/fixtures/golden/m1-canvas.png")).convert("RGB")
    actual = Image.open(BytesIO(result.png)).convert("RGB")
    assert actual.size == expected.size
    assert ImageChops.difference(actual, expected).getbbox() is None


def raster_asset(store, color, size=(20, 10)):
    image = Image.new("RGB", size, color)
    out = BytesIO()
    image.save(out, format="PNG")
    return store.put_blob("project", out.getvalue(), "image/png").id


def small_document(layers):
    return CanvasDocument.from_scene(
        m.Scene(
            id="small",
            spread_id="small",
            version="v1",
            width_mm=20,
            height_mm=10,
            design_language_id="proof",
            created_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
            layers=layers,
        )
    )


def box_layer(layer_id, color, x=0, width=20, z=0):
    return m.VectorLayer(
        id=layer_id,
        name=layer_id,
        semantic_role="shape",
        z_index=z,
        bounds=m.BoundsMM(x_mm=x, y_mm=0, width_mm=width, height_mm=10),
        fill_color=color,
        path=solid_path(x=x, width=width, height=10),
    )


@pytest.mark.parametrize("invert", [False, True])
def test_alpha_masks_and_inversion_are_rendered_without_modifying_source(store, invert):
    asset = raster_asset(store, "blue")
    mask = Image.new("L", (20, 10), 0)
    mask.paste(255, (0, 0, 10, 10))
    out = BytesIO()
    mask.save(out, format="PNG")
    mask_id = store.put_blob("project", out.getvalue(), "image/png").id
    layer = m.ImageLayer(
        id="image",
        name="image",
        semantic_role="lead",
        z_index=0,
        asset_id=asset,
        bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=20, height_mm=10),
    )
    doc = small_document([layer])
    doc.presentations[0].mask_asset_id = mask_id
    doc.presentations[0].invert_mask = invert
    result = Renderer(store, "project").render(doc, dpi=254)
    image = Image.open(BytesIO(result.png)).convert("RGB")
    left, right = image.getpixel((40, 40)), image.getpixel((160, 40))
    assert (left, right) == (
        ((255, 255, 255), (0, 0, 255)) if invert else ((0, 0, 255), (255, 255, 255))
    )
    assert store.read_blob("project", asset)


def test_compound_evenodd_clipping_preserves_hole(store):
    doc = small_document([box_layer("blue", "#0000ff")])
    hole = solid_path(x=7, y=3, width=6, height=4)
    doc.presentations[0].clips = [
        m.PathGeometry(
            commands=solid_path(width=20, height=10).commands + hole.commands, fill_rule="evenodd"
        )
    ]
    image = Image.open(BytesIO(Renderer(store, "project").render(doc, dpi=254).png)).convert("RGB")
    assert image.getpixel((30, 40)) == (0, 0, 255)
    assert image.getpixel((100, 40)) == (255, 255, 255)


def test_group_opacity_composites_once_even_where_children_overlap(store):
    a, b = box_layer("a", "#ff0000", width=15), box_layer("b", "#ff0000", x=5, width=15)
    group = m.GroupLayer(
        id="group",
        name="group",
        semantic_role="group",
        z_index=0,
        bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=20, height_mm=10),
        opacity=0.5,
        member_layer_ids=["a", "b"],
    )
    image = Image.open(
        BytesIO(Renderer(store, "project").render(small_document([a, b, group]), dpi=254).png)
    ).convert("RGB")
    assert image.getpixel((30, 50)) == image.getpixel((100, 50)) == image.getpixel((170, 50))
    assert image.getpixel((100, 50))[1] in {127, 128}


def test_blend_modes_affect_composite_in_z_order(store):
    bottom = box_layer("red", "#ff0000")
    top = box_layer("blue", "#0000ff", x=5, width=10, z=1)
    top.blend_mode = "multiply"
    result = Renderer(store, "project").render(small_document([bottom, top]), dpi=254)
    image = Image.open(BytesIO(result.png)).convert("RGB")
    assert image.getpixel((30, 50)) == (255, 0, 0) and image.getpixel((100, 50)) == (0, 0, 0)


def test_supported_executor_operations_have_native_render_proof(canvas):
    from uuid import uuid4

    executor, repo, policy, context = canvas
    asset = raster_asset(repo.store, "blue")
    mask = raster_asset(repo.store, "white")
    policy.asset_ids.update([asset, mask])
    policy.mask_asset_ids.add(mask)
    frame = m.BoundsMM(x_mm=20, y_mm=150, width_mm=80, height_mm=80)
    path = solid_path(x=20, y=150, width=80, height=80)
    ops = [
        m.AddImageOp(layer_id="image", asset_id=asset, bounds=frame),
        m.AddTextOp(
            layer_id="caption",
            text_content="A short caption.",
            style_name="caption",
            bounds=m.BoundsMM(x_mm=20, y_mm=240, width_mm=80, height_mm=15),
        ),
        m.TransformLayerOp(layer_id="image", dx_mm=5, rotation_deg=2),
        m.ClipToPathOp(target_layer_id="image", path=path),
        m.SetZIndexOp(layer_id="image", z_index=1),
        m.ApplyMaskOp(target_layer_id="image", mask_asset_id=mask),
        m.AddPathOp(layer_id="clip", path=path),
        m.EditPathOp(layer_id="clip", path=path),
        m.SetBlendModeOp(layer_id="image", blend_mode="multiply"),
        m.CreateGroupOp(group_layer_id="type-group", member_layer_ids=["caption", "title"]),
        m.SetClipStackOp(target_layer_id="image", clip_path_layer_ids=["clip"]),
        m.BindAssetOp(layer_id="image", asset_id=asset, asset_type="raster"),
        m.SetOpacityOp(layer_id="image", opacity=0.9),
    ]
    assert {op.op for op in ops} <= executor.supported_operations
    patch = m.ScenePatch(
        patch_id=uuid4().hex,
        parent_version=repo.head("canvas").version,
        target_scene_id="canvas",
        operations=ops,
        created_layer_ids=["image", "caption", "clip", "type-group"],
        modified_layer_ids=["title"],
        declared_dependencies=["title", asset, mask],
    )
    version = executor.apply(patch, policy, context, dpi=72)
    assert repo.store.read_blob("project", version.png_asset_id)
    assert len(repo.load("canvas").scene.layers) == 7


def test_unicode_ligatures_and_fallback_match_in_preview_and_vector_pdf(store):
    import unicodedata

    doc = document()
    doc.scene.layers[2].text_content = "office café naïve — Αθήνα Москва العربية"
    output = Renderer(store, "project").render(doc, dpi=144)
    preview = Image.open(BytesIO(output.png)).convert("RGB")
    pdf = pymupdf.open(stream=output.pdf, filetype="pdf")
    text = unicodedata.normalize("NFKC", pdf[0].get_text())
    assert "office" in text and "café" in text and "Αθήνα" in text and "Москва" in text
    pix = pdf[0].get_pixmap(dpi=144, alpha=False)
    raster = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    assert max(ImageStat.Stat(ImageChops.difference(preview, raster)).mean) < 1.5
    assert any(
        f.code == "FONT_FALLBACK"
        for layout in output.metadata.text_layouts
        for f in layout.result.findings
    )
    assert all(pdf.extract_font(font[0])[3] for font in pdf[0].get_fonts())


def test_group_transform_cannot_modify_a_child_owned_by_another_skill(canvas):
    executor, repo, policy, context = canvas
    current = repo.load("canvas")
    current.scene.layers[1].owner_skill_id = "other-skill"
    # Start a separate scene whose imported ownership is explicitly protected.
    current.scene.id = "owned"
    current.scene.version = "v1"
    current.scene.layers.append(
        m.GroupLayer(
            id="group",
            name="group",
            semantic_role="group",
            z_index=0,
            bounds=current.scene.layers[1].bounds,
            member_layer_ids=["title"],
        )
    )
    current.presentations.append(
        __import__(
            "editorial_studio.canvas.models", fromlist=["LayerPresentation"]
        ).LayerPresentation(layer_id="group", source_bounds=current.scene.layers[1].bounds)
    )
    executor.initialize(current, context, dpi=72)
    policy.readable_layer_ids.add("group")
    policy.writable_layer_ids.add("group")
    patch = m.ScenePatch(
        patch_id="ownership",
        target_scene_id="owned",
        parent_version="v1",
        operations=[m.TransformLayerOp(layer_id="group", dx_mm=2)],
        modified_layer_ids=["group", "title"],
        declared_dependencies=["group", "title"],
    )
    with pytest.raises(PatchRejected, match="owned by another"):
        executor.apply(patch, policy, context, dpi=72)


def test_mask_layer_invert_is_preserved_in_coverage_proof(store):
    asset = raster_asset(store, "white")
    mask = m.MaskLayer(
        id="mask",
        name="Mask",
        semantic_role="matte",
        z_index=0,
        mask_asset_id=asset,
        invert=True,
        bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=20, height_mm=10),
    )
    output = Renderer(store, "project").render(small_document([mask]), dpi=254)
    assert Image.open(BytesIO(output.png)).convert("RGB").getpixel((100, 50)) == (0, 0, 0)


def test_renderer_capability_declaration_overrides_available_executor_method(canvas, monkeypatch):
    executor, repo, policy, context = canvas
    monkeypatch.setattr(executor.renderer, "supported_operations", frozenset())
    patch = make_patch(repo, [m.SetOpacityOp(layer_id="title", opacity=0.5)], ["title"])
    with pytest.raises(PatchRejected, match="capability unavailable"):
        executor.apply(patch, policy, context, dpi=72)


def test_member_geometry_refreshes_ancestor_group_bounds(store):
    from uuid import uuid4

    doc = small_document(
        [box_layer("a", "#ff0000", width=10), box_layer("b", "#0000ff", x=5, width=15)]
    )
    group = m.GroupLayer(
        id="group",
        name="Group",
        semantic_role="group",
        z_index=0,
        bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=20, height_mm=10),
        member_layer_ids=["a", "b"],
    )
    doc.scene.layers.append(group)
    from editorial_studio.canvas.models import LayerPresentation

    doc.presentations.append(LayerPresentation(layer_id="group", source_bounds=group.bounds))
    context = CallContext(project_id="project", run_id="groups", agent_name="Verifier", stage="M1")
    repo = SceneRepository(store, "project")
    executor = Executor(repo, Renderer(store, "project"))
    executor.initialize(doc, context, dpi=72)
    policy = RuntimePolicy(
        readable_layer_ids={"a", "b", "group"},
        writable_layer_ids={"a", "b", "group"},
        allowed_operations=set(REGISTRY),
        renderer_operations=set(REGISTRY),
    )
    for target, dx, modified in [("a", 30, ["a"]), ("group", 5, ["a", "b", "group"])]:
        patch = m.ScenePatch(
            patch_id=uuid4().hex,
            target_scene_id="small",
            parent_version=repo.head("small").version,
            operations=[m.TransformLayerOp(layer_id=target, dx_mm=dx)],
            modified_layer_ids=modified,
            declared_dependencies=modified,
        )
        executor.apply(patch, policy, context, dpi=72)
    current = repo.load("small")
    bounds = next(layer.bounds for layer in current.scene.layers if layer.id == "group")
    assert bounds.x_mm == 10 and bounds.width_mm == 35
