"""Representative creative proofs and atomic human approval of the exact final Bible."""

from io import BytesIO
from itertools import combinations

import pymupdf
from PIL import Image, ImageDraw

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.canvas.repository import SceneHead, SceneRepository, key
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import utcnow
from editorial_studio.creative.critics import configuration
from editorial_studio.creative.evidence import (
    FinalBiblePublication,
    bible_foundation,
    capability_binding,
    digest,
    evidence_fingerprint,
    identity_fingerprint,
)
from editorial_studio.creative.models import (
    CompiledConcept,
    CreativeReview,
    CreativeSpread,
    FinalIdentityPackage,
)
from editorial_studio.photos.pipeline import png
from editorial_studio.spatial.proofs import CapabilityProof
from editorial_studio.telemetry.tools import tool_span


def structural_distance(a: CompiledConcept, b: CompiledConcept):
    def groups(compiled):
        treatments = {t.node_id: t for t in compiled.proposal.treatments}
        result = {}
        for node in compiled.proposal.graph.nodes:
            role = treatments[node.id].style_role if node.role == "text" else node.role
            r = node.target_region
            result.setdefault(role, []).append((r.x, r.y, r.width, r.height))
        return {role: sorted(regions) for role, regions in result.items()}

    left, right = groups(a), groups(b)
    differences = []
    for role in left.keys() | right.keys():
        x, y = left.get(role, []), right.get(role, [])
        differences.extend([1.0] * abs(len(x) - len(y)))
        differences.extend(
            sum(abs(u - v) for u, v in zip(p, q, strict=True)) / 4
            for p, q in zip(x, y, strict=False)
        )
    return sum(differences) / max(len(differences), 1)


