"""Queue snapshot-bound preflight and download verified print proofs."""

import streamlit as st

from editorial_studio.core.jobs import Command, ExportProductionCommand, Queue
from editorial_studio.creative.issue_models import IssueResult
from editorial_studio.production.models import ProductionExport, ProductionPreflight


def production_exports(store, project):
    issues = store.list("issue", IssueResult, project)
    if not issues:
        return
    with st.expander("Production PDF and preflight", expanded=True):
        key = st.selectbox("Issue for production", [r.id for r in reversed(issues)])
        issue = next(r for r in issues if r.id == key)
        st.caption(
            "A4 trim · 3 mm bleed · embedded subset fonts · minimum 300 native PPI. The check uses the selected frozen issue. Editorial approval remains with you."
        )
        if st.button("Queue production check", key="production-check"):
            Queue(store).submit(
                Command(
                    project_id=project,
                    payload=ExportProductionCommand(
                        issue_id=issue.id, expected_evidence_fingerprint=issue.evidence_fingerprint
                    ),
                )
            )
            st.success("Production preflight queued.")
        for output in reversed(store.list("production_export", ProductionExport, project)):
            if output.issue_id != key:
                continue
            report = store.get("production_preflight", output.id, ProductionPreflight)
            st.write(f"{output.id} · {output.state}")
            if report:
                st.write("Preflight passed" if report.passed else "Preflight blocked publication")
                for finding in report.findings:
                    st.write(f"{finding.severity}: {finding.code} · {finding.description}")
            if output.pdf_asset_id:
                st.download_button(
                    "Download production PDF",
                    store.read_blob(project, output.pdf_asset_id),
                    file_name=output.id + ".pdf",
                    mime="application/pdf",
                    key="print-" + output.id,
                    on_click="ignore",
                )
            st.download_button(
                "Download preflight report",
                store.read_blob(project, output.preflight_asset_id),
                file_name=output.id + "-preflight.json",
                mime="application/json",
                key="preflight-" + output.id,
                on_click="ignore",
            )
