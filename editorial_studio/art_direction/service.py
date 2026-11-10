"""Resumable provisional identity proofs and explicit, proof-bound review."""

import hashlib
from io import BytesIO
from uuid import uuid4

import pymupdf
import yaml
from PIL import Image, ImageDraw

from editorial_studio.art_direction.bible import create_bible, generate_guidelines
from editorial_studio.art_direction.models import (
    IdentityBuildCheckpoint,
    IdentityProof,
    IdentityReview,
    ProvisionalIdentity,
)
from editorial_studio.canvas.executor import Executor
from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.renderer import Renderer
from editorial_studio.canvas.repository import SceneHead, SceneRepository
from editorial_studio.canvas.repository import key as scene_key
from editorial_studio.contracts.capability_matrix import capability_coverage
from editorial_studio.contracts.models import DecisionEvent, PaletteToken, WorkflowEvent
from editorial_studio.core.storage import Store, utcnow
from editorial_studio.design_system.layout import BaselineComposer
from editorial_studio.design_system.models import BaselineStory, PairingCatalog
from editorial_studio.design_system.system import DesignSystem
from editorial_studio.llm.contracts import CallContext
from editorial_studio.settings import ROOT
from editorial_studio.telemetry.tools import tool_span

DEFAULT_REFERENCES = ["citizen-18", "citizen-27", "guggenheim-03", "guggenheim-04", "413-06"]


def load_stories() -> list[BaselineStory]:
    return [
        BaselineStory.model_validate(row)
        for row in yaml.safe_load((ROOT / "config/m2_stories.yaml").read_text())["stories"]
    ]


def identity_assets(identity: ProvisionalIdentity) -> list[str]:
    assets = {
        asset
        for proof in identity.proofs
        for asset in [
            proof.document_asset_id,
            proof.png_asset_id,
            proof.pdf_asset_id,
            proof.metadata_asset_id,
        ]
    }
    assets.update(
        asset for asset in [identity.proof_book_asset_id, identity.contact_sheet_asset_id] if asset
    )
    return sorted(assets)


