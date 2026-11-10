"""Compose with captured editorial programs; inspect admission and rejected alternatives."""

import streamlit as st

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.core.jobs import BuildReferenceCompositionCommand, Command, Queue
from editorial_studio.photos.models import IngestedStory
from editorial_studio.reference_studio.catalog import references
from editorial_studio.reference_studio.models import CompositionProgram, ReferenceComposition


def reference_composition_inputs(store, project):
    stories = store.list("story", IngestedStory, project)
    identities = store.list("identity", ProvisionalIdentity, project)
    examples = [r for r in references(store) if r.status != "needs_rework"]
    if not stories or not identities or not examples:
        return
    ledger = ProvenanceLedger(store, project)
    with st.expander("Compose from the editorial reference library", expanded=True):
        st.write(
            "Keep a reference's typography, image relationships and reading areas while fitting your story. Incompatible designs are rejected. Layout and rendering run locally; optional art-direction selection sends the proof images to the configured provider and incurs API charges."
        )
        with st.form("reference-program-composition"):
            story = st.selectbox(
                "Story for reference composition",
                [s.id for s in stories],
                format_func=lambda key: (
                    ledger.get(next(s.title_block_id for s in stories if s.id == key)).source_text
                ),
            )
            identity = st.selectbox(
                "Reading identity",
                [i.id for i in identities],
                index=next(
                    (index for index, i in enumerate(identities) if i.id == "m10a-studio-identity"),
                    0,
                ),
            )
            selected = st.multiselect(
                "Editorial programs",
                [r.id for r in examples],
                default=[r.id for r in examples[:12]],
                max_selections=12,
                format_func=lambda key: next(
                    r.design_id + " · " + r.title for r in examples if r.id == key
                ),
            )
            art_director = st.checkbox("Let the art director choose a preview", value=True)
            submit = st.form_submit_button("Queue reference composition", disabled=not selected)
        if submit:
            Queue(store).submit(
                Command(
                    project_id=project,
                    payload=BuildReferenceCompositionCommand(
                        story_id=story,
                        identity_id=identity,
                        reference_ids=selected,
                        art_director=art_director,
                    ),
                )
            )
            st.success("Reference composition queued.")


def render_reference_compositions(store, project):
    results = store.list("reference_composition", ReferenceComposition, project)
    if not results:
        return []
    with st.expander("Reference-based compositions", expanded=True):
        key = st.selectbox("Reference composition run", [r.id for r in reversed(results)])
        result = next(r for r in results if r.id == key)
        admitted = [c for c in result.candidates if c.quality.passed]
        if result.art_direction_rationale:
            st.write("Art-direction preference: " + result.art_direction_rationale)
        if result.visual_review:
            st.caption(
                "Model visual review · "
                + result.visual_review.verdict.value
                + " · "
                + result.review_mode.replace("_", " ")
            )
            st.write(result.visual_review.rationale)
        st.caption(
            f"{len(admitted)} admissible compositions · {len(result.rejections)} rejected programs · {result.state.replace('_', ' ')}"
        )
        if not admitted:
            st.info(
                "No reference fits this story under the readability and scale constraints. No winner was selected."
            )
        else:
            st.image(store.read_blob(project, result.contact_sheet_asset_id), width="stretch")
            labels = {c.program_id: c.family_id + " · " + c.reference_id for c in admitted}
            selected = st.selectbox(
                "Composition to inspect",
                list(labels),
                format_func=labels.get,
                index=next(
                    (
                        i
                        for i, c in enumerate(admitted)
                        if c.program_id == result.selected_program_id
                    ),
                    0,
                ),
            )
            candidate = next(c for c in admitted if c.program_id == selected)
            st.image(store.read_blob(project, candidate.spread.png_asset_id), width="stretch")
            st.caption(
                "Adapted from an authored reference program; original story copy and selected photograph. Ready for visual review; no publication approval is inferred."
            )
            if candidate.native_views:
                with st.expander("Native display, reading and image/type details"):
                    for name, asset in candidate.native_views.assets.items():
                        st.image(store.read_blob(project, asset), caption=name, width="stretch")
            with st.expander("Captured design characteristics and checks"):
                programs = [
                    CompositionProgram.model_validate_json(store.read_blob(project, a))
                    for a in result.program_asset_ids
                ]
                program = next(p for p in programs if p.id == candidate.program_id)
                st.json(program.characteristics.model_dump(mode="json"))
                st.json(candidate.quality.model_dump(mode="json"))
        if result.rejections:
            with st.expander("Why other programs were rejected"):
                for rejection in result.rejections:
                    st.write(rejection.program_id + ": " + rejection.reason)
    return [candidate.spread.scene_id] if admitted else []


def reference_composition_exports(store, project):
    results = store.list("reference_composition", ReferenceComposition, project)
    if results:
        with st.expander("Reference composition exports"):
            selected = st.selectbox(
                "Composition run to download", [r.id for r in reversed(results)]
            )
            result = next(r for r in results if r.id == selected)
            if result.proof_book_asset_id:
                st.download_button(
                    "Download reference composition book",
                    store.read_blob(project, result.proof_book_asset_id),
                    file_name=result.id + ".pdf",
                    mime="application/pdf",
                    key="composition-pdf-" + result.id,
                    on_click="ignore",
                )
            st.download_button(
                "Download reference composition evidence",
                result.model_dump_json(indent=2),
                file_name=result.id + ".json",
                mime="application/json",
                key="composition-json-" + result.id,
                on_click="ignore",
            )
