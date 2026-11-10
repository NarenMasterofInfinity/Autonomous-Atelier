"""Generate initial layout guidelines from the same tokens used by the renderer."""

from editorial_studio.art_direction.models import LayoutGuidelines
from editorial_studio.contracts.models import ArtDirectionBible, IssuePhaseDirection
from editorial_studio.design_system.system import DesignSystem
from editorial_studio.references.registry import ReferenceRegistry


def create_bible(
    identity_id: str, system: DesignSystem, reference_ids: list[str], *, pairing_id="quiet-serif"
) -> ArtDirectionBible:
    if pairing_id not in system.pairings:
        raise ValueError("unknown font pairing")
    if not reference_ids or len(reference_ids) != len(set(reference_ids)):
        raise ValueError("choose distinct visual references for the identity")
    registry = ReferenceRegistry()
    for reference_id in reference_ids:
        registry.get(reference_id)
    return ArtDirectionBible(
        id=identity_id,
        version="provisional-v1",
        approval_state="provisional",
        conceptual_identity="Careful attention to ordinary places, people, and the spaces between them.",
        font_pairing_id=pairing_id,
        palette=system.tokens.palette,
        photographic_character=[
            "Natural light and readable texture.",
            "One clear photographic lead when source photography is available.",
        ],
        signature_behaviors=[
            "A measured reading grid.",
            "Open margins and a clear headline-to-body hierarchy.",
        ],
        narrative_progression=[
            IssuePhaseDirection(
                phase_name="opening",
                emotional_role="invite",
                visual_behavior="A clear headline and generous breathing room.",
            ),
            IssuePhaseDirection(
                phase_name="reading",
                emotional_role="attend",
                visual_behavior="Consistent baselines and legible reading columns.",
            ),
        ],
        recurring_motifs=["Fine rules and restrained accent labels."],
        artistic_boundaries=[
            "Do not add effects without a narrative reason.",
            "Preserve source copy; request reallocation when a spread cannot hold it.",
        ],
        approved_visual_examples=[],
    )


def generate_guidelines(
    bible: ArtDirectionBible, system: DesignSystem, reference_ids: list[str]
) -> LayoutGuidelines:
    system.typography(bible)
    registry = ReferenceRegistry()
    for ref in reference_ids:
        registry.get(ref)
    t = system.tokens
    return LayoutGuidelines(
        font_pairing_id=bible.font_pairing_id,
        body_size_pt=t.type_scale.size("body"),
        headline_size_pt=t.type_scale.size("headline"),
        baseline_step_mm=t.grid.baseline_step_mm,
        fold_safe_mm=t.grid.fold_safe_mm,
        columns_per_page=t.grid.columns_per_page,
        palette_roles={p.name: p.hex_color for p in bible.palette},
        photographic_character=bible.photographic_character,
        composition_rules=[
            f"Use {t.body_span_columns} grid columns for the reading measure.",
            f"Use {t.grid.columns_per_page} reading columns per page with {t.grid.column_gap_mm:g} mm gaps.",
            f"Keep reading type {t.grid.fold_safe_mm:g} mm from either side of the fold.",
            f"Align body baselines to a {t.grid.baseline_step_mm:g} mm rhythm.",
            f"Keep body copy at or above {t.minimum_body_pt:g} pt.",
        ],
        copyfit_actions=["adjust_frame", "alternate_style", "editorial_edit", "repaginate"],
        reference_ids=reference_ids,
    )
