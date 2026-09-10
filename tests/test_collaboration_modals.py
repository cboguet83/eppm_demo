"""Real scoped modal submissions preserve sibling sections and current write guards."""

from contextlib import closing
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.collaboration import CollaborationService
from app.infrastructure.database.connection import get_db
from tests.test_business_transaction_security import business as business
from tests.test_scoped_portfolio_collaboration_ui import contacts as contacts
from tests.test_fragment_reruns import FragmentRun


def modal_app(path, actor, surface, identity):
    """Compose both lists and a summary outside their independently updated areas."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_collaboration_service
    from app.presentation.pages.collaboration import (
        _contact_dialog, _event_dialog, render_project_contacts, render_project_log,
    )

    st.session_state["summary_runs"] = st.session_state.get("summary_runs", 0) + 1
    st.sidebar.caption("Account and navigation")
    st.write("Project summary")
    service = create_collaboration_service(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    if not st.session_state.get("prepared"):
        if surface == "contacts":
            _contact_dialog(1, service, identity)
        else:
            _event_dialog(1, service)
        st.session_state["prepared"] = True
    render_project_contacts(1, service)
    render_project_log(1, service)


def interaction(app, surface, values, before=lambda: None):
    def prepare():
        before()
        submitted = dict(app.session_state[f"project_{surface}_1_modal_state"]["form"]["values"])
        submitted.update(values)
        rerun.widget_json = {"action": {"kind": "save", "values": submitted}}

    rerun = FragmentRun(f"project_{surface}_1_modal", prepare)
    rerun.run(app)
    rerun.assert_isolated()
    return rerun


@pytest.mark.parametrize("surface", ["contacts", "log"])
def test_successful_modal_save_updates_only_its_list_and_ignores_a_replayed_submit(contacts, surface):
    path, editor, contact_id, _ = contacts
    app = AppTest.from_function(modal_app, args=(path, editor.actor, surface, contact_id))
    reads = []
    sibling_method = "list_events" if surface == "contacts" else "list_contacts"
    original = getattr(CollaborationService, sibling_method)

    def read(service, *args, **kwargs):
        reads.append(1)
        return original(service, *args, **kwargs)

    initial_reads = []
    values = {"function_id": "30"} if surface == "contacts" else {"title": "Saved locally", "description": "First\nSecond"}
    with patch.object(CollaborationService, sibling_method, read):
        rerun = interaction(app, surface, values, lambda: initial_reads.append(len(reads)))
    assert app.session_state["summary_runs"] == 1
    assert len(reads) == initial_reads[0]
    assert f"project_{surface}_1_modal_state" not in app.session_state
    assert not app.error
    repeated = FragmentRun(f"project_{surface}_1_modal", widget_json=rerun.widget_json)
    repeated.run(app)
    repeated.assert_isolated()
    with closing(get_db(path)) as connection:
        if surface == "contacts":
            assert connection.execute("SELECT function_id FROM project_contact WHERE id=?", (contact_id,)).fetchone() == (30,)
        else:
            assert connection.execute("SELECT title,description FROM project_log_event WHERE project_id=1").fetchall() == [("Saved locally", "First\nSecond")]


@pytest.mark.parametrize("surface", ["contacts", "log"])
@pytest.mark.parametrize("change", ["disabled", "revoked"])
def test_retained_modal_submission_cannot_write_after_access_is_removed(business, contacts, surface, change):
    path, service, admin, editor, _ = business
    contact_id = contacts[2]
    app = AppTest.from_function(modal_app, args=(path, editor.actor, surface, contact_id))

    def remove_access():
        if change == "disabled":
            service.set_status(admin, editor.actor.user_id, "disabled")
        else:
            for assignment in service.assignments(admin, editor.actor.user_id):
                service.revoke(admin, assignment["id"])

    interaction(app, surface, {"function_id": "30"} if surface == "contacts" else {"title": "Forbidden"}, remove_access)
    assert app.session_state["summary_runs"] == 1
    assert "not permitted" in app.error[0].value
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT function_id FROM project_contact WHERE id=?", (contact_id,)).fetchone() == (10,)
        assert connection.execute("SELECT count(*) FROM project_log_event").fetchone() == (0,)


@pytest.mark.parametrize("values", [{"function_id": "nan"}, {"function_id": "0"}, {"function_id": True}, {"id": "999"}])
def test_malformed_contact_submissions_remain_in_the_modal_without_writing(contacts, values):
    path, editor, contact_id, _ = contacts
    app = AppTest.from_function(modal_app, args=(path, editor.actor, "contacts", contact_id))
    interaction(app, "contacts", values)
    assert app.session_state["project_contacts_1_modal_state"]["form"]["error"]
    assert app.session_state["summary_runs"] == 1
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT function_id FROM project_contact WHERE id=?", (contact_id,)).fetchone() == (10,)
