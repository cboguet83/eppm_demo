"""Native popup cancellation and fresh authorization on fragment interactions."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.application.services.projects import ProjectService
from app.main import create_project_service
from tests.postgresql.test_portfolio_project_modal import business, dashboard_business, runtime
from tests.test_fragment_reruns import FragmentRun
from tests.test_project_dialog_performance import project_screen


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_permission_read_is_shared_within_render_but_fresh_on_fragment_interaction(business, operation):
    path, _, _, _, manager = business
    preview = create_project_service(path, access=manager).generate_project_id() if operation == "create" else 1
    key = f"portfolio_{operation}_manager_{preview}"
    app = AppTest.from_function(project_screen, args=(path, manager.actor, operation))
    reads = []
    before = []
    original = ProjectService.permissions

    def permissions(service):
        reads.append(service)
        return original(service)

    rerun = FragmentRun(key, lambda: before.append(len(reads)))
    with patch.object(ProjectService, "permissions", permissions):
        rerun.run(app)
    # Creation also checks before preparing references. Editing reads the project
    # through its separately authorized service before entering the dialog.
    assert before == [2 if operation == "create" else 1]
    assert len(reads) == before[0] + 1
    rerun.assert_isolated()


def cancellation_screen(path, access, operation):
    """Open real native services and dispatch the retained Cancel interaction."""
    import pandas as pd
    import streamlit as st
    from app.main import (
        create_organization_service, create_resource_pool_service, create_tag_service,
    )
    from app.presentation.components import organization_dialogs as org
    from app.presentation.components import resource_pool_dialogs as pools
    from app.presentation.components import tag_dialogs as tags
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    organization = create_organization_service(path, access=access)
    resources = create_resource_pool_service(path, access=access)
    tag_service = create_tag_service(path, access=access)
    empty = pd.DataFrame()
    actions = {
        "function": (org._open_add_function_dialog, (organization, empty, empty)),
        "team": (org._open_add_team_dialog, (organization, empty)),
        "function_type": (org._open_add_function_type_dialog, (organization,)),
        "employee": (org._open_add_employee_dialog, (organization, empty)),
        "pool": (pools._open_add_pool_dialog, (resources,)),
        "pool_group": (pools._open_add_pool_dialog, (resources,)),
        "tag": (tags._open_add_tag_dialog, (tag_service, empty)),
        "tag_group": (tags._open_add_tag_group_dialog, (tag_service,)),
        "mapping": (pools._open_add_pool_mapping_dialog, (
            resources, 1, pd.DataFrame([{"team_id": 999, "team_name": "Stale choice"}]), empty,
        )),
    }
    if st.session_state.pop("test_open_popup", False):
        render, arguments = actions[operation]
        render(*arguments)


@pytest.mark.parametrize("operation", [
    "function", "team", "function_type", "employee", "pool", "pool_group", "tag", "tag_group", "mapping",
])
def test_cancel_closes_native_creation_popup_without_writing_or_leaving_readiness_elements(business, authorized, operation):
    from hashlib import sha256
    import psycopg
    from psycopg import sql

    path, _, _, _, manager = business

    def fingerprint():
        digest = sha256()
        with psycopg.connect(authorized.setup.operator_url) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='eppm' ORDER BY tablename").fetchall()
            for (table,) in tables:
                digest.update((table + "\n").encode())
                rows = connection.execute(sql.SQL("SELECT to_jsonb(record)::text FROM eppm.{} record ORDER BY 1").format(sql.Identifier(table)))
                for (row,) in rows:
                    digest.update((row + "\n").encode())
            sequences = connection.execute("""SELECT relname FROM pg_class relation JOIN pg_namespace schema ON schema.oid=relation.relnamespace
                WHERE schema.nspname='eppm' AND relation.relkind='S' ORDER BY relname""").fetchall()
            for (sequence,) in sequences:
                value = connection.execute(sql.SQL("SELECT last_value,is_called FROM eppm.{}").format(sql.Identifier(sequence))).fetchone()
                digest.update(repr((sequence, value)).encode())
        return digest.hexdigest()

    before = fingerprint()
    app = AppTest.from_function(cancellation_screen, args=(path, manager, operation))
    app.session_state["test_open_popup"] = True
    # Dispatch the retained dialog fragment, as the browser does. AppTest.run()
    # alone would close this conditional popup without executing its Cancel code.
    rerun = FragmentRun("cancel", widget_trigger=True, widget_label="Cancel")
    rerun.run(app)
    assert not app.exception and not app.get("dialog")
    assert not app.get("bidi_component")
    assert fingerprint() == before
