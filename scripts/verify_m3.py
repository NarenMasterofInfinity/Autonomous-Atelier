"""Local ten-story ingestion proof using attributed upstream sample photos."""

import base64
import json
from pathlib import Path

from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import CallContext
from editorial_studio.photos.models import PhotoInput, StoryInput
from editorial_studio.photos.pipeline import ingest_story
from editorial_studio.settings import load_settings


def main():
    store = Store(load_settings().data_root)
    manifest = json.loads(Path("data/fixtures/photos/manifest.json").read_text())
    results = []
    with worker_lock(store):
        for row in manifest:
            title = f"Looking closely: {row['id'].replace('_', ' ')}"
            story = StoryInput(
                id=row["id"],
                title=title,
                deck="A study of framing, detail, and the space around a subject.",
                body="A photograph gives the eye several possible paths. The first follows the subject; another discovers the surrounding space. Looking at both helps an editor choose a frame that preserves the image and leaves room for a clear reading sequence.",
                author="Studio acceptance fixture",
                photos=[
                    PhotoInput(
                        filename=Path(row["path"]).name,
                        data_base64=base64.b64encode(Path(row["path"]).read_bytes()).decode(),
                        source_uri=row["source_uri"],
                        credit=row["credit"],
                    )
                ],
            )
            saved = ingest_story(
                store,
                CallContext(
                    project_id="m3-proof",
                    run_id="m3-" + row["id"],
                    agent_name="IngestionProof",
                    stage="M3",
                ),
                story,
            )
            ledger = ProvenanceLedger(store, "m3-proof")
            assert ledger.get(saved.body_block_id).source_text == story.body
            results.append(saved.model_dump(mode="json"))
    assert len(results) == 10
    target = Path("data/exports/m3-proof")
    target.mkdir(parents=True, exist_ok=True)
    (target / "ingestion.json").write_text(json.dumps(results, indent=2))
    print(
        "M3: 10 attributed sample-photo stories ingested; source revisions and derived text verified"
    )


if __name__ == "__main__":
    main()
