import pytest

from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import PatchRejected, validate_patch


def patch(scene, operations, **overrides):
    data = dict(
        patch_id="patch",
        parent_version=scene.version,
        target_scene_id=scene.id,
        operations=operations,
        modified_layer_ids=["photo"],
        declared_dependencies=["photo"],
    )
    data.update(overrides)
    return m.ScenePatch(**data)


def test_valid_multi_layer_patch_is_non_mutating(scene, policy):
    original = scene.model_dump_json()
    p = patch(
        scene,
        [
            m.AddTextOp(
                layer_id="title",
                text_content="Quiet",
                style_name="body",
                bounds=m.BoundsMM(x_mm=4, y_mm=3, width_mm=50, height_mm=20),
            ),
            m.SetOpacityOp(layer_id="photo", opacity=0.3),
            m.SetZIndexOp(layer_id="title", z_index=5),
        ],
        created_layer_ids=["title"],
    )
    result = validate_patch(scene, p, policy)
    assert result.created_layer_ids == ["title"]
    assert scene.model_dump_json() == original


@pytest.mark.parametrize(
    "override",
    [
        {"parent_version": "old"},
        {"target_scene_id": "other"},
        {"modified_layer_ids": []},
        {"declared_dependencies": []},
    ],
)
def test_version_ownership_and_declared_sets(scene, policy, override):
    p = patch(scene, [m.SetOpacityOp(layer_id="photo", opacity=0.2)], **override)
    with pytest.raises(PatchRejected):
        validate_patch(scene, p, policy)


def test_missing_reference_fails_even_when_schema_valid(scene, policy):
    p = patch(scene, [m.SetOpacityOp(layer_id="absent", opacity=0.2)])
    with pytest.raises(PatchRejected, match="missing layer"):
        validate_patch(scene, p, policy)


@pytest.mark.parametrize(
    "change,match",
    [
        ({"readable_layer_ids": set()}, "read permission"),
        ({"writable_layer_ids": set()}, "write permission"),
        ({"allowed_operations": set()}, "outside permission"),
        ({"renderer_operations": set()}, "capability unavailable"),
    ],
)
def test_permissions_and_renderer(scene, policy, change, match):
    policy = policy.model_copy(update=change)
    with pytest.raises(PatchRejected, match=match):
        validate_patch(scene, patch(scene, [m.SetOpacityOp(layer_id="photo", opacity=0.5)]), policy)


def test_cannot_write_another_skills_layer(scene, policy):
    scene.layers[0].owner_skill_id = "other-skill"
    with pytest.raises(PatchRejected, match="owned by another"):
        validate_patch(scene, patch(scene, [m.SetOpacityOp(layer_id="photo", opacity=0.5)]), policy)


def test_asset_existence_is_project_scoped(scene, policy):
    p = patch(scene, [m.BindAssetOp(layer_id="photo", asset_id="absent", asset_type="raster")])
    with pytest.raises(PatchRejected, match="missing or inaccessible asset"):
        validate_patch(scene, p, policy)


def test_operation_order_is_enforced(scene, policy):
    p = patch(
        scene,
        [
            m.SetOpacityOp(layer_id="new", opacity=0.5),
            m.AddImageOp(layer_id="new", asset_id="asset", bounds=scene.layers[0].bounds),
        ],
        created_layer_ids=["new"],
        modified_layer_ids=[],
        declared_dependencies=["asset"],
    )
    with pytest.raises(PatchRejected, match="missing layer"):
        validate_patch(scene, p, policy)


def test_open_clip_is_rejected(scene, policy, rectangle):
    rectangle.commands.pop()
    p = patch(scene, [m.ClipToPathOp(target_layer_id="photo", path=rectangle)])
    with pytest.raises(PatchRejected, match="must be closed"):
        validate_patch(scene, p, policy)


def test_compound_clip_is_valid(scene, policy, rectangle):
    rectangle.commands += rectangle.commands.copy()
    p = patch(scene, [m.ClipToPathOp(target_layer_id="photo", path=rectangle)])
    assert validate_patch(scene, p, policy).modified_layer_ids == ["photo"]


