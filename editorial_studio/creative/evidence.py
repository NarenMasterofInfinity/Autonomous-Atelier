"""Stable identity and proof bindings for final-review transactions."""

import hashlib
import json

from editorial_studio.contracts import models as m


class FinalBiblePublication(m.StrictModel):
    id: str
    project_id: str
    package_id: str
    package_revision: int
    bible: m.ArtDirectionBible


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def bible_foundation(bible):
    return bible.model_dump(
        mode="json",
        exclude={"approval_state", "approved_visual_examples", "final_proof_spread_ids"},
    )


def identity_fingerprint(identity):
    return digest(
        {
            "bible": bible_foundation(identity.bible),
            "tokens": identity.tokens.model_dump(mode="json"),
            "pairing": identity.pairing.model_dump(mode="json"),
            "proofs": [p.model_dump(mode="json") for p in identity.proofs],
        }
    )


def capability_binding(proof):
    return proof.model_dump(mode="json", exclude={"status", "reviewer", "review_note"})


def evidence_fingerprint(spreads, concepts, reviews, capabilities):
    return digest(
        {
            "spreads": [s.model_dump(mode="json") for s in spreads],
            "concepts": [c.model_dump(mode="json") for c in concepts],
            "reviews": [r.model_dump(mode="json") for r in reviews],
            "capabilities": [capability_binding(c) for c in capabilities],
        }
    )


def creative_assets(store, spread):
    from editorial_studio.creative.models import CompiledConcept, CreativeReview

    project = spread.project_id
    concept = store.get("concept", spread.concept_id, CompiledConcept)
    review = store.get("creative_review", spread.review_id, CreativeReview)
    if (
        concept is None
        or review is None
        or concept.project_id != project
        or review.project_id != project
        or (review.concept_id, review.scene_id, review.scene_version)
        != (concept.id, spread.scene_id, spread.scene_version)
    ):
        raise ValueError("creative proof evidence is missing or mismatched")
    assets = {
        spread.png_asset_id,
        spread.pdf_asset_id,
        spread.document_asset_id,
        spread.metadata_asset_id,
        concept.hybrid.sketch.asset_id,
        review.inspection.source_png_asset_id,
        review.inspection.full_asset_id,
        review.inspection.thumbnail_asset_id,
        review.inspection.crop_asset_id,
    }
    assets.update(
        element.mapped_asset_id
        for element in concept.compiler.extracted_visual_elements
        if element.mapped_asset_id
        and element.mapped_asset_id
        not in {request.id for request in concept.proposal.artifact_requirements}
    )
    for asset in assets:
        store.read_blob(project, asset)
    return sorted(assets)


def package_assets(store, package):
    from editorial_studio.creative.models import CreativeSpread
    from editorial_studio.spatial.proofs import CapabilityProof

    assets = {package.proof_book_asset_id, package.contact_sheet_asset_id}
    for spread_id in package.spread_ids:
        spread = store.get("creative_spread", spread_id, CreativeSpread)
        if spread is None or spread.project_id != package.project_id:
            raise ValueError("package creative proof is missing")
        assets.update(creative_assets(store, spread))
    for proof_id in package.capability_proof_ids:
        proof = store.get("capability_proof", proof_id, CapabilityProof)
        if proof is None or proof.project_id != package.project_id:
            raise ValueError("package technique proof is missing")
        assets.update(
            (
                proof.png_asset_id,
                proof.pdf_asset_id,
                proof.document_asset_id,
                proof.metadata_asset_id,
                proof.thumbnail_asset_id,
                proof.crop_asset_id,
            )
        )
    for asset in assets:
        store.read_blob(package.project_id, asset)
    return sorted(assets)
