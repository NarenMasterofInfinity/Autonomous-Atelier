"""Immutable rendered scene versions with atomic compare-and-swap of the live head."""

import hashlib
from uuid import uuid4

from editorial_studio.canvas.models import CanvasDocument, RenderOutput, SceneVersion
from editorial_studio.contracts.models import SceneEvent, ScenePatch, StrictModel, WorkflowEvent
from editorial_studio.core.storage import Store, utcnow
from editorial_studio.llm.contracts import CallContext


class VersionConflict(ValueError):
    pass


class SceneHead(StrictModel):
    scene_id: str
    project_id: str
    version: str
    version_record_id: str


class SnapshotRollback(StrictModel):
    id: str
    scene_id: str
    project_id: str
    expected_parent_version: str
    restored_version: str


def key(project_id, scene_id, version="head"):
    return hashlib.sha256(f"{project_id}\0{scene_id}\0{version}".encode()).hexdigest()


class SceneRepository:
    def __init__(self, store: Store, project_id: str):
        self.store, self.project_id = store, project_id

    def head(self, scene_id: str) -> SceneVersion:
        head = self.store.get("scene_head", key(self.project_id, scene_id), SceneHead)
        if head is None:
            raise KeyError("scene does not belong to this project")
        return self.store.get("scene_version", head.version_record_id, SceneVersion)

    def version(self, scene_id: str, version: str) -> SceneVersion:
        found = self.store.get(
            "scene_version", key(self.project_id, scene_id, version), SceneVersion
        )
        if found is None:
            raise KeyError("snapshot does not belong to this scene/project")
        return found

    def load(self, scene_id: str) -> CanvasDocument:
        head = self.head(scene_id)
        return CanvasDocument.model_validate_json(
            self.store.read_blob(self.project_id, head.document_asset_id)
        )

    def history(self, scene_id: str) -> list[SceneVersion]:
        return [
            v
            for v in self.store.list("scene_version", SceneVersion, self.project_id)
            if v.scene_id == scene_id
        ]

    def commit(
        self,
        document: CanvasDocument,
        rendered: RenderOutput,
        context: CallContext,
        *,
        expected_parent: str | None,
        patch: ScenePatch | None = None,
        rollback: SnapshotRollback | None = None,
    ) -> SceneVersion:
        if context.project_id != self.project_id:
            raise PermissionError("run belongs to another project")
        if document.scene.parent_version != expected_parent:
            raise VersionConflict("document parent does not match the transaction")
        if (
            rendered.metadata.document_hash
            != hashlib.sha256(document.model_dump_json().encode()).hexdigest()
        ):
            raise ValueError("render does not belong to this candidate document")
        previous = self.head(document.scene.id) if expected_parent is not None else None
        if previous and previous.version != expected_parent:
            raise VersionConflict("stale parent version")
        doc = self.store.json_blob(self.project_id, document)
        png = self.store.put_blob(self.project_id, rendered.png, "image/png")
        pdf = self.store.put_blob(self.project_id, rendered.pdf, "application/pdf")
        metadata = self.store.json_blob(self.project_id, rendered.metadata)
        version = SceneVersion(
            id=key(self.project_id, document.scene.id, document.scene.version),
            project_id=self.project_id,
            run_id=context.run_id,
            scene_id=document.scene.id,
            version=document.scene.version,
            parent_version=expected_parent,
            document_asset_id=doc.id,
            png_asset_id=png.id,
            pdf_asset_id=pdf.id,
            metadata_asset_id=metadata.id,
            snapshot_asset_id=previous.document_asset_id if previous else None,
            patch_id=patch.patch_id if patch else rollback.id if rollback else None,
            created_at=utcnow(),
        )
        head = SceneHead(
            scene_id=version.scene_id,
            project_id=self.project_id,
            version=version.version,
            version_record_id=version.id,
        )
        event = WorkflowEvent(
            event_id=uuid4().hex,
            project_id=self.project_id,
            run_id=context.run_id,
            spread_id=context.spread_id,
            timestamp=utcnow(),
            payload=SceneEvent(
                scene_id=version.scene_id, scene_version=version.version, patch_id=version.patch_id
            ),
        )
        entries = [
            ("scene_version", version.id, version),
            ("scene_head", key(self.project_id, version.scene_id), head),
            ("event", event.event_id, event),
        ]
        if patch:
            entries.append(("scene_patch", patch.patch_id, patch))
        if rollback:
            entries.append(("scene_rollback", rollback.id, rollback))
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM records WHERE kind='scene_head' AND id=?",
                (key(self.project_id, version.scene_id),),
            ).fetchone()
            actual = SceneHead.model_validate_json(row[0]).version if row else None
            if actual != expected_parent:
                raise VersionConflict("scene changed during rendering")
            if db.execute(
                "SELECT 1 FROM records WHERE kind='scene_version' AND id=?", (version.id,)
            ).fetchone():
                raise VersionConflict("scene version is immutable")
            for kind, record_id, model in entries:
                if (
                    kind in {"scene_patch", "scene_rollback"}
                    and db.execute(
                        "SELECT 1 FROM records WHERE kind=? AND id=?", (kind, record_id)
                    ).fetchone()
                ):
                    raise VersionConflict("transaction identifier is already committed")
                db.execute(
                    "INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE "
                    "SET payload=excluded.payload,updated_at=excluded.updated_at",
                    (
                        kind,
                        record_id,
                        self.project_id,
                        model.model_dump_json(),
                        utcnow().isoformat(),
                    ),
                )
        return version
