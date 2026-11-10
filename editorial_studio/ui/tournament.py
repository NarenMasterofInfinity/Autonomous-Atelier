"""View stored candidate brackets and queue explicit generation commands."""

import streamlit as st

from editorial_studio.art_direction.models import ProvisionalIdentity
from editorial_studio.content.ledger import ProvenanceLedger
from editorial_studio.core.jobs import BuildTournamentCommand, Command, Queue
from editorial_studio.creative.tournament_models import TournamentResult
from editorial_studio.photos.models import IngestedStory
from editorial_studio.reference_studio.catalog import references


def tournament_inputs(store, project):
    stories = store.list("story", IngestedStory, project)
    identities = store.list("identity", ProvisionalIdentity, project)
    if not stories or not identities:
        return
    ledger = ProvenanceLedger(store, project)
    examples = references(store, reviewed_only=True)
    with st.expander("Explore new layout directions"):
        st.write(
            "Explore two new visual concepts with three variations each. These arrangements can depart from the reference designs and require visual review. To preserve a reference's composition, use the editorial reference library above. This queues paid model calls and uploads selected photographs and proof renders."
        )
        with st.form("candidate-tournament"):
            story = st.selectbox(
                "Tournament story",
                [s.id for s in stories],
                format_func=lambda key: (
                    ledger.get(next(s.title_block_id for s in stories if s.id == key)).source_text
                ),
            )
            identity = st.selectbox("Tournament identity", [i.id for i in identities])
            chosen_references = st.multiselect(
                "Visual references",
                [r.id for r in examples],
                default=[],
                max_selections=6,
                format_func=lambda key: next(
                    r.design_id + " · " + r.title for r in examples if r.id == key
                ),
                help="Reviewed authored examples guide composition. Their photographs remain reference material.",
            )
            mandate = st.text_area(
                "Tournament direction",
                "Find the strongest story-specific composition. Let photography and typography belong together.",
            )
            submit = st.form_submit_button("Queue six-candidate tournament")
        if submit and mandate.strip():
            Queue(store).submit(
                Command(
                    project_id=project,
                    payload=BuildTournamentCommand(
                        story_id=story,
                        identity_id=identity,
                        mandate=mandate,
                        authored_reference_ids=chosen_references,
                    ),
                )
            )
            st.success("Candidate tournament queued.")


def render_tournaments(store, project):
    results = store.list("tournament", TournamentResult, project)
    if not results:
        return []
    with st.expander("Candidate tournament", expanded=True):
        key = st.selectbox("Tournament", [r.id for r in reversed(results)])
        result = next(r for r in results if r.id == key)
        winner = next(c for c in result.candidates if c.slot_id == result.winner_id)
        st.caption(
            f"Two concepts · six variations · five visual comparisons · {result.state.replace('_', ' ')}"
        )
        st.image(
            store.read_blob(project, result.contact_sheet_asset_id),
            caption="All six candidates; selected candidate is labeled",
            width="stretch",
        )
        st.write("Selected: **" + result.winner_id + "**")
        st.image(store.read_blob(project, winner.png_asset_id), width="stretch")
        with st.expander("Concept directions and selection reasons"):
            for direction in result.directions.concepts:
                st.write("**" + direction.name + "** · " + direction.visual_metaphor)
            for match in result.matches:
                st.write(f"{match.candidate_a} / {match.candidate_b} → {match.winner_id}")
                st.caption(match.assessment.rationale)
                if match.tie_break:
                    st.caption(match.tie_break)
        st.caption("Selection is a model judgment. It does not record owner approval.")
    return [winner.scene_id]


def tournament_exports(store, project):
    for result in store.list("tournament", TournamentResult, project):
        with st.expander("Candidate proofs · " + result.id):
            st.download_button(
                "Download six-candidate PDF",
                store.read_blob(project, result.proof_book_asset_id),
                file_name=result.id + ".pdf",
                mime="application/pdf",
                key="tournament-pdf-" + result.id,
            )
            st.download_button(
                "Download tournament evidence",
                result.model_dump_json(indent=2),
                file_name=result.id + ".json",
                mime="application/json",
                key="tournament-json-" + result.id,
            )
