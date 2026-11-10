"""No rendering capability is marked verified by schema generation."""

from typing import Literal

from editorial_studio.contracts.models import StrictModel
from editorial_studio.contracts.operation_registry import REGISTRY


class Capability(StrictModel):
    id: str
    name: str
    operation_names: list[str]
    milestone: str
    status: Literal[
        "unsupported",
        "planned",
        "technically_verified",
        "visually_reviewed",
        "artistically_verified",
    ] = "planned"


CAPABILITIES = [
    Capability(
        id="CAP_01",
        name="Silhouette Flow",
        milestone="M5",
        operation_names=["add_path", "flow_text_into_shape", "set_clip_stack"],
    ),
    Capability(
        id="CAP_02",
        name="Depth Type",
        milestone="M5",
        operation_names=["create_group", "set_z_index", "apply_mask"],
    ),
    Capability(
        id="CAP_03",
        name="Custom Lettering",
        milestone="M5",
        operation_names=["add_path", "set_glyph_transforms", "edit_path"],
    ),
    Capability(
        id="CAP_04",
        name="Fragmented Mask",
        milestone="M5",
        operation_names=["add_path", "clip_to_path", "transform_layer"],
    ),
    Capability(
        id="CAP_05",
        name="Organic Path Flow",
        milestone="M5",
        operation_names=["add_path", "text_on_path", "flow_text_into_shape"],
    ),
    Capability(
        id="CAP_06",
        name="Type Clip Mask",
        milestone="M5",
        operation_names=["add_text", "clip_to_path", "create_group"],
    ),
    Capability(
        id="CAP_07",
        name="Layer Blending",
        milestone="M5",
        operation_names=["set_blend_mode", "create_group", "set_opacity"],
    ),
    Capability(
        id="CAP_08",
        name="Gradient Composite",
        milestone="M5",
        operation_names=["gradient_mask", "set_clip_stack", "set_blend_mode"],
    ),
    Capability(
        id="CAP_09",
        name="Editorial Collage",
        milestone="M5",
        operation_names=["add_path", "clip_to_path", "gradient_mask", "set_blend_mode"],
    ),
    Capability(
        id="CAP_10",
        name="Selective Grading",
        milestone="M5",
        operation_names=["color_adjust", "gradient_mask", "apply_filter"],
    ),
]


class CapabilityCoverage(StrictModel):
    id: str
    name: str
    required_operations: list[str]
    available_operations: list[str]
    missing_operations: list[str]
    validation_complete: bool
    verification_status: str


def capability_coverage(renderer_operations: set[str]) -> list[CapabilityCoverage]:
    result = []
    for capability in CAPABILITIES:
        required = set(capability.operation_names)
        if not required <= set(REGISTRY):
            raise ValueError("capability references an unknown operation")
        result.append(
            CapabilityCoverage(
                id=capability.id,
                name=capability.name,
                required_operations=capability.operation_names,
                available_operations=sorted(required & renderer_operations),
                missing_operations=sorted(required - renderer_operations),
                validation_complete=True,
                verification_status=capability.status,
            )
        )
    return result
