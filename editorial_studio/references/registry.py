"""Manually curated spread references. Reading the catalog never fetches the web."""

import hashlib
from pathlib import Path

import yaml
from pydantic import Field, HttpUrl, model_validator

from editorial_studio.contracts.models import StrictModel
from editorial_studio.settings import ROOT


class ReferenceEntry(StrictModel):
    id: str
    publication: str
    title: str
    source_url: HttpUrl
    image_url: HttpUrl
    source_image_name: str
    gallery_index: int = Field(ge=0)
    kind: str = "spread"
    tags: list[str] = Field(min_length=1)
    observation: str = Field(min_length=1)
    credit: str
    reviewed_on: str
    preview_path: str | None = None
    preview_sha256: str | None = None
    usage: str = "reference_only"

    @model_validator(mode="after")
    def reference_only(self):
        if self.source_url.scheme != "https" or self.image_url.scheme != "https":
            raise ValueError("reference sources must use HTTPS")
        if self.usage != "reference_only":
            raise ValueError("reference previews are not composition assets")
        if bool(self.preview_path) != bool(self.preview_sha256):
            raise ValueError("preview path and hash are paired")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("duplicate reference tag")
        return self


class ReferenceCatalog(StrictModel):
    version: str
    references: list[ReferenceEntry]

    @model_validator(mode="after")
    def unique(self):
        ids = [r.id for r in self.references]
        images = [str(r.image_url) for r in self.references]
        if len(ids) != len(set(ids)) or len(images) != len(set(images)):
            raise ValueError("reference IDs and source images must be unique")
        return self


class ReferenceRegistry:
    def __init__(self, path: Path = ROOT / "config/references.yaml"):
        self.catalog = ReferenceCatalog.model_validate(yaml.safe_load(path.read_text()))
        self.entries = {r.id: r for r in self.catalog.references}

    def get(self, reference_id: str) -> ReferenceEntry:
        try:
            return self.entries[reference_id].model_copy(deep=True)
        except KeyError:
            raise ValueError(f"Unknown reference: {reference_id}") from None

    def search(
        self, tags: list[str] | None = None, publication: str | None = None
    ) -> list[ReferenceEntry]:
        requested = set(tags or [])
        return [
            r.model_copy(deep=True)
            for r in self.catalog.references
            if requested <= set(r.tags) and (publication is None or r.publication == publication)
        ]

    def preview(self, reference_id: str) -> bytes | None:
        entry = self.get(reference_id)
        if not entry.preview_path:
            return None
        path = (ROOT / entry.preview_path).resolve()
        if not path.is_relative_to((ROOT / "data/references").resolve()):
            raise ValueError("reference preview is outside its cache")
        if not path.exists():
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.preview_sha256:
            raise ValueError("reference preview hash mismatch")
        return data
