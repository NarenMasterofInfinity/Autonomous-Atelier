"""Streamlit is a viewer and command producer. Start the worker separately."""

import streamlit as st

from editorial_studio.core.jobs import Command, ModelCommand, Queue, ReconcileCommand
from editorial_studio.core.storage import Store, identifier
from editorial_studio.llm.contracts import ImageRequest, TextRequest
from editorial_studio.settings import load_settings
from editorial_studio.ui.creative import creative_inputs, render_creative
from editorial_studio.ui.identity import identity_inputs, render_identity
from editorial_studio.ui.issue import issue_exports, issue_inputs, render_issues
from editorial_studio.ui.production import production_exports
from editorial_studio.ui.reference_atlas import reference_exports, render_reference_atlas
from editorial_studio.ui.reference_composition import (
    reference_composition_exports,
    reference_composition_inputs,
    render_reference_compositions,
)
from editorial_studio.ui.studio import render_exports, render_studio
from editorial_studio.ui.telemetry import render_logs
from editorial_studio.ui.tournament import render_tournaments, tournament_exports, tournament_inputs
from editorial_studio.ui.workflow import render_workflow, workflow_inputs


def main():
    st.set_page_config(page_title="Editorial Studio", page_icon="◧", layout="wide")
    st.title("Autonomous Editorial Studio")
    st.caption("M10A · Editorial references, expressive typography, and visual composition")
    settings = load_settings()
    if not (settings.data_root / "studio.sqlite3").exists():
        st.info("Initialize storage first: python -m editorial_studio.worker --initialize")
        return
    store = Store(settings.data_root, readonly=True)
    project_id = st.sidebar.text_input("Project", "m10a-references")
    try:
        identifier(project_id)
    except ValueError:
        st.error("Project IDs use letters, digits, underscores, or hyphens (up to 128 characters).")
        return
    tabs = st.tabs(["Inputs", "Spread Studio", "Logs & Telemetry", "Export"])
    with tabs[0]:
        reference_composition_inputs(store, project_id)
        workflow_inputs(store, project_id)
        creative_inputs(store, project_id)
        tournament_inputs(store, project_id)
        issue_inputs(store, project_id)
        identity_inputs(store, project_id)
        st.subheader("Infrastructure checks")
        st.write(
            "Submit a small provider check to the background worker. Each submission can incur "
            "an API charge; refreshes only read stored results."
        )
        with st.form("smoke"):
            kind = st.radio("Call type", ["Text", "Image"], horizontal=True)
            prompt = st.text_area("Prompt", "Describe editorial restraint in one short sentence.")
            submitted = st.form_submit_button("Queue check", disabled=not prompt.strip())
        if submitted:
            request = (
                TextRequest(
                    model=settings.text_model,
                    prompt=prompt,
                    reasoning_effort=settings.reasoning_effort,
                    max_output_tokens=settings.max_output_tokens,
                )
                if kind == "Text"
                else ImageRequest(
                    model=settings.image_model,
                    prompt=prompt,
                    quality=settings.image_quality,
                    size=settings.image_size,
                )
            )
            command = Command(project_id=project_id, payload=ModelCommand(request=request))
            Queue(store).submit(command)
            st.success(f"Queued {command.id}. Run python -m editorial_studio.worker separately.")
        with st.expander("Recover a known response"):
            with st.form("reconcile"):
                call_id = st.text_input("Ambiguous call ID")
                recover = st.form_submit_button("Queue response retrieval")
            if recover and call_id:
                Queue(store).submit(
                    Command(project_id=project_id, payload=ReconcileCommand(call_id=call_id))
                )
                st.success("Queued retrieval. No new generation request will be submitted.")
        st.dataframe(
            [
                {"job": j.command.id, "status": j.status, "error": j.error}
                for j in Queue(store).list(project_id)
            ],
            width="stretch",
        )
    with tabs[1]:

        @st.fragment(run_every="2s")
        def live_studio():
            composition_preferred = render_reference_compositions(store, project_id)
            render_workflow(store, project_id)
            reference_preferred = render_reference_atlas(store, project_id)
            issue_preferred = render_issues(store, project_id)
            tournament_preferred = render_tournaments(store, project_id)
            creative_preferred = render_creative(store, project_id)
            preferred = render_identity(store, project_id)
            preferred = (
                composition_preferred
                or reference_preferred
                or issue_preferred
                or tournament_preferred
                or creative_preferred
                or preferred
            )
            render_studio(store, project_id, preferred)

        live_studio()
    with tabs[2]:

        @st.fragment(run_every="2s")
        def live_logs():
            render_logs(store, project_id)

        live_logs()
    with tabs[3]:
        reference_composition_exports(store, project_id)
        tournament_exports(store, project_id)
        issue_exports(store, project_id)
        production_exports(store, project_id)
        reference_exports(store, project_id)
        render_exports(store, project_id)


if __name__ == "__main__":
    main()
