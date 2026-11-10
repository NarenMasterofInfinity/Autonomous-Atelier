"""Freeze selected visual examples as reference-only provider inputs, never story assets."""

from editorial_studio.llm.contracts import CallContext
from editorial_studio.reference_studio.catalog import proof_assets
from editorial_studio.reference_studio.models import AuthoredReference, EditorialFamily
from editorial_studio.telemetry.tools import tool_span


def capture(store, project, configuration):
    assets = []
    cards = []
    origin = configuration.get("authored_reference_project", "m10a-references")
    for key in configuration.get("authored_reference_ids", []):
        proof = store.get("authored_reference", key, AuthoredReference)
        if proof is None or proof.project_id != origin:
            raise PermissionError("reference outside selected project")
        proof_assets(store, proof)
        if proof.status != "visually_reviewed":
            raise ValueError("reference needs explicit visual review before conditioning")
        family = EditorialFamily.model_validate_json(proof.family_snapshot_json)
        ctx = CallContext(
            project_id=project,
            run_id="m10a-reference-capture",
            agent_name="ReferenceMaterial",
            stage="M10A",
        )
        with tool_span(store, ctx, "capture_authored_reference") as tool:
            asset = store.put_blob(
                project, store.read_blob(origin, proof.spread.png_asset_id), "image/png"
            )
            tool.output_asset_ids.extend([asset.id, store.json_blob(project, proof).id])
        assets.append(asset.id)
        cards.append(
            {
                "reference_id": proof.id,
                "family_id": family.id,
                "family_version": family.version,
                "principle": family.principle,
                "composition_rules": family.composition_rules,
                "suitability": family.suitability,
                "avoid": family.avoid,
                "reviewer": proof.reviewer,
                "human_approval": proof.human_approval,
                "input_role": "visual_reference_only_not_a_story_asset",
            }
        )
    return assets, cards
