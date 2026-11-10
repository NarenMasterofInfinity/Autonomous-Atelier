"""Read-only views: rerenders never invoke providers or advance work."""

import json

import streamlit as st

from editorial_studio.contracts.models import (
    AttemptRecord,
    ProviderCallRecord,
    ToolExecutionRecord,
    WorkflowEvent,
)
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import ProvisionalText


def shown(value):
    return "unknown" if value is None else value


def payload_view(store: Store, project_id: str, asset_id: str | None, label: str, scope: str = ""):
    if not asset_id:
        st.caption(f"{label}: unknown")
        return
    with st.expander(f"{label} · {asset_id[:12]}"):
        try:
            data = store.read_blob(project_id, asset_id)
            value = json.loads(data)
            if isinstance(value, dict) and isinstance(value.get("images"), list):
                for item in value["images"]:
                    if isinstance(item, dict) and item.get("asset_id"):
                        st.image(store.read_blob(project_id, item["asset_id"]), width=450)
                        item["data_base64"] = "[image bytes retained in downloadable request]"
            st.json(value)
            st.download_button(
                f"Download {label}",
                data,
                f"{asset_id}.json",
                key=f"{label}-{project_id}-{asset_id}-{scope}",
            )
        except (OSError, ValueError, KeyError):
            st.error("Stored asset is missing, corrupt, or inaccessible.")


def render_logs(store: Store, project_id: str):
    calls = store.list("call", ProviderCallRecord, project_id)
    view = st.selectbox(
        "View",
        [
            "Live run",
            "Model calls",
            "Usage and pricing",
            "Timing",
            "Generated assets",
            "Decision journal",
            "Error and recovery",
        ],
    )
    if view == "Live run":
        events = store.list("event", WorkflowEvent, project_id)
        st.dataframe(
            [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "run": e.run_id,
                    "spread": e.spread_id,
                    **e.payload.model_dump(mode="json"),
                }
                for e in events
            ],
            width="stretch",
        )
        for call in calls:
            if call.status == "streaming":
                partial = store.get("partial", call.call_id, ProvisionalText)
                if partial:
                    st.info(f"Provisional · {call.agent_name}: {partial.text}")
    elif view == "Model calls":
        filters = {}
        for attr in ["run_id", "agent_name", "stage", "model_requested", "status"]:
            options = sorted({getattr(c, attr) for c in calls})
            filters[attr] = st.selectbox(attr.replace("_", " ").title(), ["All", *options])
        selected = [
            c for c in calls if all(v == "All" or getattr(c, k) == v for k, v in filters.items())
        ]
        for call in reversed(selected):
            with st.expander(
                f"{call.agent_name} · {call.model_requested} · {call.status} · {call.call_id[:8]}"
            ):
                st.json(call.model_dump(mode="json"))
                payload_view(
                    store, project_id, call.request_payload_asset_id, "Request", call.call_id
                )
                payload_view(
                    store, project_id, call.response_payload_asset_id, "Response", call.call_id
                )
    elif view == "Usage and pricing":
        st.caption(
            "Usage comes from provider responses. Costs are estimates, not invoice totals. "
            "Cache reuses add no new provider tokens or cost."
        )
        originals = [c for c in calls if not c.cache_hit]
        for field in [
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "cache_write_tokens",
            "text_input_tokens",
            "image_input_tokens",
            "image_output_tokens",
        ]:
            values = [getattr(c.usage, field) if c.usage else None for c in originals]
            known = [v for v in values if v is not None]
            st.write(
                f"{field}: {sum(known) if known else 'unknown'} "
                f"({len(values) - len(known)} calls unknown)"
            )
        st.dataframe(
            [
                {
                    "call": c.call_id,
                    "run": c.run_id,
                    "agent": c.agent_name,
                    "spread": c.spread_id,
                    "stage": c.stage,
                    "cache reuse": c.cache_hit,
                    "estimated USD": shown(c.cost.estimated_cost_usd),
                    "reported USD": shown(c.cost.reported_cost_usd),
                    "certainty": c.cost.certainty.value,
                    "billing uncertain": c.cost.billing_uncertain,
                    "pricing version": c.cost.pricing_version,
                }
                for c in calls
            ],
            width="stretch",
        )
    elif view == "Timing":
        st.dataframe(
            [
                {
                    "call": c.call_id,
                    "agent": c.agent_name,
                    "stage": c.stage,
                    "latency ms": shown(c.latency_ms),
                    "attempts": len(c.attempt_ids),
                    "retries": max(0, len(c.attempt_ids) - 1),
                }
                for c in calls
            ],
            width="stretch",
        )
        tools = store.list("tool", ToolExecutionRecord, project_id)
        st.dataframe([t.model_dump(mode="json") for t in tools], width="stretch")
    elif view == "Generated assets":
        for call in calls:
            if call.cache_hit:
                continue
            for asset_id in call.generated_artifact_ids:
                st.write(f"{call.model_requested} · {asset_id}")
                payload_view(store, project_id, call.request_payload_asset_id, "Generation request")
                try:
                    ref = store.asset(project_id, asset_id)
                    if ref.media_type.startswith("image/"):
                        st.image(store.read_blob(project_id, asset_id))
                    st.json(ref.model_dump())
                except (OSError, ValueError, KeyError):
                    st.error("Generated asset is unavailable.")
    elif view == "Decision journal":
        for event in store.list("event", WorkflowEvent, project_id):
            if event.payload.kind in {"decision", "scene", "stage"}:
                st.json(event.model_dump(mode="json"))
        for call in calls:
            if call.visible_decision_summary:
                st.write(f"{call.agent_name}: {call.visible_decision_summary}")
        st.caption("Only emitted decisions and available summaries are shown.")
    else:
        for call in calls:
            if call.status in {"failed", "ambiguous", "cancelled"} or len(call.attempt_ids) > 1:
                st.json(call.model_dump(mode="json"))
        attempts = store.list("attempt", AttemptRecord, project_id)
        st.dataframe([a.model_dump(mode="json") for a in attempts], width="stretch")
        st.caption(
            "Ambiguous submissions require response retrieval or manual provider reconciliation. "
            "Refreshing this view does not retry them."
        )
