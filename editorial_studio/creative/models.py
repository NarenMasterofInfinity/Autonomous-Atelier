"""Concept proposals, compiler evidence, critic judgments and explicit final review."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from editorial_studio.artifacts.inspection import InspectionSet
from editorial_studio.canvas.typography.fonts import FontConfiguration, FontSpec
from editorial_studio.contracts import models as m
from editorial_studio.design_system.models import DesignTokens, FontPairing


class TextRange(m.StrictModel):
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_char <= self.start_char:
            raise ValueError("text range must contain source characters")
        return self


class AxisSetting(m.StrictModel):
    tag: str = Field(pattern=r"^[A-Za-z0-9]{4}$")
    value: float


class ConceptFont(FontSpec):
    # Structured-output objects have closed property sets. Represent optional
    # axis choices as typed rows, then freeze them into the renderer's map.
    axes: list[AxisSetting] = Field(default_factory=list)

    @field_validator("axes", mode="before")
    @classmethod
    def legacy_axis_map(cls, value):
        if isinstance(value, dict):
            return [{"tag": tag, "value": number} for tag, number in sorted(value.items())]
        return value


class ConceptTypography(FontConfiguration):
    fonts: list[ConceptFont]

    @classmethod
    def from_configuration(cls, config: FontConfiguration):
        return cls(
            fonts=[
                ConceptFont(
                    **font.model_dump(exclude={"axes"}),
                    axes=[AxisSetting(tag=tag, value=value) for tag, value in font.axes.items()],
                )
                for font in config.fonts
            ],
            styles=config.styles,
        )

    def freeze(self):
        if any(len({axis.tag for axis in font.axes}) != len(font.axes) for font in self.fonts):
            raise ValueError("duplicate font axis settings")
        return FontConfiguration(
            fonts=[
                FontSpec(
                    **font.model_dump(exclude={"axes"}),
                    axes={axis.tag: axis.value for axis in font.axes},
                )
                for font in self.fonts
            ],
            styles=self.styles,
        )


class NodeTreatment(m.StrictModel):
    node_id: str
    style_role: Literal["headline", "deck", "body", "caption", "label"] = "body"
    style_name: str | None = None
    text_range: TextRange | None = None
    layout: Literal["rect", "path", "shape", "glyphs"] = "rect"
    path: m.PathGeometry | None = None
    exclusions: list[m.PathGeometry] = Field(default_factory=list)
    glyph_transforms: list[m.GlyphTransform] = Field(default_factory=list)
    fill_color: str | None = None
    opacity: float = Field(default=1, ge=0, le=1)
    blend_mode: m.BlendMode = m.BlendMode.NORMAL
    image_treatment: Literal["native", "grain", "halftone", "monochrome"] = "native"
    gradient: m.GradientMaskOp | None = None
    image_bleed_mm: float = Field(default=0, ge=0, le=10)
    rotation_deg: float = Field(default=0, ge=-180, le=180)
    minimum_display_pt: float | None = Field(default=None, ge=18)

    @model_validator(mode="after")
    def gradient_binding(self):
        if self.gradient and self.gradient.target_layer_id != self.node_id:
            raise ValueError("gradient must target its own concept node")
        return self


class ConceptProposal(m.StrictModel):
    visual_metaphor: str
    compositional_structure: str
    photography_treatment: str
    narrative_expression: str
    graph: m.SpatialConceptGraph
    treatments: list[NodeTreatment]
    typography: ConceptTypography | None = None
    inspection_crop: m.BoundsMM | None = None
    artifact_requirements: list[m.ArtifactRequest] = Field(default_factory=list)
    required_capabilities: list[
        Literal[
            "CAP_01",
            "CAP_02",
            "CAP_03",
            "CAP_04",
            "CAP_05",
            "CAP_06",
            "CAP_07",
            "CAP_08",
            "CAP_09",
            "CAP_10",
        ]
    ] = Field(default_factory=list)
    spatial_intent: m.SpatialIntent

    @model_validator(mode="after")
    def bindings(self):
        ids = [t.node_id for t in self.treatments]
        if len(ids) != len(set(ids)) or set(ids) != {n.id for n in self.graph.nodes}:
            raise ValueError("each concept node needs exactly one treatment")
        if any(n.target_region is None or n.z_order_hint is None for n in self.graph.nodes):
            raise ValueError("all concept objects need region and z order")
        for treatment in self.treatments:
            if treatment.layout in ("path", "shape") and treatment.path is None:
                raise ValueError("advanced text treatment requires a typed path")
        return self


class CombinatorialRecipe(m.StrictModel):
    id: str
    capability_ids: list[str]
    operations: list[m.RegistryOperation]
    dependency_order: list[str]
    rationale: str
    compatibility_checks: list[str]


class CompiledConcept(m.StrictModel):
    id: str
    project_id: str
    story_id: str
    identity_id: str
    proposal: ConceptProposal
    hybrid: m.HybridConceptOutput
    compiler: m.ConceptCompilerOutput
    recipe: CombinatorialRecipe
    typography: FontConfiguration
    background_color: str
    provider_call_id: str | None = None
    identity_bible: m.ArtDirectionBible | None = None
    tokens: DesignTokens
    pairing: FontPairing
    authorship: Literal["model", "authored", "reference_adapted"] = "model"
    reference_program_id: str | None = None


class CriticAssessment(m.StrictModel):
    verdict: m.CriticVerdict
    score: float = Field(ge=0, le=1)
    findings: list[m.CritiqueFinding]
    rule_break_evaluations: list[m.RuleBreakEvaluation] = Field(default_factory=list)
    rationale: str


class CreativeReview(m.StrictModel):
    id: str
    project_id: str
    concept_id: str
    scene_id: str
    scene_version: str
    inspection: InspectionSet
    execution: CriticAssessment
    artistic: CriticAssessment | None = None
    fidelity: CriticAssessment | None = None
    decision: m.ReviewDecision
    model_call_ids: list[str]
    visual_change_from_previous: float | None = None
    run_id: str = ""
    human_approval: bool = False
    comparative_preference: Literal["current", "previous", "tie"] | None = None


class CreativeSpread(m.StrictModel):
    id: str
    project_id: str
    story_id: str
    identity_id: str
    scene_id: str
    scene_version: str
    concept_id: str
    review_id: str
    png_asset_id: str
    pdf_asset_id: str
    document_asset_id: str
    metadata_asset_id: str
    state: Literal["review", "revision_required", "approved_for_identity_review"]
    run_id: str


class FinalIdentityPackage(m.StrictModel):
    id: str
    project_id: str
    identity_id: str
    bible: m.ArtDirectionBible
    spread_ids: list[str] = Field(min_length=2, max_length=3)
    proof_versions: list[str]
    capability_proof_ids: list[str]
    proof_book_asset_id: str
    contact_sheet_asset_id: str
    structural_distances: list[float]
    source_identity_fingerprint: str = ""
    evidence_fingerprint: str = ""
    requires_critic_override: bool = False
    critic_override_recorded: bool = False
    revision: int = 0
    review_actor: str | None = None
    review_note: str | None = None
    review_verdict: Literal["approved", "revision_required"] | None = None
    reviewed_at: datetime | None = None


class ComparativeAssessment(m.StrictModel):
    preferred_image: Literal["A", "B", "tie"]
    rationale: str
    concrete_changes: list[str]


class CreativeAttempt(m.StrictModel):
    id: str
    project_id: str
    run_id: str
    proposal: ConceptProposal | None = None
    provider_call_id: str | None = None
    error: str | None = None
    spread_id: str | None = None


class CreativeBuildCheckpoint(m.StrictModel):
    id: str
    project_id: str
    story_id: str
    identity_id: str
    identity_snapshot_json: str
    mandate: str
    prompt_template: str
    prompt_version: str
    model: str
    reasoning_effort: Literal["low", "medium", "high", "xhigh"]
    max_output_tokens: int
    maximum_repairs: int
    with_visual_critics: bool
    reference_program_id: str | None = None