def package_identity(store, context, identity_id, spread_ids, capability_proof_ids):
    old = store.get("final_identity_package", context.run_id, FinalIdentityPackage)
    if old:
        if (
            old.project_id != context.project_id
            or old.identity_id != identity_id
            or old.spread_ids != spread_ids
            or old.capability_proof_ids != capability_proof_ids
        ):
            raise PermissionError("package project mismatch")
        for asset in (old.proof_book_asset_id, old.contact_sheet_asset_id):
            store.read_blob(context.project_id, asset)
        if old.source_identity_fingerprint and old.evidence_fingerprint:
            from editorial_studio.creative.evidence import package_assets

            package_assets(store, old)
            return old
        if old.review_verdict is not None:
            raise ValueError("legacy reviewed package requires a fresh proof package")
    identity = store.get("identity", identity_id, ProvisionalIdentity)
    if identity is None or identity.project_id != context.project_id:
        raise PermissionError("identity not in project")
    if len(spread_ids) not in (2, 3) or len(set(spread_ids)) != len(spread_ids):
        raise ValueError("two or three distinct creative spreads required")
    spreads = []
    concepts = []
    reviews = []
    for spread_id in spread_ids:
        spread = store.get("creative_spread", spread_id, CreativeSpread)
        if (
            spread is None
            or spread.project_id != context.project_id
            or spread.identity_id != identity_id
        ):
            raise PermissionError("creative proof input mismatch")
        if (
            SceneRepository(store, context.project_id).head(spread.scene_id).version
            != spread.scene_version
        ):
            raise ValueError("creative proof changed; rebuild package")
        review = store.get("creative_review", spread.review_id, CreativeReview)
        if review is None or review.execution.verdict != m.CriticVerdict.ACCEPT:
            raise ValueError("representative spread has unresolved technical defects")
        if review.artistic is None or review.fidelity is None:
            raise ValueError("representative spread requires both visual critic passes")
        if (review.project_id, review.concept_id, review.scene_id, review.scene_version) != (
            context.project_id,
            spread.concept_id,
            spread.scene_id,
            spread.scene_version,
        ):
            raise ValueError("critic review does not bind this exact proof")
        concept = store.get("concept", spread.concept_id, CompiledConcept)
        if concept.compiler.unsupported_features:
            raise ValueError("unsupported concept features remain")
        if (
            concept.tokens != identity.tokens
            or concept.pairing != identity.pairing
            or concept.hybrid.concept_brief.project_id != context.project_id
        ):
            raise ValueError("creative proof does not use this identity snapshot")
        for asset in (
            spread.png_asset_id,
            spread.pdf_asset_id,
            spread.document_asset_id,
            spread.metadata_asset_id,
        ):
            store.read_blob(context.project_id, asset)
        spreads.append(spread)
        concepts.append(concept)
        reviews.append(review)
    distances = [structural_distance(a, b) for a, b in combinations(concepts, 2)]
    if any(d < configuration()["minimum_structural_distance"] for d in distances):
        raise ValueError("representative spreads need distinct structural compositions")
    cap_proofs = [
        store.get("capability_proof", proof_id, CapabilityProof)
        for proof_id in capability_proof_ids
    ]
    if (
        len(cap_proofs) != 10
        or any(p is None or p.project_id != context.project_id for p in cap_proofs)
        or {p.capability_id for p in cap_proofs} != {f"CAP_{i:02d}" for i in range(1, 11)}
    ):
        raise ValueError("all ten project-scoped technique proofs required")
    for proof in cap_proofs:
        from editorial_studio.contracts.capability_matrix import CAPABILITIES

        required = next(c.operation_names for c in CAPABILITIES if c.id == proof.capability_id)
        if not set(required) <= set(proof.operation_names):
            raise ValueError("technique proof does not exercise its capability")
        version = SceneRepository(store, context.project_id).version(
            proof.scene_id, proof.scene_version
        )
        patch = (
            store.get("scene_patch", version.patch_id, m.ScenePatch) if version.patch_id else None
        )
        if patch is None or {op.op for op in patch.operations} != set(proof.operation_names):
            raise ValueError("technique evidence does not match committed operations")
        for asset in (
            proof.png_asset_id,
            proof.pdf_asset_id,
            proof.document_asset_id,
            proof.metadata_asset_id,
            proof.thumbnail_asset_id,
            proof.crop_asset_id,
        ):
            store.read_blob(context.project_id, asset)
    with tool_span(store, context, "assemble_creative_identity_proofs") as tool:
        book = pymupdf.open()
        sheet = Image.new("RGB", (len(spreads) * 600, 460), "#e6e3dc")
        draw = ImageDraw.Draw(sheet)
        for i, spread in enumerate(spreads):
            with pymupdf.open(
                stream=store.read_blob(context.project_id, spread.pdf_asset_id), filetype="pdf"
            ) as page:
                book.insert_pdf(page)
            image = Image.open(
                BytesIO(store.read_blob(context.project_id, spread.png_asset_id))
            ).convert("RGB")
            image.thumbnail((580, 410))
            sheet.paste(image, (i * 600 + 10, 35))
            draw.text((i * 600 + 10, 10), spread.id, fill="#22211f")
        pdf = store.put_blob(
            context.project_id, book.tobytes(garbage=4, deflate=True), "application/pdf"
        )
        book.close()
        contact = store.put_blob(context.project_id, png(sheet), "image/png")
        bible = identity.bible.model_copy(deep=True)
        bible.final_proof_spread_ids = [s.scene_id for s in spreads]
        result = FinalIdentityPackage(
            id=context.run_id,
            project_id=context.project_id,
            identity_id=identity_id,
            bible=bible,
            spread_ids=spread_ids,
            proof_versions=[s.scene_version for s in spreads],
            capability_proof_ids=capability_proof_ids,
            proof_book_asset_id=pdf.id,
            contact_sheet_asset_id=contact.id,
            structural_distances=distances,
            source_identity_fingerprint=identity_fingerprint(identity),
            evidence_fingerprint=evidence_fingerprint(spreads, concepts, reviews, cap_proofs),
            requires_critic_override=any(
                review.decision.verdict != m.CriticVerdict.ACCEPT for review in reviews
            ),
        )
        store.put_records(("final_identity_package", result.id, context.project_id, result))
        tool.output_asset_ids.extend(
            [pdf.id, contact.id, store.json_blob(context.project_id, result).id]
        )
        return result


