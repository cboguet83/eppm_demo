"""Storage-independent renderers shared by scoped business UI tests."""


def project_permission_dialog(path, actor, action="edit"):
    """Render the actual project popup with a current application identity."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_project_workspace
    from app.presentation.components.project_dialogs import open_create_project_dialog, open_edit_project_dialog
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    workspace = create_project_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    if action == "create":
        open_create_project_dialog(workspace)
    else:
        open_edit_project_dialog(1, workspace, read_only=True)


def permission_control_app(path, actor, surface):
    """Render real services, including direct modal entry after a stale browser event."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_collaboration_service, create_planning_workspace
    from app.presentation.pages import collaboration, planning

    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    service = create_collaboration_service(path, access=access)
    workspace = create_planning_workspace(path, access=access)
    surfaces = {
        "contacts": lambda: collaboration.render_project_contacts(1, service),
        "log": lambda: collaboration.render_project_log(1, service),
        "add_contact": lambda: collaboration._contact_dialog(1, service),
        "remove_contact": lambda: collaboration._remove_contact_dialog(1, service, 1),
        "edit_event": lambda: collaboration._event_dialog(1, service),
        "project_tags": lambda: planning._manage_project_tags_dialog(1, "Visible", workspace),
        "task_tags": lambda: planning._manage_task_tags_dialog(10, "Forged label", workspace),
        "project_pools": lambda: planning._manage_project_resource_pools_dialog(1, "Visible", workspace),
        "task_pools": lambda: planning._manage_task_resource_pools_dialog(10, "Forged label", 2, workspace),
        "import": lambda: planning._schedule_csv_dialog(workspace, 1, "import_csv_template"),
        "allocations": lambda: planning._pool_allocations_dialog(1, workspace),
        "group_allocations": lambda: planning._pool_allocations_dialog(0, workspace, group_id=1),
    }
    surfaces[surface]()


def scoped_planning_app(path, actor):
    """Run the complete planner with real scoped services and component event input."""
    import streamlit as st
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_planning_workspace
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages.planning import render_planning_milestones, _handle_gantt_component_change

    set_current_locale("en")
    workspace = create_planning_workspace(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    event = st.session_state.pop("before_event", None)
    if event:
        st.session_state["planning_lazy_gantt"] = event
        _handle_gantt_component_change("planning_lazy_gantt", workspace)
    render_planning_milestones(workspace)


def tag_catalog_app(path, actor, surface):
    """Render one tag catalog with an explicit application actor."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_tag_service
    from app.presentation.i18n import set_current_locale
    from app.presentation.pages import tags

    set_current_locale("en")
    service = create_tag_service(path, access=BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits())))
    {
        "group": tags.render_tag_groups, "dictionary": tags.render_tag_dictionary,
        "project": tags.render_project_tags, "task": tags.render_task_tags,
    }[surface](service)


def shared_catalog_app(path, actor, surface):
    """Render a shared catalog through the actual actor-required composition root."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_organization_service
    from app.presentation.pages import organization

    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    getattr(organization, "render_" + surface)(create_organization_service(path, access=access))


def shared_directory_dialog_app(path, actor, surface, record_id=0):
    """Keep a real directory dialog open while AppTest submits its widgets."""
    from app.application.services.access import AuthorizationPolicy, SessionLimits
    from app.application.services.business_access import BusinessAccess
    from app.main import create_organization_service
    from app.presentation.components import organization_dialogs as dialogs
    from app.presentation.components.organization_frames import functions_frame
    from app.presentation.i18n import set_current_locale

    set_current_locale("en")
    access = BusinessAccess(actor, AuthorizationPolicy(lambda: 1000, SessionLimits()))
    service = create_organization_service(path, access=access)
    functions = functions_frame(service.get_all_functions())
    if surface == "type_add":
        dialogs._open_add_function_type_dialog(service)
    elif surface == "type_edit":
        record = service.get_function_type_by_id(record_id)
        dialogs._open_edit_function_type_dialog(service, record_id, record.function_type)
    elif surface == "type_delete":
        dialogs._open_delete_function_type_dialog(service, record_id, "Reviewed type")
    elif surface == "employee_add":
        dialogs._open_add_employee_dialog(service, functions)
    elif surface == "employee_edit":
        dialogs._open_edit_employee_dialog(service, record_id, functions)
    elif surface == "employee_delete":
        dialogs._open_delete_employee_dialog(service, record_id, "Reviewed employee")