def build_identity(
    store: Store,
    context: CallContext,
    *,
    pairing_id="quiet-serif",
    reference_ids: list[str] | None = None,
    photo_asset_id: str | None = None,
    stories: list[BaselineStory] | None = None,
    palette: list[PaletteToken] | None = None,
    dpi=144,
    system: DesignSystem | None = None,
) -> ProvisionalIdentity:
    identity_id = context.run_id
    completed = store.get("identity", identity_id, ProvisionalIdentity)
    if completed:
        if completed.project_id != context.project_id:
            raise PermissionError("identity belongs to another project")
        for asset in identity_assets(completed):
            store.read_blob(context.project_id, asset)
        return completed
    checkpoint = store.get("identity_build", identity_id, IdentityBuildCheckpoint)
    if checkpoint is None:
        system = system or DesignSystem()
        if palette is not None:
            system.tokens.palette = palette
        selected = reference_ids if reference_ids is not None else DEFAULT_REFERENCES
        bible = create_bible(identity_id, system, selected, pairing_id=pairing_id)
        inputs = stories if stories is not None else load_stories()
        if len(inputs) != 3 or len({s.id for s in inputs}) != 3:
            raise ValueError("M2 identity proofs require three distinct stories")
        if photo_asset_id:
            store.read_blob(context.project_id, photo_asset_id)
            inputs = [
                s.model_copy(
                    update={"photo_asset_id": photo_asset_id if s.layout != "essay" else None}
                )
                for s in inputs
            ]
        bible.provisional_proof_spread_ids = [f"{identity_id}-{s.id}" for s in inputs]
        checkpoint = IdentityBuildCheckpoint(
            id=identity_id,
            project_id=context.project_id,
            run_id=context.run_id,
            bible=bible,
            tokens=system.tokens,
            pairing=system.pairings[pairing_id],
            font_configuration=system.fonts.config,
            stories=inputs,
            guidelines=generate_guidelines(bible, system, selected),
            created_at=utcnow(),
            render_dpi=dpi,
        )
        store.put_records(("identity_build", identity_id, context.project_id, checkpoint))
    if checkpoint.project_id != context.project_id:
        raise PermissionError("checkpoint belongs to another project")
    system = DesignSystem(
        tokens=checkpoint.tokens,
        pairing_catalog=PairingCatalog(pairings=[checkpoint.pairing]),
        font_configuration=checkpoint.font_configuration,
    )
    composer = BaselineComposer(system, checkpoint.bible)
    repository = SceneRepository(store, context.project_id)
    executor = Executor(repository, Renderer(store, context.project_id))
    proofs = []
    for story, scene_id in zip(
        checkpoint.stories, checkpoint.bible.provisional_proof_spread_ids, strict=True
    ):
        proof_context = context.model_copy(update={"spread_id": scene_id})
        with tool_span(store, proof_context, "compile_baseline") as tool:
            document, report = composer.compose(story, scene_id)
            document.scene.created_at = checkpoint.created_at
            document.scene.version = hashlib.sha256(scene_id.encode()).hexdigest()
            tool.output_asset_ids.append(store.json_blob(context.project_id, report).id)
        try:
            version = repository.head(scene_id)
        except KeyError:
            version = None
        if version:
            if version.run_id != context.run_id:
                raise ValueError("proof scene belongs to another run")
            prior = CanvasDocument.model_validate_json(
                store.read_blob(context.project_id, version.document_asset_id)
            )
            if prior != document:
                raise ValueError("committed proof differs from the frozen identity build input")
            for asset in [version.png_asset_id, version.pdf_asset_id, version.metadata_asset_id]:
                store.read_blob(context.project_id, asset)
        else:
            version = executor.initialize(document, proof_context, dpi=checkpoint.render_dpi)
        proofs.append(
            IdentityProof(
                story_id=story.id,
                scene_id=scene_id,
                scene_version=version.version,
                document_asset_id=version.document_asset_id,
                png_asset_id=version.png_asset_id,
                pdf_asset_id=version.pdf_asset_id,
                metadata_asset_id=version.metadata_asset_id,
                report=report,
            )
        )
    with tool_span(store, context, "assemble_identity_proofs") as tool:
        book = pymupdf.open()
        sheet = Image.new("RGB", (1200, 340), "#e6e3dc")
        draw = ImageDraw.Draw(sheet)
        for index, proof in enumerate(proofs):
            with pymupdf.open(
                stream=store.read_blob(context.project_id, proof.pdf_asset_id), filetype="pdf"
            ) as pdf:
                book.insert_pdf(pdf)
            image = Image.open(
                BytesIO(store.read_blob(context.project_id, proof.png_asset_id))
            ).convert("RGB")
            image.thumbnail((390, 280))
            sheet.paste(
                image, (index * 400 + (400 - image.width) // 2, 45 + (280 - image.height) // 2)
            )
            draw.text((index * 400 + 10, 15), proof.story_id, fill="#22211f")
        pdf_asset = store.put_blob(
            context.project_id, book.tobytes(garbage=4, deflate=True), "application/pdf"
        )
        book.close()
        output = BytesIO()
        sheet.save(output, format="PNG")
        contact_asset = store.put_blob(context.project_id, output.getvalue(), "image/png")
        tool.output_asset_ids.extend([pdf_asset.id, contact_asset.id])
    identity = ProvisionalIdentity(
        typography=system.typography(checkpoint.bible),
        id=identity_id,
        project_id=context.project_id,
        run_id=context.run_id,
        bible=checkpoint.bible,
        pairing=checkpoint.pairing,
        tokens=checkpoint.tokens,
        guidelines=checkpoint.guidelines,
        proofs=proofs,
        capabilities=capability_coverage(executor.supported_operations),
        proof_book_asset_id=pdf_asset.id,
        contact_sheet_asset_id=contact_asset.id,
        created_at=checkpoint.created_at,
    )
    store.put_records(("identity", identity.id, context.project_id, identity))
    return identity


def review_identity(
    store: Store,
    context: CallContext,
    identity_id: str,
    *,
    expected_revision: int,
    actor: str,
    verdict: str,
    note: str,
) -> ProvisionalIdentity:
    identity = store.get("identity", identity_id, ProvisionalIdentity)
    if identity is None or identity.project_id != context.project_id:
        raise PermissionError("identity is not in this project")
    if identity.revision != expected_revision:
        raise ValueError("identity review is stale")
    if len(identity.proofs) != 3:
        raise ValueError("three rendered proofs are required before review")
    if not identity.proof_book_asset_id or not identity.contact_sheet_asset_id:
        raise ValueError("rebuild the identity to include its complete proof package before review")
    repository = SceneRepository(store, context.project_id)
    for proof in identity.proofs:
        if repository.head(proof.scene_id).version != proof.scene_version:
            raise ValueError(
                "proof changed after identity generation; rebuild the identity before review"
            )
    for asset in identity_assets(identity):
        store.read_blob(context.project_id, asset)
    review = IdentityReview(
        id=context.run_id,
        actor=actor,
        verdict=verdict,
        note=note,
        reviewed_at=utcnow(),
        reviewed_proof_versions=[p.scene_version for p in identity.proofs],
    )
    identity.bible.approval_state = "provisional" if verdict == "approved" else "revision_required"
    identity.bible.approved_visual_examples = (
        identity.guidelines.reference_ids if verdict == "approved" else []
    )
    identity.review = review
    identity.revision += 1
    event = WorkflowEvent(
        event_id=uuid4().hex,
        project_id=context.project_id,
        run_id=context.run_id,
        timestamp=utcnow(),
        payload=DecisionEvent(
            decision_id=review.id, verdict="ACCEPT" if verdict == "approved" else "REVISE"
        ),
    )
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT payload FROM records WHERE kind='identity' AND id=?", (identity_id,)
        ).fetchone()
        if ProvisionalIdentity.model_validate_json(row[0]).revision != expected_revision:
            raise ValueError("identity changed during review")
        for proof in identity.proofs:
            row = db.execute(
                "SELECT payload FROM records WHERE kind='scene_head' AND id=?",
                (scene_key(context.project_id, proof.scene_id),),
            ).fetchone()
            if row is None or SceneHead.model_validate_json(row[0]).version != proof.scene_version:
                raise ValueError("proof changed during review; approval was not recorded")
        for kind, record_id, model in [
            ("identity", identity.id, identity),
            ("identity_review", review.id, review),
            ("event", event.event_id, event),
        ]:
            db.execute(
                "INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE "
                "SET payload=excluded.payload,updated_at=excluded.updated_at",
                (
                    kind,
                    record_id,
                    context.project_id,
                    model.model_dump_json(),
                    utcnow().isoformat(),
                ),
            )
    return identity
