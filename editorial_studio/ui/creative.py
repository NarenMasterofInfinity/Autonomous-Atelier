"""Creative jobs, sketch/render inspection, critic evidence and explicit final identity review."""

import streamlit as st

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.artifacts.models import ArtifactBuild
from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.core.jobs import (
    BuildCapabilityProofsCommand,
    BuildCreativeSpreadCommand,
    Command,
    PackageFinalIdentityCommand,
    Queue,
    ReviewFinalIdentityCommand,
)
from editorial_studio.creative.models import (
    CompiledConcept,
    CreativeReview,
    CreativeSpread,
    FinalIdentityPackage,
)
from editorial_studio.photos.models import IngestedStory
from editorial_studio.spatial.proofs import CapabilityProof


def creative_inputs(store, project):
    stories = store.list("story", IngestedStory, project)
    identities = store.list("identity", ProvisionalIdentity, project)
    if not stories or not identities:
        return
    ledger = ProvenanceLedger(store, project)
    with st.expander("Compose a creative spread"):
        st.write(
            "The worker will generate a concept, compile it, render the spread and request visual critic reviews. This sends selected story copy and images to the configured provider and can incur API charges."
        )
        with st.form("creative-spread"):
            story_id = st.selectbox(
                "Creative story",
                [s.id for s in stories],
                format_func=lambda key: (
                    ledger.get(next(s.title_block_id for s in stories if s.id == key)).source_text
                ),
            )
            identity_id = st.selectbox(
                "Creative identity",
                [i.id for i in identities],
                format_func=lambda key: next(
                    i.pairing.name + " · " + i.id[:8] for i in identities if i.id == key
                ),
            )
            mandate = st.text_area(
                "Creative direction",
                "Find a visual metaphor in this story. Preserve all source copy and give the image a deliberate role.",
            )
            submit = st.form_submit_button("Queue creative composition")
        if submit:
            if not mandate.strip():
                st.error("Provide a creative direction.")
            else:
                Queue(store).submit(
                    Command(
                        project_id=project,
                        payload=BuildCreativeSpreadCommand(
                            story_id=story_id, identity_id=identity_id, mandate=mandate
                        ),
                    )
                )
                st.success(
                    "Creative composition queued. The generated proofs will remain available for review."
                )


