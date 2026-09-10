"""Fixed-role access administration, explicit scopes and immutable audit inspection."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import json

import streamlit as st

from app.application.services.access import AccessService
from app.domain.access.models import APPLICATION_ROLES, ROLE_PERMISSIONS, USER_STATES, Actor, ReauthenticationRequired, normalize_scope
from app.presentation.components.action_table import action_table
from app.presentation.i18n import t


_VALIDATION_KEYS = {
    "At least one active access administrator must remain.": "last_admin",
    "This operation is unavailable or not permitted.": "denied",
    "Select at least one reference value.": "empty",
    "Reference IDs must be positive integers.": "ids",
    "Invalid scope structure.": "structure",
    "Choose all projects, named projects, or nonempty property conditions.": "kind",
    "Invalid property condition.": "condition",
    "Invalid property identifier.": "property_id",
    "Use equality with one value or membership in a nonempty set.": "operator",
    "Unknown fixed role.": "role",
    "Application administrator roles require explicit all-project scope.": "admin_scope",
    "Scope contains a missing project reference.": "project_missing",
    "Property is not in the scope allowlist.": "property_forbidden",
    "Scope contains a missing or unsupported property.": "property_missing",
    "Scope contains a missing categorical value.": "value_missing",
    "Revoke the invalid assignment before granting its replacement.": "replacement",
    "Use the configured OIDC issuer.": "issuer",
    "Unknown user status.": "status",
    "Invalid text value.": "text",
    "A nonempty value is required.": "required",
}


def _validation_message(message: str) -> str:
    key = _VALIDATION_KEYS.get(message)
    return _label("errors." + key, message) if key else message


def _label(key: str, default: str) -> str:
    return t("access." + key, default=default)


def _role_label(role: str) -> str:
    labels = {"project_viewer": "Project viewer", "project_editor": "Project editor",
              "project_approver": "Project approver", "access_admin": "Access administrator",
              "business_admin": "Business administrator"}
    return _label("roles." + role, labels.get(role, role))


def _permission_label(permission: str) -> str:
    labels = {"project.read": "View projects", "project.edit": "Edit projects", "project.approve": "Approve projects",
              "project.create": "Create projects", "project.delete": "Delete projects",
              "project.protected_properties": "Edit protected properties", "business.manage": "Manage shared business data",
              "access.manage": "Manage application access"}
    return _label("permissions." + permission.replace(".", "_"), labels.get(permission, permission))


def _scope_summary(encoded: str, catalog: dict[str, dict[str, object]]) -> str:
    try:
        scope = normalize_scope(json.loads(encoded))
    except (ValueError, TypeError):
        return _label("invalid_scope", "Invalid scope")
    if scope.kind == "all":
        return _label("all", "All projects")
    if scope.kind == "projects":
        return _label("projects", "Projects") + ": " + ", ".join(f"#{value}" for value in scope.project_ids)
    conditions = []
    for condition in scope.conditions:
        property_info = catalog.get(condition.property_id, {})
        values = {item["id"]: item["label"] for item in property_info.get("values", [])}
        selected = ", ".join(str(values.get(value, f"#{value}")) for value in condition.value_ids)
        conditions.append(str(property_info.get("label", condition.property_id)) + " = " + selected)
    return (" " + _label("and", "and") + " ").join(conditions)


@contextmanager
def _access_errors() -> Iterator[None]:
    """Handle authorization failures inside the fragment that is being rerun."""
    try:
        yield
    except ReauthenticationRequired:
        st.warning(_label("reauthenticate", "Sign in again before changing application access."))
        st.link_button(_label("sign_in_again", "Sign in again"), "/auth/login", type="primary")
    except ValueError as error:
        st.error(_validation_message(str(error)))


def render_access_management(service: AccessService, actor: Actor) -> None:
    """Keep account controls independent from navigation and the audit report."""
    st.header(_label("title", "Application access"))
    with _access_errors():
        users_tab, audit_tab = st.tabs([_label("users", "Users"), _label("audit", "Security audit")])
        with users_tab:
            _users(service, actor)
        with audit_tab:
            events = service.audit(actor)
            for event in events:
                event["time"] = datetime.fromtimestamp(int(event["occurred_at"]), UTC).isoformat(timespec="seconds")
            action_table(events, [("time", _label("time", "Time (UTC)")),
                                  ("actor", _label("actor", "Actor")), ("target", _label("target", "Target")),
                                  ("action", _label("action", "Action")), ("outcome", _label("outcome", "Outcome")),
                                  ("details_json", _label("details", "Details")),
                                  ("correlation_id", _label("reference", "Reference"))], {}, key="access_audit")


@st.fragment
def _users(service: AccessService, actor: Actor) -> None:
    """Refresh selected-account details without rerunning the application shell."""
    with _access_errors():
        _user_controls(service, actor)


def _user_controls(service: AccessService, actor: Actor) -> None:
    search = st.text_input(_label("search", "Search accounts"), key="access_user_search")
    users = service.list_users(actor, search)
    choices = {user["id"]: user for user in users}
    user_id = st.selectbox(_label("account", "Application account"), list(choices), index=None,
                          format_func=lambda value: f'{value} · {choices[value]["display_name"]} · '
                          + _label("states." + choices[value]["status"], choices[value]["status"]),
                          key="access_selected_user")
    with st.expander(_label("preregister", "Pre-register a provider identity")):
        with st.form("access_preregister"):
            st.caption(_label("issuer", "Configured issuer") + ": " + service.issuer)
            subject = st.text_input(_label("subject", "Exact provider subject"))
            name = st.text_input(_label("display_name", "Display name"))
            if st.form_submit_button(_label("register", "Create pending account")):
                service.register(actor, service.issuer, subject, name)
                st.rerun()
    if user_id is None:
        return
    with st.form("access_status"):
        states = sorted(USER_STATES)
        status = st.selectbox(_label("status", "Account status"), states,
                              format_func=lambda value: _label("states." + value, value),
                              index=states.index(choices[user_id]["status"]))
        if st.form_submit_button(_label("save_status", "Save account status")):
            service.set_status(actor, user_id, status)
            st.rerun()
    assignments = service.assignments(actor, user_id)
    catalog = {str(item["property_id"]): item for item in service.scope_catalog(actor)}
    for assignment in assignments:
        st.write(f'#{assignment["id"]} · {_role_label(str(assignment["role"]))}')
        st.caption(_scope_summary(str(assignment["scope_json"]), catalog))
        if assignment["problem"]:
            st.warning(_validation_message(str(assignment["problem"])))
        if st.button(_label("revoke", "Revoke assignment"), key=f'access_revoke_{assignment["id"]}'):
            service.revoke(actor, int(assignment["id"]))
            st.rerun()
    _assignment_editor(service, actor, user_id)
    st.subheader(_label("explain", "Explain effective access"))
    with st.form("access_explain"):
        project_id = st.number_input(_label("project_id", "Project reference"), min_value=1, step=1, key="access_explain_project")
        check = st.form_submit_button(_label("check", "Check effective access"))
    if check:
        explanation = service.effective_access(actor, user_id, int(project_id))
        if not explanation:
            st.info(_label("no_access", "No assignment grants access to this project."))
        for item in explanation:
            st.write(f'#{item["assignment_id"]} · {_role_label(str(item["role"]))}: ' + ", ".join(_permission_label(value) for value in item["permissions"]))
            if item["requires_mfa"]:
                st.caption(_label("mfa", "Administrator permissions also require a provider-verified MFA session."))


@st.fragment
def _assignment_editor(service: AccessService, actor: Actor, user_id: int) -> None:
    """Rerun dependent scope controls while retaining the account and its grants."""
    with _access_errors():
        # This protected read reauthorizes every fragment run, including roles
        # with static all-project scope that need no project-choice query.
        catalog = {str(item["property_id"]): item for item in service.scope_catalog(actor)}
        st.subheader(_label("grant", "Assign a role"))
        role = st.selectbox(_label("role", "Fixed role"), list(ROLE_PERMISSIONS), format_func=_role_label, key="access_new_role")
        st.caption(" · ".join(_permission_label(value) for value in sorted(ROLE_PERMISSIONS[role])))
        scope = _scope_editor(service, actor, role, catalog)
        if st.button(_label("save_grant", "Grant access"), key="access_grant"):
            service.grant(actor, user_id, role, scope)
            st.rerun()


def _scope_editor(
    service: AccessService, actor: Actor, role: str, catalog: dict[str, dict[str, object]],
) -> dict[str, object]:
    if role in APPLICATION_ROLES:
        st.info(_label("global_admin", "This administrator role applies to the whole application."))
        return {"kind": "all"}
    kinds = {"projects": _label("named_projects", "Named projects"),
             "properties": _label("properties", "Matching properties"), "all": _label("all", "All projects")}
    kind = st.selectbox(_label("scope", "Assignment scope"), list(kinds), format_func=kinds.get, key="access_scope_kind")
    if kind == "all":
        return {"kind": "all"}
    if kind == "projects":
        search = st.text_input(_label("search_projects", "Search project names or references"), key="access_project_search")
        choices = {int(item["id"]): item["name"] for item in service.scope_project_choices(actor, search)}
        selected = st.multiselect(_label("projects", "Projects"), list(choices),
                                  format_func=lambda value: f"{value} · {choices[value]}",
                                  key="access_scope_projects")
        return {"kind": kind, "project_ids": selected}
    st.caption(_label("protected", "Scope-eligible properties are protected. All conditions must match; add separate assignments for alternatives."))
    selected = st.multiselect(_label("conditions", "Properties to match"), list(catalog),
                              format_func=lambda value: str(catalog[value]["label"]),
                              key="access_scope_properties")
    conditions = []
    for property_id in selected:
        values = {int(item["id"]): str(item["label"]) for item in catalog[property_id]["values"]}
        operator = st.selectbox(_label("operator", "Operator"), ["eq", "in"],
                                format_func=lambda value: _label("operators." + value, value),
                                key=f"access_operator_{property_id}")
        chosen = st.multiselect(str(catalog[property_id]["label"]), list(values), format_func=values.get,
                                max_selections=1 if operator == "eq" else None, key=f"access_values_{property_id}")
        conditions.append({"property_id": property_id, "operator": operator, "value_ids": chosen})
    return {"kind": kind, "conditions": conditions}
