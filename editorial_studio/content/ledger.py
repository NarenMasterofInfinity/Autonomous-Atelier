"""Immutable source revisions and explicit derived-text coverage, independent of telemetry."""

import hashlib

from pydantic import Field

from editorial_studio.contracts.models import (
    ContentBlock,
    CoverageAssignment,
    DerivedText,
    EditType,
    SourceSpan,
    StrictModel,
)
from editorial_studio.core.storage import Store


class LedgerCoverage(StrictModel):
    block_id: str
    revision_id: str
    source_char_count: int
    represented_ranges: list[tuple[int, int]]
    unassigned_ranges: list[tuple[int, int]]
    placed_layer_ids: list[str] = Field(default_factory=list)


class TextPlacementBinding(StrictModel):
    id: str
    derived_text_id: str
    scene_id: str
    scene_version: str
    layer_ids: list[str]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ProvenanceLedger:
    def __init__(self, store: Store, project_id: str):
        self.store, self.project_id = store, project_id

    def source(self, story_id: str, field: str, text: str, images: list[str]) -> ContentBlock:
        if not text.strip():
            raise ValueError("empty source copy")
        revision = digest(text)
        block_id = digest(
            f"{self.project_id}\0{story_id}\0{field}\0{revision}\0" + ",".join(images)
        )
        existing = self.store.get("content", block_id, ContentBlock)
        if existing and existing.derived_texts:
            return existing
        block = ContentBlock(
            id=block_id, source_revision_id=revision, source_text=text, attached_image_ids=images
        )
        if existing is None:
            self.store.put_records(("content", block_id, self.project_id, block))
        self.derive(
            text,
            EditType.VERBATIM,
            [
                SourceSpan(
                    source_block_id=block_id,
                    source_revision_id=revision,
                    start_char=0,
                    end_char=len(text),
                )
            ],
        )
        return self.get(block_id)

    def get(self, block_id: str) -> ContentBlock:
        block = self.store.get("content", block_id, ContentBlock)
        if block is None or not any(
            b.id == block_id for b in self.store.list("content", ContentBlock, self.project_id)
        ):
            raise PermissionError("source block not in project")
        return block

    def derive(
        self, text: str, edit_type: EditType, spans: list[SourceSpan], *, separator=""
    ) -> DerivedText:
        if not text.strip():
            raise ValueError("empty derived copy")
        if not spans and edit_type != EditType.NEW_COPY:
            raise ValueError("source spans required")
        parts = []
        blocks = {}
        for span in spans:
            block = self.get(span.source_block_id)
            if span.source_revision_id != block.source_revision_id or span.end_char > len(
                block.source_text
            ):
                raise ValueError("source revision or range mismatch")
            parts.append(block.source_text[span.start_char : span.end_char])
            blocks[block.id] = block
        if (
            edit_type in (EditType.VERBATIM, EditType.EXCERPT, EditType.CONDENSED)
            and separator.join(parts) != text
        ):
            raise ValueError("exact source edit does not match its spans")
        if edit_type == EditType.VERBATIM and (
            len(spans) != 1
            or spans[0].start_char != 0
            or spans[0].end_char != len(next(iter(blocks.values())).source_text)
        ):
            raise ValueError("verbatim must represent the full source block")
        derived = DerivedText(
            id=digest(
                f"{self.project_id}\0{text}\0{edit_type}\0"
                + "".join(s.model_dump_json() for s in spans)
            ),
            text=text,
            edit_type=edit_type,
            derived_from=spans,
        )
        old = self.store.get("derived_text", derived.id, DerivedText)
        if old:
            return old
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._put(db, "derived_text", derived.id, derived)
            for block_id in blocks:
                row = db.execute(
                    "SELECT payload FROM records WHERE kind='content' AND id=? AND project_id=?",
                    (block_id, self.project_id),
                ).fetchone()
                block = ContentBlock.model_validate_json(row[0])
                block.derived_texts.append(derived)
                self._put(db, "content", block.id, block)
        return derived

    def _put(self, db, kind, record_id, model):
        from editorial_studio.core.storage import utcnow

        db.execute(
            "INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
            (kind, record_id, self.project_id, model.model_dump_json(), utcnow().isoformat()),
        )

    def assign(self, assignment: CoverageAssignment):
        block = self.get(assignment.span.source_block_id)
        if (
            assignment.span.source_revision_id != block.source_revision_id
            or assignment.span.end_char > len(block.source_text)
        ):
            raise ValueError("invalid assignment range")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM records WHERE kind='content' AND id=?", (block.id,)
            ).fetchone()
            block = ContentBlock.model_validate_json(row[0])
            block.coverage.append(assignment)
            self._put(db, "content", block.id, block)

    def bind(self, derived_id: str, layer_ids: list[str], *, scene_id: str) -> DerivedText:
        from editorial_studio.canvas.repository import SceneRepository
        from editorial_studio.contracts.models import TextLayer

        derived = self.store.get("derived_text", derived_id, DerivedText)
        if derived is None:
            raise ValueError("missing derived text")
        for span in derived.derived_from:
            self.get(span.source_block_id)
        # New-copy records are still scoped to the project.
        if not any(
            d.id == derived_id
            for d in self.store.list("derived_text", DerivedText, self.project_id)
        ):
            raise PermissionError("derived text not in project")
        repository = SceneRepository(self.store, self.project_id)
        document = repository.load(scene_id)
        layers = {layer.id: layer for layer in document.scene.layers}
        selected = [layers.get(layer_id) for layer_id in layer_ids]
        if (
            not selected
            or len(layer_ids) != len(set(layer_ids))
            or any(
                not isinstance(layer, TextLayer) or layer.derived_text_id != derived_id
                for layer in selected
            )
        ):
            raise ValueError("placement does not reference rendered text with matching provenance")
        if "".join(layer.text_content for layer in selected) != derived.text:
            raise ValueError("placed text does not represent the complete derivation")
        binding = TextPlacementBinding(
            id=digest(
                derived_id + document.scene.id + document.scene.version + ",".join(layer_ids)
            ),
            derived_text_id=derived_id,
            scene_id=scene_id,
            scene_version=document.scene.version,
            layer_ids=layer_ids,
        )
        derived.placed_layer_ids = sorted(set(derived.placed_layer_ids + layer_ids))
        self.store.put_records(
            ("derived_text", derived.id, self.project_id, derived),
            ("text_binding", binding.id, self.project_id, binding),
        )
        return derived

    def coverage(self, block_id: str) -> LedgerCoverage:
        block = self.get(block_id)
        # Only actual placements and explicit editorial assignments count as covered.
        ranges = []
        layers = set()
        bindings = self.store.list("text_binding", TextPlacementBinding, self.project_id)
        bound = {binding.derived_text_id for binding in bindings}
        for d in self.store.list("derived_text", DerivedText, self.project_id):
            if d.id in bound:
                for s in d.derived_from:
                    if s.source_block_id == block_id:
                        ranges.append((s.start_char, s.end_char))
                        layers.update(d.placed_layer_ids)
        for a in block.coverage:
            if a.status.value == "omitted_approved":
                ranges.append((a.span.start_char, a.span.end_char))
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        gaps = []
        cursor = 0
        for start, end in merged:
            if start > cursor:
                gaps.append((cursor, start))
            cursor = end
        if cursor < len(block.source_text):
            gaps.append((cursor, len(block.source_text)))
        return LedgerCoverage(
            block_id=block_id,
            revision_id=block.source_revision_id,
            source_char_count=len(block.source_text),
            represented_ranges=merged,
            unassigned_ranges=gaps,
            placed_layer_ids=sorted(layers),
        )
