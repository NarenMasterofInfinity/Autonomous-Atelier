"""SQLite WAL metadata and immutable, content-addressed project blobs.

The worker owns pipeline writes. The UI connection only reads metadata and
inserts commands through the separate queue API.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from editorial_studio.contracts.models import StrictModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid project or record identifier")
    return value


class AssetRef(StrictModel):
    id: str
    project_id: str
    sha256: str
    media_type: str
    size_bytes: int = Field(ge=0)


class ReconciliationReport(StrictModel):
    quarantined_paths: list[str] = Field(default_factory=list)
    missing_asset_ids: list[str] = Field(default_factory=list)
    corrupt_asset_ids: list[str] = Field(default_factory=list)


class Store:
    def __init__(self, root: Path, *, readonly: bool = False):
        self.root = root.resolve()
        self.readonly = readonly
        self.db_path = self.root / "studio.sqlite3"
        if not readonly:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.connection() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, project_id TEXT NOT NULL,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(kind, id)
                );
                CREATE INDEX IF NOT EXISTS records_project ON records(project_id, kind);
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT NOT NULL, project_id TEXT NOT NULL, sha256 TEXT NOT NULL,
                    media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                    PRIMARY KEY(project_id, id)
                );
                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued', worker_id TEXT,
                    lease_until REAL, created_at TEXT NOT NULL, error TEXT
                );
                CREATE TABLE IF NOT EXISTS steps (
                    job_id TEXT NOT NULL, step_name TEXT NOT NULL, output TEXT NOT NULL,
                    PRIMARY KEY(job_id, step_name)
                );
                """)

    @contextmanager
    def connection(self):
        uri = f"{self.db_path.as_uri()}?mode=ro" if self.readonly else str(self.db_path)
        db = sqlite3.connect(uri, timeout=5, uri=self.readonly)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        if self.readonly:
            db.execute("PRAGMA query_only=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def put_records(self, *entries: tuple[str, str, str, BaseModel]) -> None:
        if self.readonly:
            raise PermissionError("viewer cannot write pipeline state")
        with self.connection() as db:
            for kind, record_id, project_id, model in entries:
                db.execute(
                    "INSERT INTO records VALUES (?,?,?,?,?) "
                    "ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload, "
                    "updated_at=excluded.updated_at",
                    (
                        kind,
                        identifier(record_id),
                        identifier(project_id),
                        model.model_dump_json(),
                        utcnow().isoformat(),
                    ),
                )

    def get(self, kind: str, record_id: str, model: type[BaseModel]):
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)
            ).fetchone()
        return model.model_validate_json(row[0]) if row else None

    def list(self, kind: str, model: type[BaseModel], project_id: str | None = None):
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM records WHERE kind=? "
                "AND (? IS NULL OR project_id=?) ORDER BY updated_at,id",
                (kind, project_id, project_id),
            ).fetchall()
        return [model.model_validate_json(row[0]) for row in rows]

    def put_blob(self, project_id: str, data: bytes, media_type: str) -> AssetRef:
        if self.readonly:
            raise PermissionError("viewer cannot create assets")
        project_id = identifier(project_id)
        digest = hashlib.sha256(data).hexdigest()
        folder = self.root / project_id / "blobs"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / digest
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("existing immutable asset is corrupt")
        if not target.exists():
            descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=folder)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                Path(temporary).unlink(missing_ok=True)
        ref = AssetRef(
            id=digest,
            project_id=project_id,
            sha256=digest,
            media_type=media_type,
            size_bytes=len(data),
        )
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?)",
                (ref.id, ref.project_id, ref.sha256, ref.media_type, ref.size_bytes),
            )
        return ref

    def asset(self, project_id: str, asset_id: str) -> AssetRef:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM assets WHERE project_id=? AND id=?",
                (identifier(project_id), asset_id),
            ).fetchone()
        if not row:
            raise KeyError("asset does not belong to this project")
        return AssetRef.model_validate(dict(row))

    def read_blob(self, project_id: str, asset_id: str) -> bytes:
        ref = self.asset(project_id, asset_id)
        data = (self.root / identifier(project_id) / "blobs" / ref.sha256).read_bytes()
        if hashlib.sha256(data).hexdigest() != ref.sha256:
            raise ValueError("asset content hash mismatch")
        return data

    def assets(self, project_id: str) -> list[AssetRef]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM assets WHERE project_id=?", (project_id,)).fetchall()
        return [AssetRef.model_validate(dict(row)) for row in rows]

    def reconcile(self) -> ReconciliationReport:
        report = ReconciliationReport()
        with self.connection() as db:
            refs = [AssetRef.model_validate(dict(r)) for r in db.execute("SELECT * FROM assets")]
        known = {(r.project_id, r.sha256) for r in refs}
        for ref in refs:
            path = self.root / ref.project_id / "blobs" / ref.sha256
            if not path.exists():
                report.missing_asset_ids.append(ref.id)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != ref.sha256:
                report.corrupt_asset_ids.append(ref.id)
        for path in self.root.glob("*/blobs/*"):
            if (path.parent.parent.name, path.name) not in known:
                quarantine = self.root / "quarantine"
                quarantine.mkdir(exist_ok=True)
                destination = quarantine / f"{uuid4().hex}-{path.name}"
                os.replace(path, destination)
                report.quarantined_paths.append(str(destination.relative_to(self.root)))
        return report

    def json_blob(self, project_id: str, value: BaseModel) -> AssetRef:
        return self.put_blob(project_id, value.model_dump_json().encode(), "application/json")
