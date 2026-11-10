"""Compose typed content, geometry and compositing modules with explicit dependencies."""

from pydantic import Field

from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import REGISTRY
from editorial_studio.creative.models import CombinatorialRecipe


class RecipeModule(m.StrictModel):
    id: str
    skill_id: str
    operations: list[m.RegistryOperation] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    incompatible_skill_ids: list[str] = Field(default_factory=list)


class DynamicRecipeGenerator:
    def generate(
        self,
        recipe_id,
        modules: list[RecipeModule],
        *,
        supported_operations,
        capability_ids,
        rationale,
    ):
        by_id = {module.id: module for module in modules}
        if len(by_id) != len(modules):
            raise ValueError("duplicate recipe module")
        skills = {module.skill_id for module in modules}
        visiting = set()
        visited = set()
        order = []
        for module in modules:
            if skills.intersection(module.incompatible_skill_ids):
                raise ValueError("incompatible recipe skills")
            if not set(module.depends_on) <= set(by_id):
                raise ValueError("missing recipe dependency")

        def visit(key):
            if key in visiting:
                raise ValueError("recipe dependency cycle")
            if key in visited:
                return
            visiting.add(key)
            for dependency in by_id[key].depends_on:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)
            order.append(key)

        for module in modules:
            visit(module.id)
        operations = [op for key in order for op in by_id[key].operations]
        created = set()
        layout_modes = {}
        for op in operations:
            if op.op not in REGISTRY or op.op not in supported_operations:
                raise ValueError("recipe uses unsupported operation")
            if op.op.startswith("add_") or op.op == "create_group":
                key = getattr(op, "layer_id", getattr(op, "group_layer_id", None))
                if key in created:
                    raise ValueError("recipe creates a layer twice")
                created.add(key)
            if op.op in ("text_on_path", "flow_text_into_shape"):
                prior = layout_modes.get(op.layer_id)
                if prior and prior != op.op:
                    raise ValueError("path and shape flow compete for the same text layer")
                layout_modes[op.layer_id] = op.op
        return CombinatorialRecipe(
            id=recipe_id,
            capability_ids=capability_ids,
            operations=operations,
            dependency_order=order,
            rationale=rationale,
            compatibility_checks=[
                "module dependencies resolved",
                "skill incompatibilities checked",
                "unique layer creation",
                "single text-layout mode",
                "typed registry support checked",
            ],
        )

    def from_operations(
        self, recipe_id, operations, *, supported_operations, capability_ids, rationale
    ):
        # Each operation is a typed atomic skill. Repeated access to a layer creates an
        # explicit dependency; unrelated nodes may compose without an accidental write order.
        last_access = {}
        modules = []
        for index, op in enumerate(operations):
            model = op.model_dump()
            resources = []
            for name, value in model.items():
                if name.endswith("layer_id") and isinstance(value, str):
                    resources.append(value)
                elif name.endswith("layer_ids") and isinstance(value, list):
                    resources.extend(value)
            module_id = f"{recipe_id}-{index:03d}"
            deps = list(dict.fromkeys(last_access[key] for key in resources if key in last_access))
            modules.append(
                RecipeModule(id=module_id, skill_id=op.op, operations=[op], depends_on=deps)
            )
            for key in resources:
                last_access[key] = module_id
        return self.generate(
            recipe_id,
            modules,
            supported_operations=supported_operations,
            capability_ids=capability_ids,
            rationale=rationale,
        )
