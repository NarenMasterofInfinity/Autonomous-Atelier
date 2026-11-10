"""Queued publication inputs and saved image-analysis/cutout evidence."""

import base64
from uuid import uuid4

import streamlit as st

from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.contracts.models import BoundsMM, NormalizedRegion
from editorial_studio.core.jobs import Command, IngestStoryCommand, Queue, SegmentSubjectCommand
from editorial_studio.photos.models import IngestedStory, PhotoAssessment, PhotoInput, StoryInput
from editorial_studio.photos.pipeline import assess_placement
from editorial_studio.segmentation.models import SegmentationResult, SegmentPrompt


def workflow_inputs(store, project_id):
    with st.expander("Ingest a photo story"):
        with st.form("ingest-story"):
            story_id = st.text_input("Story identifier", value="story-" + uuid4().hex[:8])
            title = st.text_input("Story title")
            deck = st.text_area("Story deck")
            body = st.text_area("Story body")
            author = st.text_input("Story author")
            photos = st.file_uploader(
                "Story photographs", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True
            )
            source = st.text_input("Photo source", value="User upload")
            credit = st.text_input("Photo credit")
            submit = st.form_submit_button("Queue story ingestion")
        if submit:
            if (
                not all(x.strip() for x in (story_id, title, deck, body, author, source, credit))
                or not photos
            ):
                st.error("Provide the story, photographs, source, and credit.")
            else:
                value = StoryInput(
                    id=story_id,
                    title=title,
                    deck=deck,
                    body=body,
                    author=author,
                    photos=[
                        PhotoInput(
                            filename=p.name,
                            data_base64=base64.b64encode(p.getvalue()).decode(),
                            source_uri=source,
                            credit=credit,
                        )
                        for p in photos
                    ],
                )
                Queue(store).submit(
                    Command(project_id=project_id, payload=IngestStoryCommand(story=value))
                )
                st.success("Story queued for source-preserving ingestion and photo analysis.")


def render_workflow(store, project_id):
    photos = store.list("photo", PhotoAssessment, project_id)
    stories = store.list("story", IngestedStory, project_id)
    if stories:
        with st.expander("Content and provenance"):
            ledger = ProvenanceLedger(store, project_id)
            for story in stories:
                st.write("**" + ledger.get(story.title_block_id).source_text + "**")
                st.caption("Revision " + story.source_revision_id[:12] + " · " + story.author)
                st.json(ledger.coverage(story.body_block_id).model_dump(mode="json"))
    if photos:
        with st.expander("Photo feasibility and subject isolation"):
            by_id = {p.id: p for p in photos}
            selected = st.selectbox(
                "Source photo",
                list(by_id),
                format_func=lambda key: by_id[key].source_uri + " · " + key[:8],
            )
            photo = by_id[selected]
            columns = st.columns(3)
            for column, asset, caption in zip(
                columns,
                [photo.source_asset_id, photo.saliency_asset_id, photo.negative_space_asset_id],
                ["Source", "Saliency", "Quiet regions"],
                strict=True,
            ):
                column.image(store.read_blob(project_id, asset), width="stretch")
                column.caption(caption)
            st.write(photo.findings or ["No configured feasibility threshold was exceeded."])
            st.caption(
                f"Sharpness {photo.sharpness:.1f} · noise {photo.noise:.1f} · contrast {photo.contrast:.2f} · {len(photo.faces)} detected faces"
            )
            frame_width = st.number_input("Placement width (mm)", min_value=1.0, value=180.0)
            frame_height = st.number_input("Placement height (mm)", min_value=1.0, value=180.0)
            placement = assess_placement(
                photo, BoundsMM(x_mm=0, y_mm=0, width_mm=frame_width, height_mm=frame_height)
            )
            st.write(
                f"Effective PPI: {placement.effective_ppi:.0f} · {placement.status.replace('_', ' ')}"
            )
            with st.form("segment-photo"):
                st.caption("Give a box around the subject using fractions of the full image.")
                x = st.number_input("Subject left", min_value=0.0, max_value=0.99, value=0.05)
                y = st.number_input("Subject top", min_value=0.0, max_value=0.99, value=0.05)
                width = st.number_input("Subject width", min_value=0.01, max_value=1.0, value=0.9)
                height = st.number_input("Subject height", min_value=0.01, max_value=1.0, value=0.9)
                isolate = st.form_submit_button("Queue subject isolation")
            if isolate:
                if x + width > 1 or y + height > 1:
                    st.error("Subject box must lie inside the photograph.")
                else:
                    Queue(store).submit(
                        Command(
                            project_id=project_id,
                            payload=SegmentSubjectCommand(
                                prompt=SegmentPrompt(
                                    source_asset_id=photo.source_asset_id,
                                    box=NormalizedRegion(x=x, y=y, width=width, height=height),
                                )
                            ),
                        )
                    )
                    st.success("Subject isolation queued.")
            for result in store.list("segmentation", SegmentationResult, project_id):
                if result.source_asset_id == photo.source_asset_id:
                    st.image(store.read_blob(project_id, result.cutout_asset_id), width=450)
                    st.json(result.quality.model_dump(mode="json"))
                    st.caption(
                        "Edge diagnostics support visual inspection; they do not establish true segmentation accuracy."
                    )
