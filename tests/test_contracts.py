import json
import math
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from editorial_studio.contracts import models as m
from editorial_studio.contracts.export import schemas
from editorial_studio.contracts.operation_registry import REGISTRY, Validator


def test_committed_schemas_match_all_models():
    expected = schemas()
    folder = Path("editorial_studio/contracts/schemas")
    assert {p.stem for p in folder.glob("*.json")} == set(expected)
    for name, schema in expected.items():
        assert json.loads((folder / f"{name}.json").read_text()) == schema
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False


def test_registry_is_exact_typed_union_and_handlers():
    union = get_args(get_args(m.RegistryOperation)[0])
    assert len(REGISTRY) == len(union) == 21
    assert set(get_args(m.OperationName)) == set(REGISTRY)
    assert {d.model for d in REGISTRY.values()} == set(union)
    assert all(callable(getattr(Validator, d.handler)) for d in REGISTRY.values())
    assert "set_opacity" in REGISTRY


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_coordinates_reject_nonfinite(value):
    with pytest.raises(ValidationError):
        m.PointMM(x_mm=value, y_mm=0)


@pytest.mark.parametrize(
    "data",
    [
        {"x_mm": 0, "y_mm": 0, "width_mm": -1, "height_mm": 3},
        {"x_mm": 0, "y_mm": 0, "width_mm": 1, "height_mm": 0},
        {"x_mm": 0, "y_mm": 0, "width_mm": 1, "height_mm": 3, "unit": "px"},
    ],
)
def test_impossible_or_unknown_bounds(data):
    with pytest.raises(ValidationError):
        m.BoundsMM.model_validate(data)


@pytest.mark.parametrize(
    "data",
    [
        {"op": "arbitrary_python", "code": "print(1)"},
        {"op": "set_opacity", "layer_id": "x", "opacity": 2},
        {"op": "set_opacity", "layer_id": "x", "opacity": -0.1},
        {"op": "transform_layer", "layer_id": "x", "scale_x": 0},
        {"op": "apply_filter", "layer_id": "x", "filter": {"kind": "blur", "radius_mm": -1}},
        {"op": "set_glyph_transforms", "layer_id": "x", "transforms": [[1, 2]]},
        {"op": "set_z_index", "layer_id": "x", "z_index": 3, "secret": "unknown"},
    ],
)
def test_bad_operation_parameters(data):
    with pytest.raises(ValidationError):
        TypeAdapter(m.RegistryOperation).validate_python(data)


@pytest.mark.parametrize(
    "commands",
    [
        [{"cmd": "L", "p": {"x_mm": 0, "y_mm": 0}}, {"cmd": "Z"}],
        [{"cmd": "M", "p": {"x_mm": 0, "y_mm": 0}}, {"cmd": "Z"}],
        [
            {"cmd": "M", "p": {"x_mm": 0, "y_mm": 0}},
            {"cmd": "L", "p": {"x_mm": 1, "y_mm": 1}},
            {"cmd": "Z"},
            {"cmd": "Z"},
        ],
        [{"cmd": "M", "p": {"x_mm": 0, "y_mm": 0}}, {"cmd": "C", "p": {"x_mm": 1, "y_mm": 1}}],
    ],
)
def test_bad_path_topology(commands):
    with pytest.raises(ValidationError):
        m.PathGeometry(commands=commands)


def test_compound_closed_curves_and_typed_filter(rectangle):
    p = m.PointMM(x_mm=2, y_mm=3)
    curve = [
        m.MoveTo(p=p),
        m.QuadraticTo(control=p, p=p),
        m.CubicTo(control1=p, control2=p, p=p),
        m.ClosePath(),
    ]
    path = m.PathGeometry(commands=rectangle.commands + curve, fill_rule="evenodd")
    assert len(path.commands) == 9
    op = TypeAdapter(m.RegistryOperation).validate_python(
        {
            "op": "apply_filter",
            "layer_id": "photo",
            "filter": {"kind": "grain", "strength": 0.2, "random_seed": 42},
        }
    )
    assert isinstance(op.filter, m.GrainFilter)


def test_gradient_stops_must_be_sorted_and_unique():
    with pytest.raises(ValidationError):
        m.GradientMaskOp(
            target_layer_id="a",
            gradient_type="linear",
            start=m.PointMM(x_mm=0, y_mm=0),
            end=m.PointMM(x_mm=1, y_mm=1),
            stops=[m.GradientStop(offset=1, opacity=0), m.GradientStop(offset=0, opacity=1)],
        )


def test_duplicate_layers(scene):
    with pytest.raises(ValidationError):
        m.Scene.model_validate({**scene.model_dump(), "layers": scene.layers * 2})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"input_tokens": 2, "cached_input_tokens": 3},
        {"output_tokens": 2, "reasoning_tokens": 3},
        {"image_input_tokens": -1},
    ],
)
def test_token_subsets(kwargs):
    with pytest.raises(ValidationError):
        m.UsageRecord(**kwargs)


def test_missing_usage_and_cost_are_nullable():
    assert set(m.UsageRecord().model_dump().values()) == {None}
    cost = m.CostRecord(certainty="unknown", pricing_version="v1")
    assert cost.estimated_cost_usd is None and cost.reported_cost_usd is None


def test_provenance_requires_real_ranges_and_approval():
    with pytest.raises(ValidationError):
        m.SourceSpan(source_block_id="b", source_revision_id="r", start_char=5, end_char=4)
    span = m.SourceSpan(source_block_id="b", source_revision_id="r", start_char=0, end_char=4)
    with pytest.raises(ValidationError):
        m.CoverageAssignment(span=span, status="omitted_approved")


def test_every_normative_class_has_a_valid_reference_fixture():
    fixtures = json.loads(Path("tests/fixtures/contracts.json").read_text())
    models = {
        name: obj
        for name, obj in vars(m).items()
        if isinstance(obj, type) and issubclass(obj, m.StrictModel) and obj.__module__ == m.__name__
    }
    assert fixtures.keys() == models.keys()
    for name, model in models.items():
        parsed = model.model_validate(fixtures[name])
        assert model.model_validate_json(parsed.model_dump_json()) == parsed
