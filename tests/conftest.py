from pathlib import Path

import pytest

from editorial_studio.contracts.models import (
    BoundsMM,
    ClosePath,
    ImageLayer,
    LineTo,
    MoveTo,
    PathGeometry,
    PointMM,
    Scene,
)
from editorial_studio.contracts.operation_registry import REGISTRY, RuntimePolicy
from editorial_studio.core.storage import Store, utcnow
from editorial_studio.llm.contracts import CallContext, ProviderResult
from editorial_studio.telemetry.pricing import PricingTable


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "projects")


@pytest.fixture
def pricing():
    return PricingTable.load(Path("config/pricing.yaml"))


@pytest.fixture
def context():
    return CallContext(project_id="project", run_id="run", agent_name="TestAgent", stage="M0")


@pytest.fixture
def rectangle():
    return PathGeometry(
        commands=[
            MoveTo(p=PointMM(x_mm=0, y_mm=0)),
            LineTo(p=PointMM(x_mm=20, y_mm=0)),
            LineTo(p=PointMM(x_mm=20, y_mm=10)),
            LineTo(p=PointMM(x_mm=0, y_mm=10)),
            ClosePath(),
        ]
    )


@pytest.fixture
def scene():
    return Scene(
        id="scene",
        spread_id="spread",
        version="v1",
        width_mm=420,
        height_mm=297,
        design_language_id="bible",
        created_at=utcnow(),
        layers=[
            ImageLayer(
                id="photo",
                name="Photo",
                semantic_role="lead",
                z_index=0,
                asset_id="asset",
                bounds=BoundsMM(x_mm=0, y_mm=0, width_mm=100, height_mm=100),
            )
        ],
    )


@pytest.fixture
def policy():
    return RuntimePolicy(
        readable_layer_ids={"photo"},
        writable_layer_ids={"photo"},
        asset_ids={"asset", "mask"},
        mask_asset_ids={"mask"},
        derived_text_ids={"derived"},
        style_names={"body"},
        allowed_operations=set(REGISTRY),
        renderer_operations=set(REGISTRY),
    )


class FakeProvider:
    namespace = "fake-provider-account"

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.retrievals = 0
        self.on_execute = None
        self.recovered = None

    def execute(self, request, progress):
        self.calls += 1
        if self.on_execute:
            self.on_execute(request, progress)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def retrieve(self, response_id):
        self.retrievals += 1
        if isinstance(self.recovered, BaseException):
            raise self.recovered
        return self.recovered


@pytest.fixture
def provider_factory():
    return FakeProvider


@pytest.fixture
def text_result():
    from editorial_studio.contracts.models import UsageRecord

    return ProviderResult(
        response_id="resp_1",
        request_id="req_1",
        model_snapshot="gpt-6-luna",
        visible_text="Restraint creates emphasis.",
        usage=UsageRecord(
            input_tokens=100, cached_input_tokens=20, output_tokens=50, reasoning_tokens=30
        ),
        raw_usage={"input_tokens": 100},
    )
