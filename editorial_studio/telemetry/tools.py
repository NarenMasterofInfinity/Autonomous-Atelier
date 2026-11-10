"""Local tools share run correlation without becoming billable model calls."""

from contextlib import contextmanager
from time import monotonic
from uuid import uuid4

from editorial_studio.contracts.models import ArtifactEvent, ToolExecutionRecord, WorkflowEvent
from editorial_studio.core.storage import Store, utcnow
from editorial_studio.llm.contracts import CallContext
from editorial_studio.telemetry.redaction import Redactor


@contextmanager
def tool_span(
    store: Store,
    context: CallContext,
    tool_name: str,
    input_asset_id: str | None = None,
    redactor: Redactor | None = None,
):
    record = ToolExecutionRecord(
        tool_call_id=uuid4().hex,
        project_id=context.project_id,
        run_id=context.run_id,
        spread_id=context.spread_id,
        parent_call_id=context.parent_call_id,
        tool_name=tool_name,
        input_asset_id=input_asset_id,
        status="started",
    )
    store.put_records(("tool", record.tool_call_id, context.project_id, record))
    started = monotonic()
    try:
        yield record
    except BaseException as error:
        record.status = (
            "cancelled" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
        )
        record.error_summary = (redactor or Redactor()).text(str(error))
        raise
    else:
        record.status = "completed"
    finally:
        record.elapsed_ms = (monotonic() - started) * 1000
        entries = [("tool", record.tool_call_id, context.project_id, record)]
        for asset_id in record.output_asset_ids:
            event = WorkflowEvent(
                event_id=uuid4().hex,
                project_id=context.project_id,
                run_id=context.run_id,
                spread_id=context.spread_id,
                timestamp=utcnow(),
                payload=ArtifactEvent(artifact_id=asset_id, action="created"),
            )
            entries.append(("event", event.event_id, context.project_id, event))
        store.put_records(*entries)
