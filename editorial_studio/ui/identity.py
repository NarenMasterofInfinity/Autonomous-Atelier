"""M2 controls stay within the existing Inputs and Spread Studio tabs."""

import streamlit as st
import yaml

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.art_direction.service import DEFAULT_REFERENCES
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts.models import PaletteToken
from editorial_studio.core.jobs import BuildIdentityCommand, Command, Queue, ReviewIdentityCommand
from editorial_studio.design_system.models import DesignTokens, PairingCatalog
from editorial_studio.references.registry import ReferenceRegistry
from editorial_studio.settings import ROOT


def identity_inputs(store, project_id):
    catalog = PairingCatalog.model_validate(
        yaml.safe_load((ROOT / "config/font_pairings.yaml").read_text())
    )
    tokens = DesignTokens.model_validate(
        yaml.safe_load((ROOT / "config/design_system.yaml").read_text())
    )
    references = ReferenceRegistry()
    st.subheader("Provisional identity")
    st.write(
        "Choose the type pairing, palette, and visual references. The worker will build three measured story proofs for review."
    )
    pairings = {p.id: p for p in catalog.pairings}
    with st.form("build-identity"):
        pairing = st.selectbox(
            "Type pairing", list(pairings), format_func=lambda key: pairings[key].name
        )
        palette = []
        columns = st.columns(len(tokens.palette))
        for column, token in zip(columns, tokens.palette, strict=True):
            palette.append(
                PaletteToken(
                    name=token.name,
                    hex_color=column.color_picker(token.name.title(), token.hex_color),
                )
            )
        selected = st.multiselect(
            "Identity references",
            list(references.entries),
            default=DEFAULT_REFERENCES,
            format_func=lambda key: (
                f"{references.entries[key].publication} · {references.entries[key].title}"
            ),
        )
        build = st.form_submit_button("Build provisional identity", disabled=not selected)
    if build:
        command = Command(
            project_id=project_id,
            payload=BuildIdentityCommand(
                pairing_id=pairing, reference_ids=selected, palette=palette
            ),
        )
        Queue(store).submit(command)
        st.success(
            "Queued three baseline proofs. The identity stays provisional while they are reviewed."
        )


def render_identity(store, project_id):
    identities = store.list("identity", ProvisionalIdentity, project_id)
    if not identities:
        return
    with st.expander("Identity, proofs, and references", expanded=True):
        identity_id = st.selectbox(
            "Identity",
            [i.id for i in reversed(identities)],
            format_func=lambda key: next(
                i.pairing.name + " · " + i.id[:8] for i in identities if i.id == key
            ),
        )
        identity = next(i for i in identities if i.id == identity_id)
        status = identity.review.verdict if identity.review else "pending provisional review"
        st.write(f"**Provisional identity · {status}**")
        proofs_current = all(
            SceneRepository(store, project_id).head(p.scene_id).version == p.scene_version
            for p in identity.proofs
        )
        reviewable = proofs_current and bool(identity.proof_book_asset_id)
        if not reviewable:
            st.info(
                "Build a fresh identity proof set before recording a review. Current canvas edits are outside this saved proof set."
            )
        st.write(identity.bible.conceptual_identity)
        st.caption(
            f"{identity.pairing.name} · body {identity.guidelines.body_size_pt:g} pt · "
            f"baseline {identity.guidelines.baseline_step_mm:g} mm · fold clearance {identity.guidelines.fold_safe_mm:g} mm"
        )
        for rule in identity.guidelines.composition_rules:
            st.write("• " + rule)
        columns = st.columns(3)
        for column, proof in zip(columns, identity.proofs, strict=True):
            column.image(store.read_blob(project_id, proof.png_asset_id), width="stretch")
            column.caption(proof.story_id)
        st.download_button(
            "Download provisional Bible",
            identity.bible.model_dump_json(indent=2),
            "provisional-bible.json",
            mime="application/json",
            key=f"bible-{identity.id}",
        )
        if identity.proof_book_asset_id:
            st.download_button(
                "Download three-proof PDF",
                store.read_blob(project_id, identity.proof_book_asset_id),
                "baseline-proofs.pdf",
                mime="application/pdf",
                key=f"book-{identity.id}",
            )
        st.download_button(
            "Download layout guidelines",
            identity.guidelines.model_dump_json(indent=2),
            "layout-guidelines.json",
            mime="application/json",
            key=f"guidelines-{identity.id}",
        )
        with st.form("review-" + identity.id):
            actor = st.text_input("Reviewer name", key="actor-" + identity.id)
            verdict = st.radio(
                "Provisional review",
                ["Approve provisional identity", "Request revision"],
                key="verdict-" + identity.id,
            )
            note = st.text_area(
                "Review note", "Reviewed all three baseline proofs.", key="note-" + identity.id
            )
            submit = st.form_submit_button("Record provisional review", disabled=not reviewable)
        if submit:
            if not actor.strip() or not note.strip():
                st.error("Enter a reviewer name and a review note.")
            else:
                Queue(store).submit(
                    Command(
                        project_id=project_id,
                        payload=ReviewIdentityCommand(
                            identity_id=identity.id,
                            expected_revision=identity.revision,
                            actor=actor.strip(),
                            verdict="approved"
                            if verdict.startswith("Approve")
                            else "revision_required",
                            note=note.strip(),
                        ),
                    )
                )
                st.success(
                    "Review queued against these exact proof versions. Final creative identity approval is a later stage."
                )
        with st.expander("Capability coverage"):
            st.dataframe(
                [
                    {
                        "technique": c.name,
                        "status": c.verification_status,
                        "available operations": ", ".join(c.available_operations),
                        "missing operations": ", ".join(c.missing_operations),
                    }
                    for c in identity.capabilities
                ],
                width="stretch",
            )
            st.caption(
                "Operation availability does not establish artistic verification of a technique."
            )
    with st.expander("Manual reference library · 20 curated spread examples"):
        registry = ReferenceRegistry()
        tags = sorted({tag for reference in registry.catalog.references for tag in reference.tags})
        selected_tags = st.multiselect("Filter reference tags", tags)
        for reference in registry.search(selected_tags):
            st.write(f"**{reference.publication} · {reference.title}**")
            preview = registry.preview(reference.id)
            if preview:
                st.image(preview, width=500)
            st.caption(reference.observation)
            st.link_button("Source: " + reference.title, str(reference.source_url))
            st.caption(reference.credit + " · " + reference.source_image_name)
    return [proof.scene_id for proof in identity.proofs]
