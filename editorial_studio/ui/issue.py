"""Read issue pacing and physical pages; enqueue explicit architecture work."""

import streamlit as st

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.core.jobs import BuildIssueCommand, Command, Queue, ReviseIssueCommand
from editorial_studio.creative.issue_models import IssueCorrection, IssueResult
from editorial_studio.creative.tournament_models import TournamentResult
from editorial_studio.photos.models import IngestedStory
from editorial_studio.reference_studio.catalog import references


def issue_inputs(store, project):
    stories = store.list("story", IngestedStory, project)
    identities = store.list("identity", ProvisionalIdentity, project)
    tournaments = store.list("tournament", TournamentResult, project)
    if len(stories) < 6 or not identities:
        return
    ledger = ProvenanceLedger(store, project)
    library = [r for r in references(store) if r.status != "needs_rework"]
    with st.expander("Build a twelve-page issue"):
        st.write(
            "Choose six stories. The architect plans covers and reading progression. With the reference library enabled, each story is fitted and checked, then a varied sequence is selected across the issue. The cover keeps its headline on the front. Selected designs are preserved during assembly. This queues paid selection and review calls and uploads selected photographs and proof images."
        )
        with st.form("issue-architect"):
            selected = st.multiselect(
                "Issue stories",
                [s.id for s in stories],
                default=[s.id for s in stories[:6]],
                format_func=lambda key: (
                    ledger.get(next(s.title_block_id for s in stories if s.id == key)).source_text
                ),
            )
            identity = st.selectbox("Issue identity", [i.id for i in identities])
            winners = st.multiselect("Reuse tournament selections", [t.id for t in tournaments])
            use_library = st.checkbox(
                "Compose issue pages from the editorial reference library",
                value=bool(library),
                disabled=not library,
            )
            submit = st.form_submit_button("Queue twelve-page issue")
        if submit:
            if len(selected) != 6:
                st.error("Choose exactly six distinct stories.")
            else:
                Queue(store).submit(
                    Command(
                        project_id=project,
                        payload=BuildIssueCommand(
                            story_ids=selected,
                            identity_id=identity,
                            tournament_ids=winners,
                            reference_ids=[r.id for r in library[:12]] if use_library else [],
                        ),
                    )
                )
                st.success("Issue composition queued.")


def render_issues(store, project):
    results = store.list("issue", IssueResult, project)
    if not results:
        return []
    with st.expander("Issue architecture and pacing", expanded=True):
        key = st.selectbox("Issue", [r.id for r in reversed(results)])
        result = next(r for r in results if r.id == key)
        st.write("**" + result.blueprint.title + "**")
        st.caption(result.blueprint.throughline + " · " + result.state.replace("_", " "))
        st.image(
            store.read_blob(project, result.contact_sheet_asset_id),
            caption="Cover wrap, then facing pairs 2/3 through 10/11",
            width="stretch",
        )
        st.dataframe(
            [
                {
                    "pages": f"{e.slot.left_page}/{e.slot.right_page}",
                    "phase": e.slot.phase,
                    "energy": e.slot.visual_energy,
                    "photo frame coverage": round(e.image_area_fraction, 3),
                    "display ink coverage": round(e.headline_ink_fraction, 3),
                    "Bible version": e.bible_after.version,
                    "source": e.source,
                }
                for e in result.spreads
            ],
            hide_index=True,
            width="stretch",
        )
        st.write("Issue coherence · " + result.coherence.verdict.value)
        st.caption(result.coherence.rationale)
        for finding in result.coherence.findings:
            st.write(finding.description + " " + finding.actionable_fix)
        with st.expander("Physical page and printer mapping"):
            st.json(result.page_map.model_dump(mode="json"))
            st.json([s.model_dump(mode="json") for s in result.printer_sheets])
        st.caption("This is an issue proof. Owner approval is not inferred from model selection.")
        with st.expander("Revise an issue spread"):
            st.caption(
                "Creates a new issue version and keeps the other spreads. Recomposition uploads selected photos and proof images and incurs model charges."
            )
            with st.form("revise-issue"):
                slot_id = st.selectbox("Spread to revise", [s.slot.id for s in result.spreads])
                instruction = st.text_area("Art direction for this revision")
                replacement = st.selectbox(
                    "Replacement story",
                    [None] + [s.id for s in store.list("story", IngestedStory, project)],
                    format_func=lambda s: s or "Keep current story",
                )
                regenerate = st.checkbox("Recompose the spread", value=True)
                revise = st.form_submit_button("Queue issue revision")
            if revise:
                if not instruction.strip() or (replacement and not regenerate):
                    st.error("Add art direction. A replacement story requires recomposition.")
                else:
                    Queue(store).submit(
                        Command(
                            project_id=project,
                            payload=ReviseIssueCommand(
                                issue_id=result.id,
                                expected_evidence_fingerprint=result.evidence_fingerprint,
                                corrections=[
                                    IssueCorrection(
                                        slot_id=slot_id,
                                        instruction=instruction,
                                        replacement_story_id=replacement,
                                        regenerate=regenerate,
                                    )
                                ],
                            ),
                        )
                    )
                    st.success("Issue revision queued.")
    return [e.spread.scene_id for e in result.spreads]


def issue_exports(store, project):
    results = store.list("issue", IssueResult, project)
    if not results:
        return
    key = st.selectbox("Reader issue to download", [r.id for r in reversed(results)])
    for result in [r for r in results if r.id == key]:
        with st.expander("Twelve-page issue · " + result.id):
            st.download_button(
                "Download twelve-page reader PDF",
                store.read_blob(project, result.reader_pdf_asset_id),
                file_name=result.id + "-reader.pdf",
                mime="application/pdf",
                key="issue-reader-" + result.id,
                on_click="ignore",
            )
            st.download_button(
                "Download issue and page map",
                result.model_dump_json(indent=2),
                file_name=result.id + ".json",
                mime="application/json",
                key="issue-map-" + result.id,
                on_click="ignore",
            )