def render_creative(store, project):
    spreads = store.list("creative_spread", CreativeSpread, project)
    caps = store.list("capability_proof", CapabilityProof, project)
    preferred = []
    if spreads:
        with st.expander("Creative concepts and critics", expanded=True):
            selected = st.selectbox("Creative spread", [s.id for s in reversed(spreads)])
            spread = next(s for s in spreads if s.id == selected)
            concept = store.get("concept", spread.concept_id, CompiledConcept)
            review = store.get("creative_review", spread.review_id, CreativeReview)
            st.write("**" + concept.proposal.visual_metaphor + "**")
            st.caption(spread.state.replace("_", " ") + " · " + review.decision.verdict.value)
            if concept.authorship == "authored":
                st.caption(
                    "Authored composition benchmark · generated layout performance remains a separate question."
                )
                st.image(
                    store.read_blob(project, spread.png_asset_id),
                    caption="Rendered spread",
                    width="stretch",
                )
                st.download_button(
                    "Download this spread PDF",
                    store.read_blob(project, spread.pdf_asset_id),
                    file_name=spread.id + ".pdf",
                    mime="application/pdf",
                )
                with st.expander("Composition plan"):
                    st.image(
                        store.read_blob(project, concept.hybrid.sketch.asset_id), width="stretch"
                    )
            else:
                if concept.authorship == "reference_adapted":
                    st.caption(
                        "Automatically adapted from an authored reference program; not a free-form model layout."
                    )
                columns = st.columns([1, 2])
                columns[0].image(
                    store.read_blob(project, concept.hybrid.sketch.asset_id),
                    caption="Concept graph sketch",
                    width="stretch",
                )
                columns[1].image(
                    store.read_blob(project, spread.png_asset_id),
                    caption="Rendered spread",
                    width="stretch",
                )
            opacity = st.slider("Sketch overlay", 0.0, 1.0, 0.25, 0.05)
            from io import BytesIO

            from PIL import Image

            sketch = Image.open(
                BytesIO(store.read_blob(project, concept.hybrid.sketch.asset_id))
            ).convert("RGB")
            rendered = Image.open(BytesIO(store.read_blob(project, spread.png_asset_id))).convert(
                "RGB"
            )
            rendered.thumbnail((1000, 707))
            sketch = sketch.resize(rendered.size)
            with st.expander("Sketch-to-render overlay"):
                st.image(Image.blend(rendered, sketch, opacity), width="stretch")
            st.image(
                store.read_blob(project, review.inspection.thumbnail_asset_id),
                caption="Mass hierarchy thumbnail",
                width=420,
            )
            with st.expander("Native pixel crop"):
                st.image(store.read_blob(project, review.inspection.crop_asset_id), width="content")
            for title, assessment in [
                ("Execution", review.execution),
                ("Artistic", review.artistic),
                ("Concept fidelity", review.fidelity),
            ]:
                if assessment:
                    st.write(f"**{title} critic · {assessment.verdict.value}**")
                    st.write(assessment.rationale)
                    for finding in assessment.findings:
                        st.write(
                            f"{finding.severity.value}: {finding.description} {finding.actionable_fix}"
                        )
                else:
                    st.info(title + " critic has not run.")
            if review.decision.stagnation_detected:
                st.warning(
                    "Comparative reviews found stagnation. Reconsider the concept or subtract an element."
                )
            st.caption("Model judgments support review; no human approval is inferred.")
            st.download_button(
                "Download concept and recipe",
                concept.model_dump_json(indent=2),
                "creative-concept.json",
                key="creative-concept-" + spread.id,
            )
            preferred = [spread.scene_id]
    if caps:
        with st.expander("R1 technique proofs"):
            latest = {proof.capability_id: proof for proof in caps}
            st.dataframe(
                [
                    {
                        "technique": proof.capability_id,
                        "status": proof.status,
                        "reviewer": proof.reviewer,
                    }
                    for proof in latest.values()
                ],
                width="stretch",
            )
            columns = st.columns(3)
            for index, proof in enumerate(latest.values()):
                columns[index % 3].image(
                    store.read_blob(project, proof.thumbnail_asset_id),
                    caption=proof.capability_id,
                    width="stretch",
                )
    elif st.button("Queue ten technique proofs"):
        Queue(store).submit(Command(project_id=project, payload=BuildCapabilityProofsCommand()))
        st.success("Ten local technique proofs queued.")
    for build in store.list("artifact_build", ArtifactBuild, project):
        with st.expander("Generated artifact · " + build.request.visual_role):
            st.image(store.read_blob(project, build.raster_asset_id), width=400)
            st.caption(build.classification + " · " + build.status)
            if build.traced:
                st.caption(f"Trace/source raster agreement: {build.traced.reconstructed_iou:.3f}")
    if len(spreads) >= 2 and caps:
        with st.expander("Assemble representative identity proofs"):
            identities = store.list("identity", ProvisionalIdentity, project)
            with st.form("package-identity"):
                identity_id = st.selectbox("Final identity source", [i.id for i in identities])
                selected = st.multiselect(
                    "Representative creative spreads",
                    [s.id for s in spreads],
                    default=[s.id for s in spreads if s.identity_id == identity_id][-3:],
                )
                submit = st.form_submit_button("Queue final review package")
            if submit:
                if len(selected) not in (2, 3):
                    st.error("Select two or three representative spreads.")
                else:
                    latest = {p.capability_id: p for p in caps}
                    Queue(store).submit(
                        Command(
                            project_id=project,
                            payload=PackageFinalIdentityCommand(
                                identity_id=identity_id,
                                spread_ids=selected,
                                capability_proof_ids=[p.id for p in latest.values()],
                            ),
                        )
                    )
                    st.success("Representative package queued.")
    packages = store.list("final_identity_package", FinalIdentityPackage, project)
    shown_packages = []
    if packages:
        selected_package = st.selectbox(
            "Final review package", [package.id for package in reversed(packages)]
        )
        shown_packages = [package for package in packages if package.id == selected_package]
    for package in shown_packages:
        with st.expander("Final creative identity · " + package.id, expanded=True):
            st.write("**" + (package.review_verdict or "Awaiting art-director review") + "**")
            st.image(store.read_blob(project, package.contact_sheet_asset_id), width="stretch")
            st.download_button(
                "Download representative spread PDF",
                store.read_blob(project, package.proof_book_asset_id),
                "representative-spreads.pdf",
                mime="application/pdf",
                key="final-pdf-" + package.id,
            )
            st.download_button(
                "Download candidate Bible",
                package.bible.model_dump_json(indent=2),
                "candidate-bible.json",
                key="final-bible-" + package.id,
            )
            identity = store.get("identity", package.identity_id, ProvisionalIdentity)
            if identity.review is None or identity.review.verdict != "approved":
                st.info("Approve the provisional identity below before recording final approval.")
            if package.requires_critic_override:
                st.warning(
                    "One or more critics requested changes. Review their findings before choosing final approval."
                )
            with st.form("final-review-" + package.id):
                actor = st.text_input("Final reviewer name", key="final-actor-" + package.id)
                note = st.text_area("Final review note", key="final-note-" + package.id)
                verdict = st.radio(
                    "Final verdict",
                    ["Approve final creative identity", "Request creative revision"],
                    key="final-verdict-" + package.id,
                )
                inspected = st.checkbox(
                    "I approve the ten R1 technique proofs and have reviewed all representative spreads.",
                    key="final-inspected-" + package.id,
                )
                override = (
                    st.checkbox(
                        "I deliberately override the model revision requests, for the reasons in my review note.",
                        key="critic-override-" + package.id,
                    )
                    if package.requires_critic_override
                    else False
                )
                submit = st.form_submit_button("Record final identity review")
            if submit:
                if not actor.strip() or not note.strip():
                    st.error("A reviewer name and specific review note are required.")
                elif verdict.startswith("Approve") and (
                    identity.review is None or identity.review.verdict != "approved"
                ):
                    st.error("Record provisional identity approval before final approval.")
                elif (
                    verdict.startswith("Approve")
                    and package.requires_critic_override
                    and not override
                ):
                    st.error("Address the critic findings or explicitly acknowledge your override.")
                elif verdict.startswith("Approve") and not inspected:
                    st.error("Review the complete proof set before approving.")
                else:
                    Queue(store).submit(
                        Command(
                            project_id=project,
                            payload=ReviewFinalIdentityCommand(
                                package_id=package.id,
                                expected_revision=package.revision,
                                actor=actor.strip(),
                                note=note.strip(),
                                verdict="approved"
                                if verdict.startswith("Approve")
                                else "revision_required",
                                reviewed_techniques=inspected,
                                override_critic_recommendations=override,
                            ),
                        )
                    )
                    st.success("Final review queued against the exact proof versions.")
    return preferred