def approve_final_identity(
    store,
    context,
    package_id,
    *,
    expected_revision,
    actor,
    note,
    verdict,
    reviewed_techniques,
    override_critic_recommendations=False,
):
    if verdict not in ("approved", "revision_required") or not actor.strip() or not note.strip():
        raise ValueError("explicit reviewer, note and verdict required")
    package = store.get("final_identity_package", package_id, FinalIdentityPackage)
    if package is None or package.project_id != context.project_id:
        raise PermissionError("package not in project")
    if package.revision != expected_revision:
        raise ValueError("stale final review")
    original_package_digest = digest(package.model_dump(mode="json"))
    identity = store.get("identity", package.identity_id, ProvisionalIdentity)
    if verdict == "approved" and (
        identity is None or identity.review is None or identity.review.verdict != "approved"
    ):
        raise ValueError("provisional identity approval is required before final approval")
    if verdict == "approved" and not reviewed_techniques:
        raise ValueError("review the R1 technique contact sheet before final approval")
    if verdict == "approved" and (
        not package.source_identity_fingerprint
        or identity_fingerprint(identity) != package.source_identity_fingerprint
        or bible_foundation(package.bible) != bible_foundation(identity.bible)
    ):
        raise ValueError("identity snapshot changed after packaging; rebuild the proof package")
    if (
        verdict == "approved"
        and package.requires_critic_override
        and not override_critic_recommendations
    ):
        raise ValueError(
            "critics requested revision; explicit override and review rationale required"
        )
    spreads = [
        store.get("creative_spread", spread_id, CreativeSpread) for spread_id in package.spread_ids
    ]
    if any(s is None or s.project_id != context.project_id for s in spreads):
        raise ValueError("creative proofs missing")
    for asset in (package.proof_book_asset_id, package.contact_sheet_asset_id):
        store.read_blob(context.project_id, asset)
    for spread in spreads:
        for asset in (
            spread.png_asset_id,
            spread.pdf_asset_id,
            spread.document_asset_id,
            spread.metadata_asset_id,
        ):
            store.read_blob(context.project_id, asset)
    cap_proofs = [
        store.get("capability_proof", proof_id, CapabilityProof)
        for proof_id in package.capability_proof_ids
    ]
    if any(p is None or p.project_id != context.project_id for p in cap_proofs):
        raise ValueError("technique proof missing")
    concepts = [store.get("concept", spread.concept_id, CompiledConcept) for spread in spreads]
    reviews = [store.get("creative_review", spread.review_id, CreativeReview) for spread in spreads]
    if (
        any(row is None for row in concepts + reviews)
        or evidence_fingerprint(spreads, concepts, reviews, cap_proofs)
        != package.evidence_fingerprint
    ):
        raise ValueError("proof or critic evidence changed after packaging")
    evidence_rows = (
        [("creative_spread", row.id, row) for row in spreads]
        + [("concept", row.id, row) for row in concepts]
        + [("creative_review", row.id, row) for row in reviews]
        + [("capability_proof", row.id, row) for row in cap_proofs]
    )
    for proof in cap_proofs:
        for asset in (
            proof.png_asset_id,
            proof.pdf_asset_id,
            proof.document_asset_id,
            proof.metadata_asset_id,
            proof.thumbnail_asset_id,
            proof.crop_asset_id,
        ):
            store.read_blob(context.project_id, asset)
    package.review_actor = actor.strip()
    package.review_note = note.strip()
    package.review_verdict = verdict
    package.reviewed_at = utcnow()
    package.revision += 1
    package.critic_override_recorded = bool(
        verdict == "approved"
        and package.requires_critic_override
        and override_critic_recommendations
    )
    package.bible.approval_state = "final" if verdict == "approved" else "revision_required"
    if verdict == "approved":
        package.bible.approved_visual_examples = list(
            dict.fromkeys(
                package.bible.approved_visual_examples + [s.png_asset_id for s in spreads]
            )
        )
    event = m.WorkflowEvent(
        event_id=context.run_id,
        project_id=context.project_id,
        run_id=context.run_id,
        timestamp=utcnow(),
        payload=m.DecisionEvent(
            decision_id=context.run_id, verdict="ACCEPT" if verdict == "approved" else "REVISE"
        ),
    )
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT payload FROM records WHERE kind='final_identity_package' AND id=?",
            (package_id,),
        ).fetchone()
        if (
            digest(FinalIdentityPackage.model_validate_json(current[0]).model_dump(mode="json"))
            != original_package_digest
        ):
            raise ValueError("package changed during review")
        for kind, record_id, expected in evidence_rows:
            row = db.execute(
                "SELECT payload FROM records WHERE kind=? AND id=? AND project_id=?",
                (kind, record_id, context.project_id),
            ).fetchone()
            actual = type(expected).model_validate_json(row[0]) if row else None
            normalized = (
                capability_binding
                if kind == "capability_proof"
                else lambda value: value.model_dump(mode="json")
            )
            if actual is None or normalized(actual) != normalized(expected):
                raise ValueError("review evidence changed during final approval")
        if verdict == "approved":
            row = db.execute(
                "SELECT payload FROM records WHERE kind='identity' AND id=? AND project_id=?",
                (identity.id, context.project_id),
            ).fetchone()
            current_identity = ProvisionalIdentity.model_validate_json(row[0]) if row else None
            if (
                current_identity is None
                or current_identity.revision != identity.revision
                or current_identity.review is None
                or current_identity.review.verdict != "approved"
                or identity_fingerprint(current_identity) != package.source_identity_fingerprint
            ):
                raise ValueError("provisional identity changed during final review")
            for proof in current_identity.proofs:
                row = db.execute(
                    "SELECT payload FROM records WHERE kind='scene_head' AND id=?",
                    (key(context.project_id, proof.scene_id),),
                ).fetchone()
                if (
                    row is None
                    or SceneHead.model_validate_json(row[0]).version != proof.scene_version
                ):
                    raise ValueError("provisional identity proof changed before final review")
        for spread, expected in zip(spreads, package.proof_versions, strict=True):
            row = db.execute(
                "SELECT payload FROM records WHERE kind='scene_head' AND id=?",
                (key(context.project_id, spread.scene_id),),
            ).fetchone()
            if row is None or SceneHead.model_validate_json(row[0]).version != expected:
                raise ValueError("proof changed during final review")
        for proof in cap_proofs:
            row = db.execute(
                "SELECT payload FROM records WHERE kind='scene_head' AND id=?",
                (key(context.project_id, proof.scene_id),),
            ).fetchone()
            if row is None or SceneHead.model_validate_json(row[0]).version != proof.scene_version:
                raise ValueError("technique proof changed during final review")
        entries = [
            ("final_identity_package", package.id, package),
            ("final_identity_review", context.run_id, package),
            ("event", event.event_id, event),
        ]
        if verdict == "approved":
            entries.append(("final_bible", package.bible.id, package.bible))
            publication = FinalBiblePublication(
                id=package.bible.id,
                project_id=context.project_id,
                package_id=package.id,
                package_revision=package.revision,
                bible=package.bible,
            )
            entries.append(("final_bible_publication", publication.id, publication))
            for proof in cap_proofs:
                proof.status = "artistically_verified"
                proof.reviewer = actor.strip()
                proof.review_note = note.strip()
                entries.append(("capability_proof", proof.id, proof))
        else:
            row = db.execute(
                "SELECT payload FROM records WHERE kind='final_bible_publication' AND id=? AND project_id=?",
                (package.bible.id, context.project_id),
            ).fetchone()
            if row and FinalBiblePublication.model_validate_json(row[0]).package_id == package.id:
                db.execute(
                    "DELETE FROM records WHERE kind='final_bible' AND id=? AND project_id=?",
                    (package.bible.id, context.project_id),
                )
                db.execute(
                    "DELETE FROM records WHERE kind='final_bible_publication' AND id=? AND project_id=?",
                    (package.bible.id, context.project_id),
                )
        for kind, record_id, model in entries:
            db.execute(
                "INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (
                    kind,
                    record_id,
                    context.project_id,
                    model.model_dump_json(),
                    utcnow().isoformat(),
                ),
            )
    return package
