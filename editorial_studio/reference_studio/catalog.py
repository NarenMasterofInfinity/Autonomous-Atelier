"""Read manual, versioned visual families and verify their exact authored evidence."""

import yaml

from editorial_studio.contracts.capability_matrix import CAPABILITIES
from editorial_studio.creative.evidence import creative_assets
from editorial_studio.reference_studio.models import (
    AuthoredReference,
    EditorialFamily,
    ReferenceAtlas,
)
from editorial_studio.references.registry import ReferenceRegistry
from editorial_studio.settings import ROOT


def families():
    rows = [
        EditorialFamily.model_validate(r)
        for r in yaml.safe_load((ROOT / "config/editorial_families.yaml").read_text())["families"]
    ]
    if len({r.id for r in rows}) != len(rows):
        raise ValueError("duplicate editorial family")
    registry = ReferenceRegistry()
    caps = {r.id for r in CAPABILITIES}
    for r in rows:
        for key in r.reference_ids:
            registry.get(key)
        if not set(r.capability_ids) <= caps:
            raise ValueError("unknown family capability")
    return {r.id: r for r in rows}


def proof_assets(store, proof):
    family = EditorialFamily.model_validate_json(proof.family_snapshot_json)
    if (family.id, family.version, family.reference_ids) != (
        proof.family_id,
        proof.family_version,
        proof.reference_ids,
    ):
        raise ValueError("reference family differs from frozen evidence")
    if proof.project_id != proof.spread.project_id:
        raise PermissionError("reference outside project")
    return creative_assets(store, proof.spread)


def references(store, project="m10a-references", *, reviewed_only=False):
    atlases = store.list("reference_atlas", ReferenceAtlas, project)
    if atlases:
        rows = [
            store.get("authored_reference", key, AuthoredReference)
            for key in atlases[-1].reference_ids
        ]
        if any(row is None or row.project_id != project for row in rows):
            raise ValueError("atlas reference missing or outside project")
    else:
        rows = []
    return [r for r in rows if not reviewed_only or r.status == "visually_reviewed"]
