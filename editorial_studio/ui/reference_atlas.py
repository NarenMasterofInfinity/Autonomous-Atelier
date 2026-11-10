"""Inspect authored reference studies without inferring artistic or owner approval."""

import streamlit as st

from editorial_studio.reference_studio.catalog import proof_assets, references
from editorial_studio.reference_studio.models import ReferenceAtlas


def render_reference_atlas(store, project):
    rows = references(store, project)
    if not rows:
        return []
    with st.expander("M10A · Authored visual reference atlas", expanded=True):
        st.caption(
            f"{len(rows)} authored studies · {len({r.family_id for r in rows})} visual families. These are design references; owner approval is recorded separately."
        )
        labels = {r.id: f"{r.design_id} · {r.title}" for r in rows}
        key = st.selectbox("Authored study", list(labels), format_func=labels.get)
        proof = next(r for r in rows if r.id == key)
        proof_assets(store, proof)
        st.image(
            store.read_blob(project, proof.spread.png_asset_id),
            caption=proof.title,
            width="stretch",
        )
        st.write(proof.brief)
        st.caption(proof.family_id + " · " + proof.status.replace("_", " "))
        if proof.review_note:
            st.write(proof.review_note)
        with st.expander("Family and source references"):
            st.json(proof.model_dump(mode="json", exclude={"spread"}))
    return [proof.spread.scene_id]


def reference_exports(store, project):
    rows = references(store, project)
    if not rows:
        return
    with st.expander("Authored reference downloads"):
        atlas = store.list("reference_atlas", ReferenceAtlas, project)[-1]
        st.download_button(
            "Download complete reference book",
            store.read_blob(project, atlas.pdf_asset_id),
            file_name=atlas.id + "-references.pdf",
            mime="application/pdf",
            key="atlas-book-" + atlas.id,
            on_click="ignore",
        )
        labels = {r.id: f"{r.design_id} · {r.title}" for r in rows}
        key = st.selectbox("Reference to download", list(labels), format_func=labels.get)
        proof = next(r for r in rows if r.id == key)
        st.download_button(
            "Download authored reference PDF",
            store.read_blob(project, proof.spread.pdf_asset_id),
            file_name=proof.id + ".pdf",
            mime="application/pdf",
            key="atlas-pdf-" + proof.id,
            on_click="ignore",
        )
        st.download_button(
            "Download reference scene",
            store.read_blob(project, proof.spread.document_asset_id),
            file_name=proof.id + ".json",
            mime="application/json",
            key="atlas-scene-" + proof.id,
            on_click="ignore",
        )
