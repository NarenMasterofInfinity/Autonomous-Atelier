"""Deterministically generate every normative model and union schema."""

import json
from pathlib import Path
from typing import get_origin

from pydantic import BaseModel, TypeAdapter

from editorial_studio import settings
from editorial_studio.art_direction import models as direction_models
from editorial_studio.artifacts import inspection
from editorial_studio.artifacts import models as artifact_models
from editorial_studio.canvas import models as canvas_models
from editorial_studio.canvas import repository
from editorial_studio.canvas.typography import advanced_models, fonts
from editorial_studio.content import ledger
from editorial_studio.contracts import capability_matrix, models, operation_registry
from editorial_studio.core import jobs, storage
from editorial_studio.creative import evidence, issue_models, recipes, tournament_models
from editorial_studio.creative import models as creative_models
from editorial_studio.design_system import models as design_models
from editorial_studio.llm import contracts
from editorial_studio.photos import models as photo_models
from editorial_studio.production import models as production_models
from editorial_studio.reference_studio import models as editorial_reference_models
from editorial_studio.references import registry as reference_models
from editorial_studio.segmentation import models as segmentation_models
from editorial_studio.spatial import proofs
from editorial_studio.telemetry import pricing


def schemas() -> dict[str, dict]:
    result = {}
    for module in (
        models,
        operation_registry,
        jobs,
        storage,
        contracts,
        settings,
        pricing,
        canvas_models,
        repository,
        fonts,
        capability_matrix,
        design_models,
        direction_models,
        reference_models,
        editorial_reference_models,
        photo_models,
        production_models,
        segmentation_models,
        ledger,
        advanced_models,
        proofs,
        artifact_models,
        inspection,
        creative_models,
        tournament_models,
        issue_models,
        recipes,
        evidence,
    ):
        for name, obj in vars(module).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == module.__name__
            ):
                result[name] = obj.model_json_schema()
            elif get_origin(obj) is not None and name[0].isupper():
                result[name] = TypeAdapter(obj).json_schema()
    return result


def export(destination: Path | None = None) -> int:
    destination = destination or Path(__file__).parent / "schemas"
    destination.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas().items():
        (destination / f"{name}.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n"
        )
    return len(schemas())


if __name__ == "__main__":
    print(f"Exported {export()} schemas")
