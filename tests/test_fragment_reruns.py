"""Reusable real Streamlit fragment dispatch with injected page resources."""

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from unittest.mock import patch

from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.scriptrunner import RerunData, ScriptRunnerEvent
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.local_script_runner import LocalScriptRunner

from app.domain.access.models import Actor
from app.runtime import RuntimeResources

@dataclass
class FragmentRun:
    """Collect only the rerun output, retaining Streamlit's real widget dispatch."""

    widget_key: str
    before_rerun: Callable[[], None] = lambda: None
    fragment_id: str = ""
    dispatched: bool = False
    messages: list[ForwardMsg] = field(default_factory=list)
    widget_json: dict[str, object] | None = None
    widget_index: int | None = None
    full_app_request: bool = False
    widget_id: str = ""
    widget_options: list[str] = field(default_factory=list)
    widget_trigger: bool = False
    widget_label: str = ""

    def runner(self, *args, **kwargs) -> LocalScriptRunner:
        runner = LocalScriptRunner(*args, **kwargs)

        def event_received(sender, event, **event_data):
            if event == ScriptRunnerEvent.ENQUEUE_FORWARD_MSG:
                message = event_data["forward_msg"]
                if self.dispatched:
                    self.messages.append(message)
                elif message.WhichOneof("type") == "delta":
                    delta = message.delta
                    identifiers = (
                        delta.new_element.selectbox.id,
                        delta.new_element.radio.id,
                        delta.new_element.button.id,
                        delta.new_element.bidi_component.id,
                        delta.new_element.component_instance.id,
                        delta.new_element.dataframe.id,
                        delta.add_block.tab_container.id,
                    )
                    identifier = next((value for value in identifiers if value.endswith("-" + self.widget_key)), "")
                    if self.widget_label and delta.new_element.button.label == self.widget_label:
                        identifier = delta.new_element.button.id
                    if identifier:
                        self.widget_id = identifier
                        self.fragment_id = delta.fragment_id
                        self.widget_options = list(delta.new_element.radio.options)
            if event == ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS and not self.dispatched:
                assert self.fragment_id or self.full_app_request, "The interactive control must belong to a fragment"
                self.before_rerun()
                self.dispatched = True
                states = WidgetStates(widgets=runner._session_state.get_widget_states())
                if self.widget_json is not None:
                    widget = next(widget for widget in states.widgets if widget.id.endswith("-" + self.widget_key))
                    if widget.HasField("string_value"):
                        widget.string_value = json.dumps(self.widget_json)
                    else:
                        widget.json_value = json.dumps(self.widget_json)
                if self.widget_index is not None:
                    assert self.widget_id, "The interactive control must have rendered"
                    widget = next((widget for widget in states.widgets if widget.id == self.widget_id), None)
                    if widget is None:
                        widget = states.widgets.add(id=self.widget_id)
                    widget.string_value = self.widget_options[self.widget_index]
                if self.widget_trigger:
                    widget = next((widget for widget in states.widgets if widget.id == self.widget_id), None)
                    if widget is None:
                        widget = states.widgets.add(id=self.widget_id)
                    widget.trigger_value = True
                runner.request_rerun(RerunData(
                    widget_states=states,
                    fragment_id_queue=[] if self.full_app_request else [self.fragment_id],
                ))

        runner.on_event.connect(event_received, weak=False)
        return runner

    def run(self, app: AppTest) -> AppTest:
        """Queue the browser-equivalent fragment request after initial rendering."""
        with patch("streamlit.testing.v1.app_test.LocalScriptRunner", self.runner):
            app.run(timeout=30)
        assert self.dispatched and self.messages
        assert not app.exception
        return app

    def assert_isolated(self) -> None:
        """No navigation or sibling-fragment deltas may be sent on a local update."""
        deltas = [message for message in self.messages if message.WhichOneof("type") == "delta"]
        assert deltas
        assert all(message.delta.fragment_id == self.fragment_id for message in deltas)
        assert all(message.metadata.delta_path[0] != 1 for message in deltas)



def settings_fragment_app(path, actor):
    """Render real protected Settings with a shell counter outside its fragment."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_settings_workspace
    from app.presentation.pages.settings import render_settings_view

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1
    st.sidebar.caption("Navigation remains mounted")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_settings_view(create_settings_workspace(path, access=access))



def navigation_app(path, actor):
    """Navigate composed protected pages while retaining the authorized shell."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_application_workspace
    from app.presentation.shell import render_application

    st.session_state["shell_runs"] = st.session_state.get("shell_runs", 0) + 1
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_application(create_application_workspace(path, access=access))



def portfolio_app(path: RuntimeResources, actor: Actor) -> None:
    """Inject only the authenticated transport into the production portfolio page."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.portfolio import render_portfolio_overview

    set_current_locale("en")
    if st.session_state.get("nav_redirect"):
        st.caption(st.session_state["nav_redirect"])
        return
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    render_portfolio_overview(create_project_workspace(path, access=access))



def project_details_fragment_app(path: RuntimeResources, actor: Actor) -> None:
    """Rerun the production details fragment with its previously displayed row."""
    import pandas as pd
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.portfolio import _render_project_details_panel

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    selected = pd.Series({"id": 1, "name": "Visible", "planned_budget": "0", "actual_budget": "0"})
    _render_project_details_panel(selected, pd.DataFrame(), create_project_workspace(path, access=access))