def test_group_cycle_rejected(scene, policy):
    scene.layers += [
        m.GroupLayer(
            id="a",
            name="a",
            semantic_role="group",
            z_index=0,
            bounds=scene.layers[0].bounds,
            member_layer_ids=["b"],
        ),
        m.GroupLayer(
            id="b",
            name="b",
            semantic_role="group",
            z_index=0,
            bounds=scene.layers[0].bounds,
            member_layer_ids=["a"],
        ),
    ]
    p = patch(scene, [m.SetOpacityOp(layer_id="photo", opacity=0.3)])
    with pytest.raises(PatchRejected, match="group cycle"):
        validate_patch(scene, p, policy)


def test_wrong_mask_type_and_unknown_style(scene, policy):
    with pytest.raises(PatchRejected, match="not a mask"):
        validate_patch(
            scene,
            patch(scene, [m.ApplyMaskOp(target_layer_id="photo", mask_asset_id="asset")]),
            policy,
        )
    with pytest.raises(PatchRejected, match="typography style"):
        validate_patch(
            scene,
            patch(
                scene,
                [
                    m.AddTextOp(
                        layer_id="new",
                        text_content="Text",
                        style_name="missing",
                        bounds=scene.layers[0].bounds,
                    )
                ],
            ),
            policy,
        )


def test_invalid_operation_rolls_back_all_validation_state(scene, policy):
    before = scene.model_dump_json()
    p = patch(
        scene,
        [
            m.SetOpacityOp(layer_id="photo", opacity=0.1),
            m.SetZIndexOp(layer_id="missing", z_index=1),
        ],
    )
    with pytest.raises(PatchRejected):
        validate_patch(scene, p, policy)
    assert scene.model_dump_json() == before


def test_all_21_handlers_accept_a_prospective_typed_patch(scene, policy, rectangle):
    from editorial_studio.contracts.operation_registry import REGISTRY

    bounds = scene.layers[0].bounds
    point = m.PointMM(x_mm=0, y_mm=0)
    operations = [
        m.AddImageOp(layer_id="art", asset_id="asset", bounds=bounds),
        m.AddTextOp(layer_id="title", text_content="Quiet", style_name="body", bounds=bounds),
        m.TransformLayerOp(layer_id="photo", dx_mm=1),
        m.ClipToPathOp(target_layer_id="photo", path=rectangle),
        m.SetZIndexOp(layer_id="title", z_index=4),
        m.ApplyMaskOp(target_layer_id="photo", mask_asset_id="mask"),
        m.AddPathOp(layer_id="outline", path=rectangle),
        m.AddPathOp(layer_id="operand", path=rectangle),
        m.EditPathOp(layer_id="outline", path=rectangle),
        m.BooleanPathOp(
            target_layer_id="outline", operand_layer_id="operand", operation_type="union"
        ),
        m.TextOnPathOp(layer_id="title", text_content="Quiet", style_name="body", path=rectangle),
        m.SetGlyphTransformsOp(layer_id="title", transforms=[m.GlyphTransform(glyph_index=0)]),
        m.FlowTextIntoShapeOp(
            layer_id="title", text_content="Quiet", style_name="body", boundary=rectangle
        ),
        m.SetBlendModeOp(layer_id="photo", blend_mode="multiply"),
        m.CreateGroupOp(group_layer_id="group", member_layer_ids=["title", "art"]),
        m.SetClipStackOp(target_layer_id="photo", clip_path_layer_ids=["outline"]),
        m.ColorAdjustOp(layer_id="photo", saturation=0.5),
        m.GradientMaskOp(
            target_layer_id="photo",
            gradient_type="linear",
            start=point,
            end=m.PointMM(x_mm=5, y_mm=5),
            stops=[m.GradientStop(offset=0, opacity=0), m.GradientStop(offset=1, opacity=1)],
        ),
        m.DisplacementMapOp(target_layer_id="photo", map_asset_id="asset", scale_mm=1),
        m.ApplyFilterOp(layer_id="photo", filter=m.BlurFilter(radius_mm=1)),
        m.BindAssetOp(layer_id="photo", asset_id="asset", asset_type="raster"),
        m.SetOpacityOp(layer_id="photo", opacity=0.9),
    ]
    assert {op.op for op in operations} == set(REGISTRY)
    p = patch(
        scene,
        operations,
        created_layer_ids=["art", "title", "outline", "operand", "group"],
        declared_dependencies=["photo", "asset", "mask"],
    )
    assert validate_patch(scene, p, policy).modified_layer_ids == ["photo"]
