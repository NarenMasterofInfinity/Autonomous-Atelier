"""Build M2's three baseline proofs locally, retaining a pending provisional review."""

import argparse
from pathlib import Path
from uuid import uuid4

from editorial_studio.art_direction.service import build_identity
from editorial_studio.contracts.models import ProviderCallRecord
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import CallContext
from editorial_studio.settings import load_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairing", default="quiet-serif", choices=["quiet-serif", "direct-sans"])
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    with worker_lock(store):
        project = "m2-proof"
        photo = None
        source = next(
            (
                call
                for call in store.list("call", ProviderCallRecord, "m0-live")
                if call.status == "completed" and call.generated_artifact_ids and not call.cache_hit
            ),
            None,
        )
        if source:
            photo = store.put_blob(
                project, store.read_blob("m0-live", source.generated_artifact_ids[0]), "image/png"
            ).id
        context = CallContext(
            project_id=project,
            run_id=uuid4().hex,
            agent_name="IdentityProof",
            stage="M2",
            parent_call_id=source.call_id if source else None,
        )
        identity = build_identity(
            store, context, pairing_id=args.pairing, photo_asset_id=photo, dpi=144
        )
        target = Path("data/exports/m2-proof")
        target.mkdir(parents=True, exist_ok=True)
        for proof in identity.proofs:
            folder = target / proof.story_id
            folder.mkdir(exist_ok=True)
            for filename, asset in [
                ("spread.png", proof.png_asset_id),
                ("spread.pdf", proof.pdf_asset_id),
                ("scene.json", proof.document_asset_id),
                ("render-metadata.json", proof.metadata_asset_id),
            ]:
                (folder / filename).write_bytes(store.read_blob(project, asset))
            (folder / "layout-report.json").write_text(proof.report.model_dump_json(indent=2))
        (target / "baseline-proofs.pdf").write_bytes(
            store.read_blob(project, identity.proof_book_asset_id)
        )
        (target / "contact-sheet.png").write_bytes(
            store.read_blob(project, identity.contact_sheet_asset_id)
        )
        (target / "provisional-bible.json").write_text(identity.bible.model_dump_json(indent=2))
        (target / "layout-guidelines.json").write_text(
            identity.guidelines.model_dump_json(indent=2)
        )
        (target / "identity.json").write_text(identity.model_dump_json(indent=2))
        print("Identity:", identity.id)
        print(
            "Proofs:",
            len(identity.proofs),
            "Review:",
            "pending" if identity.review is None else identity.review.verdict,
        )
        print("Vector proof book:", target / "baseline-proofs.pdf")
        print("Contact sheet:", target / "contact-sheet.png")


if __name__ == "__main__":
    main()
