from streamlit.testing.v1 import AppTest

from editorial_studio.core.jobs import Queue
from editorial_studio.llm.contracts import TextRequest
from editorial_studio.llm.gateway import Gateway


def app_source(root):
    return f"""
import editorial_studio.app as app
from editorial_studio.settings import Settings
from pathlib import Path
app.load_settings=lambda:Settings(data_root=Path({str(root)!r}))
app.main()
"""


def test_all_telemetry_views_render_without_issuing_calls(
    store, pricing, context, text_result, provider_factory
):
    provider = provider_factory([text_result])
    gateway = Gateway(store, provider, pricing)
    request = TextRequest(
        model="gpt-6-luna", prompt="Test view", reasoning_effort="medium", max_output_tokens=512
    )
    gateway.invoke(context, request)
    gateway.invoke(context, request)  # same stored payloads in separate call expanders
    app = AppTest.from_string(app_source(store.root), default_timeout=10).run()
    app.sidebar.text_input[0].set_value("project").run()
    assert [tab.label for tab in app.tabs] == [
        "Inputs",
        "Spread Studio",
        "Logs & Telemetry",
        "Export",
    ]
    for view in [
        "Live run",
        "Model calls",
        "Usage and pricing",
        "Timing",
        "Generated assets",
        "Decision journal",
        "Error and recovery",
    ]:
        next(s for s in app.selectbox if s.label == "View").set_value(view).run()
        assert not app.exception, view
    assert provider.calls == 1 and Queue(store).list() == []


def test_ui_submit_queues_one_command_without_executing_it(store):
    app = AppTest.from_string(app_source(store.root), default_timeout=10).run()
    next(b for b in app.button if b.label == "Queue check").click().run()
    jobs = Queue(store).list()
    assert len(jobs) == 1 and jobs[0].status == "queued"
    app.run()
    assert len(Queue(store).list()) == 1 and not app.exception


def test_empty_storage_shows_initialization_instruction(tmp_path):
    app = AppTest.from_string(app_source(tmp_path / "absent")).run()
    assert not app.exception
    assert any("Initialize storage" in message.value for message in app.info)


def test_canvas_view_queues_edits_and_downloads_existing_outputs(store, pricing, provider_factory):
    from editorial_studio.canvas.demo import proof_document
    from editorial_studio.canvas.executor import Executor
    from editorial_studio.canvas.renderer import Renderer
    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.core.jobs import PatchSceneCommand
    from editorial_studio.llm.contracts import CallContext

    context = CallContext(project_id="m1-proof", run_id="ui-test", agent_name="Fixture", stage="M1")
    Executor(SceneRepository(store, "m1-proof"), Renderer(store, "m1-proof")).initialize(
        proof_document("ui-canvas"), context, dpi=72
    )
    app = AppTest.from_string(app_source(store.root), default_timeout=10).run()
    app.sidebar.text_input[0].set_value("m1-proof").run()
    assert not app.exception
    next(slider for slider in app.slider if slider.label == "Opacity").set_value(0.5)
    next(button for button in app.button if button.label == "Queue layer edit").click().run()
    assert not app.exception
    jobs = Queue(store).list("m1-proof")
    assert len(jobs) == 1 and isinstance(jobs[0].command.payload, PatchSceneCommand)


def test_identity_form_queues_tokens_without_rendering_or_model_calls(store):
    from editorial_studio.core.jobs import BuildIdentityCommand

    app = AppTest.from_string(app_source(store.root), default_timeout=10).run()
    next(
        button for button in app.button if button.label == "Build provisional identity"
    ).click().run()
    assert not app.exception
    jobs = Queue(store).list()
    assert len(jobs) == 1 and isinstance(jobs[0].command.payload, BuildIdentityCommand)
    assert jobs[0].command.payload.pairing_id == "quiet-serif"
    assert {p.name for p in jobs[0].command.payload.palette} == {"paper", "ink", "muted", "accent"}
    assert jobs[0].status == "queued"


def test_identity_review_ui_is_explicit_and_binds_current_revision(store):
    from editorial_studio.art_direction.service import build_identity
    from editorial_studio.core.jobs import ReviewIdentityCommand
    from editorial_studio.llm.contracts import CallContext

    context = CallContext(
        project_id="m2-proof", run_id="ui-identity", agent_name="Fixture", stage="M2"
    )
    identity = build_identity(store, context, dpi=72)
    app = AppTest.from_string(app_source(store.root), default_timeout=15).run()
    app.sidebar.text_input[0].set_value("m2-proof").run()
    assert not app.exception
    next(field for field in app.text_input if field.label == "Reviewer name").set_value(
        "UI test reviewer"
    )
    next(
        button for button in app.button if button.label == "Record provisional review"
    ).click().run()
    assert not app.exception
    jobs = Queue(store).list()
    assert len(jobs) == 1 and isinstance(jobs[0].command.payload, ReviewIdentityCommand)
    assert jobs[0].command.payload.identity_id == identity.id
    assert jobs[0].command.payload.expected_revision == 0
    assert identity.review is None
