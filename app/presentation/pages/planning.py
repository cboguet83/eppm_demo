"""Planning screen using injected task, tag, resource, and project services.

Any marks existing custom-component JSON and DataFrame values at the display
boundary. Authoritative validation and persistence live in application services.
"""

import csv
import datetime
import html
import io
from collections.abc import Callable
from functools import wraps
from app.presentation.assets import component_path
from typing import Any
import pandas as pd
import streamlit as st

from app.presentation.components.dialog import dialog
from app.presentation.components.authorized_cache import authorized_cache
from app.domain.access.models import Permission
import streamlit.components.v1 as components
from app.application.exceptions import (
    OrganizationStorageError,
    PlanningStorageError,
    ProjectStorageError,
    ProjectTypeStorageError,
    ResourcePoolStorageError,
    SchemaStorageError,
    TagStorageError,
)
from app.domain.resources.models import PoolAssignment, PoolCapacityDetail
from app.domain.projects.project import PROJECT_STATUSES
from app.domain.resources.allocation_scope import scoped_assignments
from app.domain.tags.models import ProjectTag, TaskTag
from app.domain.resources.capacity_rules import (
    calculate_pool_scope_daily_usage,
    calculate_daily_overassignments,
    get_projects_consuming_pool_in_period,
    project_pool_status,
)
from app.domain.planning.rules import normalize_progress
from app.domain.planning.plans import ProjectPlan
from app.presentation.components.property_labels import property_label
from app.presentation.components.planning_events import validate_event
from app.presentation.components.planning_workspace import PlanningWorkspace
from app.presentation.components.planning_transport import planning_revision_token
from app.presentation.components.project_dialogs import open_edit_project_dialog
from app.presentation.components.resource_pool_frames import (
    pools_frame,
    groups_frame as resource_groups_frame,
    all_members_frame,
    assignments_frame,
)
from app.presentation.components.tag_frames import (
    get_project_tags_by_project_frame,
    get_task_tags_by_task_frame,
    get_project_tag_group_tags_frame,
    get_task_tag_group_tags_frame,
)
from app.presentation.components.schema_frames import parameters_frame
from app.presentation.components.planning_data import (
    load_planning_catalog,
    load_planning_project_metadata,
    load_dependency_choices,
    load_project_summaries,
    affected_task_projects,
    build_task_payload,
)
from app.presentation.components.planning_transport import pack_pool_payloads
from app.presentation.i18n import get_current_locale, get_section_catalog, t
from app.presentation.navigation import PAGE_SETTINGS
from app.presentation.pages.planning_scenarios import (
    SCENARIO_ACTIONS, MUTATIONS, choose_alternative, close_alternative_view, create_alternative,
    handle_scenario_event, require_edit, scenario_payload,
)


def planning_errors[**P](function: Callable[P, None]) -> Callable[P, None]:
    """Render safe application failures at screen, dialog, and callback boundaries."""

    @wraps(function)
    def render(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            function(*args, **kwargs)
        except (
            ValueError,
            PlanningStorageError,
            OrganizationStorageError,
            ProjectStorageError,
            ProjectTypeStorageError,
            ResourcePoolStorageError,
            SchemaStorageError,
            TagStorageError,
        ) as exc:
            st.error(str(exc))

    return render


def require_change(changed: bool) -> None:
    """Do not report success for a task or association deleted by another session."""
    if not changed:
        raise ValueError("The selected record no longer exists. Refresh and try again.")


def _interactive_gantt(**payload: Any) -> Any:
    """Register the existing component in the active Streamlit runtime."""
    path = component_path("gantt")
    return components.declare_component("interactive_gantt", path=str(path))(**payload)


def _get_gantt_event_nonce(gantt_event: dict[str, Any]) -> str:
    """Return the component nonce, with a deterministic fallback for older events."""
    nonce = gantt_event.get("nonce")
    if nonce:
        return str(nonce)
    return str(hash(frozenset((str(key) + str(value) for key, value in gantt_event.items()))))


def _apply_immediate_gantt_update(
    gantt_event: dict[str, Any], workspace: PlanningWorkspace
) -> bool:
    """Persist date/progress events before Streamlit starts its automatic rerun."""
    action = gantt_event.get("action")
    step_id = gantt_event.get("id")
    try:
        step_id_int = int(step_id)
    except (TypeError, ValueError):
        return False
    if action == "update_dates":
        new_start = str(gantt_event.get("start_date", "")).strip()
        new_end = str(gantt_event.get("end_date", "")).strip()
        try:
            start_date = datetime.date.fromisoformat(new_start)
            end_date = datetime.date.fromisoformat(new_end)
        except ValueError:
            return False
        if end_date < start_date:
            return False
        updated = workspace.planning.update_dates(step_id_int, new_start, new_end)
        require_change(updated)
        st.toast(
            t("planning.toast_dates_updated", id=step_id_int, start=new_start, end=new_end),
            icon="📅",
        )
        return updated
    if action == "update_progress":
        try:
            new_progress = normalize_progress(gantt_event.get("progress"))
        except (TypeError, ValueError):
            return False
        updated = workspace.planning.update_progress(step_id_int, new_progress)
        require_change(updated)
        st.toast(
            t("planning.toast_progress_updated", id=step_id_int, progress=new_progress),
            icon="📊",
        )
        return updated
    return False


def _planning_edit_revision(workspace: PlanningWorkspace) -> tuple:
    """Compare edits against the chart's source format, not portfolio tokens."""
    snapshot = st.session_state.get('planning_chart_snapshot')
    ids = list(snapshot.get('task_source_tokens', {})) if snapshot else []
    return workspace.sources.capture(ids).revision if ids else workspace.revision()


def _apply_step_form(
    event: dict[str, Any], workspace: PlanningWorkspace, fallback_project: int | None = None,
) -> dict[str, Any] | None:
    """Commit a step form once and return the metadata for its targeted patch."""
    name = str(event.get("task_name", "")).strip()
    start = str(event.get("start_date", "")).strip()
    end = str(event.get("end_date", "")).strip()
    if not name or not start or not end:
        return None
    values = dict(
        task_name=name, phase=str(event.get("phase", "")).strip() or "General",
        start_date=start, end_date=end, progress_pct=int(event.get("progress_pct", 0)),
        dependencies=event.get("dependencies", [] if event["action"] == "create_step_full" else None),
        description=str(event.get("description", "")).strip(),
    )
    before = _planning_edit_revision(workspace)
    if event["action"] == "create_step_full":
        project_id = int(event.get("project_id") or fallback_project or 0)
        step_id = workspace.planning.create_milestone(project_id=project_id, **values)
        st.toast(t("planning.toast_step_created", name=name, project_id=project_id), icon="➕")
        return {**event, "id": step_id, "project_id": project_id, "before_revision": before}
    step_id = int(event["id"])
    require_change(workspace.planning.update_milestone(milestone_id=step_id, **values))
    st.toast(t("planning.toast_step_updated", name=name), icon="✏️")
    return {**event, "before_revision": before}


@planning_errors
def _handle_gantt_component_change(widget_key: str, workspace: PlanningWorkspace) -> None:
    """Route filters and inline Gantt mutations before the automatic rerun.

    Filters target the planning workspace so selection widgets update together.
    Inline edits commit before the chart fragment reads the changed task values.
    """
    gantt_event = st.session_state.get(widget_key)
    if not isinstance(gantt_event, dict) or not isinstance(gantt_event.get("action"), str):
        return
    if gantt_event.get("action") not in SCENARIO_ACTIONS | {
        "filter_project",
        "update_dates",
        "update_progress",
        "create_step_full",
        "update_task_full",
        "load_dependency_tasks",
        "load_project_dependencies",
        "save_project_dependencies",
        "load_project_tasks",
        "initialize_planning",
    }:
        return
    nonce = _get_gantt_event_nonce(gantt_event)
    if nonce == st.session_state.get("last_gantt_nonce"):
        return
    st.session_state["last_gantt_nonce"] = nonce
    if gantt_event['action'] in MUTATIONS:
        require_edit(alternative=gantt_event['action'] == 'manage_project_tags')
    if gantt_event['action'] in {'load_project_dependencies', 'save_project_dependencies'}:
        _handle_project_dependency_event(gantt_event, workspace, nonce)
        return
    gantt_event = validate_event(gantt_event)
    if gantt_event['action'] in SCENARIO_ACTIONS:
        handle_scenario_event(gantt_event, workspace)
        if gantt_event['action'] in {'hide_alternatives', 'activate_alternative', 'toggle_baseline'}:
            st.rerun('planning_workspace')
    elif gantt_event.get("action") == "initialize_planning":
        st.session_state.pop("planning_chart_snapshot", None)
    elif gantt_event.get("action") == "load_project_tasks":
        st.session_state["planning_pending_change"] = dict(gantt_event)
    elif gantt_event.get("action") == "load_dependency_tasks":
        try:
            project_id = int(gantt_event.get("project_id"))
        except (TypeError, ValueError):
            return
        response = {"project_id": str(project_id), "nonce": nonce}
        try:
            response['tasks'] = load_dependency_choices(workspace, workspace.revision(), project_id)
        except (ValueError, PlanningStorageError, ProjectStorageError) as exc:
            response['error'] = str(exc)
        st.session_state["planning_dependency_response"] = response
    elif gantt_event.get("action") == "filter_project":
        st.session_state["pending_project_context_filter"] = gantt_event
        st.rerun("planning_workspace")
    elif gantt_event.get("action") in {"create_step_full", "update_task_full"}:
        try:
            change = _apply_step_form(gantt_event, workspace)
        except (ValueError, PlanningStorageError, ProjectStorageError) as exc:
            st.session_state["planning_step_form_error"] = str(exc)
            return
        if change:
            st.session_state["planning_pending_change"] = change
    else:
        before = _planning_edit_revision(workspace)
        if _apply_immediate_gantt_update(gantt_event, workspace):
            st.session_state["planning_pending_change"] = {
                **gantt_event,
                "before_revision": before,
            }


def _handle_project_dependency_event(event: dict[str, Any], workspace: PlanningWorkspace, nonce: str) -> None:
    """Return a correlated result so failed saves retain the component draft."""
    response = {'project_id': event.get('project_id'), 'nonce': nonce, 'action': event['action']}
    try:
        event = validate_event(event)
        if event['action'] == 'load_project_dependencies':
            response['panel'] = workspace.planning.get_project_dependency_panel(event['project_id'])
        else:
            response['panel'] = workspace.planning.save_project_dependencies(
                event['project_id'], event.get('upserts', []), event.get('deleted_ids', []), event.get('revision', ''))
    except (ValueError, PlanningStorageError) as exc:
        response['error'] = str(exc)
    st.session_state['planning_project_dependency_response'] = response


def _normalise_planning_filter_values(value: Any) -> list[str]:
    """Convert scalar and multi-valued project attributes to filter values."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [str(value).strip()]


def _unique_planning_filter_options(series: pd.Series) -> list[str]:
    """Return the sorted distinct values available for one filter field."""
    values = {
        item
        for value in series.tolist()
        for item in _normalise_planning_filter_values(value)
        if item
    }
    return sorted(values, key=str.casefold)


def _apply_planning_flex_filters(
    frame: pd.DataFrame, filters: dict[str, list[str]], match_all_values: bool = False
) -> pd.DataFrame:
    """Apply AND across fields and Any/All matching within each field."""
    filtered = frame.copy()
    for column, selected_values in filters.items():
        if column not in filtered.columns or not selected_values:
            continue
        wanted = {str(value).casefold() for value in selected_values}

        def cell_matches(value: Any) -> bool:
            actual = {item.casefold() for item in _normalise_planning_filter_values(value)}
            return wanted.issubset(actual) if match_all_values else bool(wanted & actual)

        filtered = filtered[filtered[column].apply(cell_matches)]
    return filtered


def _clear_planning_flex_filter_state(*, clear_tracking: bool = False) -> None:
    """Clear only state owned by the planning flexible filter."""
    for key in list(st.session_state):
        if str(key).startswith("planning_flex_"):
            del st.session_state[key]
    if clear_tracking:
        st.session_state.pop("planning_last_flex_signature", None)


def _clear_all_planning_filters() -> None:
    """Reset project, resource and flexible filters before widgets are rendered."""
    _clear_planning_flex_filter_state(clear_tracking=True)
    for key in ("active_resource_pool_filter", "pending_resource_pool_filter",
                "pending_clear_resource_pool_filter", "pending_project_context_filter",
                "target_planning_project_id", "target_planning_task_id"):
        st.session_state.pop(key, None)
    st.session_state["ms_multi_projects"] = []
    st.session_state["planning_statuses"] = ["In Progress"]
    st.session_state["ms_planning_tag_filter"] = []
    st.session_state["last_planning_tag_filter"] = []
    st.session_state["planning_filter_reset"] = st.session_state.get("planning_filter_reset", 0) + 1
    st.session_state.pop("planning_chart_snapshot", None)


def _focus_planning_on_project(gantt_event: dict[str, Any], workspace: PlanningWorkspace | None = None) -> bool:
    """Clear competing filters and focus the planning page on one project."""
    try:
        project_id = int(gantt_event.get("project_id"))
    except (TypeError, ValueError):
        return False
    if project_id <= 0:
        return False
    _clear_planning_flex_filter_state(clear_tracking=True)
    st.session_state.pop("active_resource_pool_filter", None)
    st.session_state.pop("pending_resource_pool_filter", None)
    st.session_state.pop("pending_clear_resource_pool_filter", None)
    st.session_state["ms_planning_tag_filter"] = []
    st.session_state["last_planning_tag_filter"] = []
    scope = str(gantt_event.get("filter_scope", "this"))
    st.session_state["ms_multi_projects"] = (
        workspace.planning.related_project_ids(project_id, scope)
        if workspace and scope != "this" else [project_id]
    )
    project_name = str(gantt_event.get("project_name", "")).strip()
    label = project_name or f"Project #{project_id}"
    st.toast(f"Filtered planning to {label}", icon="🔍")
    return True


def _build_resource_pool_hierarchy(
    workspace: PlanningWorkspace, pools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build a loop-safe tree of pool groups and ungrouped pools for the Gantt."""
    pool_by_id = {int(pool["id"]): pool for pool in pools}
    groups = resource_groups_frame(workspace.resources.group_choices())
    if groups.empty:
        return [
            {
                "key": f"pool:{pool_id}",
                "node_type": "pool",
                "pool_id": pool_id,
                "name": str(pool["name"]),
            }
            for pool_id, pool in sorted(
                pool_by_id.items(), key=lambda item: str(item[1]["name"]).casefold()
            )
        ]
    group_by_id = {
        int(row["id"]): {
            "name": str(row["name"]),
            "description": str(row.get("description")) if pd.notna(row.get("description")) else "",
        }
        for _, row in groups.iterrows()
    }
    members_by_group: dict[int, tuple[list[int], list[int]]] = {}
    child_group_ids: set[int] = set()
    grouped_pool_ids: set[int] = set()
    for row in all_members_frame(workspace.resources.group_membership()).to_dict("records"):
        pool_ids, child_ids = members_by_group.setdefault(int(row["group_id"]), ([], []))
        if pd.notna(row["pool_id"]):
            pool_ids.append(int(row["pool_id"]))
            grouped_pool_ids.add(int(row["pool_id"]))
        if pd.notna(row["child_group_id"]):
            child_ids.append(int(row["child_group_id"]))
            child_group_ids.add(int(row["child_group_id"]))

    def pool_node(pool_id: int, path: tuple[int, ...]) -> dict[str, Any] | None:
        pool = pool_by_id.get(pool_id)
        if pool is None:
            return None
        path_key = "/".join((str(item) for item in path))
        return {
            "key": f"pool:{path_key}:{pool_id}" if path_key else f"pool:{pool_id}",
            "node_type": "pool",
            "pool_id": pool_id,
            "name": str(pool["name"]),
        }

    def group_node(group_id: int, path: tuple[int, ...]) -> dict[str, Any]:
        group = group_by_id[group_id]
        current_path = (*path, group_id)
        path_key = "/".join((str(item) for item in current_path))
        if group_id in path:
            return {
                "key": f"group:{path_key}:cycle",
                "node_type": "group",
                "group_id": group_id,
                "name": group["name"],
                "children": [],
                "descendant_pool_ids": [],
                "cycle_blocked": True,
            }
        direct_pool_ids, direct_child_ids = members_by_group.get(group_id, ([], []))
        children: list[dict[str, Any]] = []
        for child_id in sorted(
            direct_child_ids, key=lambda item: group_by_id.get(item, {}).get("name", "").casefold()
        ):
            if child_id in group_by_id:
                children.append(group_node(child_id, current_path))
        for pool_id in sorted(
            direct_pool_ids,
            key=lambda item: str(pool_by_id.get(item, {}).get("name", "")).casefold(),
        ):
            node = pool_node(pool_id, current_path)
            if node is not None:
                children.append(node)
        return {
            "key": f"group:{path_key}",
            "node_type": "group",
            "group_id": group_id,
            "name": group["name"],
            "description": group["description"],
            "children": children,
            "descendant_pool_ids": sorted(
                {
                    pid
                    for child in children
                    for pid in (
                        [child["pool_id"]]
                        if child["node_type"] == "pool"
                        else child["descendant_pool_ids"]
                    )
                }
            ),
        }

    root_group_ids = sorted(
        set(group_by_id) - child_group_ids, key=lambda item: group_by_id[item]["name"].casefold()
    )
    if not root_group_ids:
        root_group_ids = sorted(group_by_id, key=lambda item: group_by_id[item]["name"].casefold())
    hierarchy = [group_node(group_id, ()) for group_id in root_group_ids]
    for pool_id in sorted(
        set(pool_by_id) - grouped_pool_ids,
        key=lambda item: str(pool_by_id[item]["name"]).casefold(),
    ):
        node = pool_node(pool_id, ())
        if node is not None:
            hierarchy.append(node)
    return hierarchy


@dialog(t("planning.dialog_project_tags_title", default="🏷️ Manage Project Tags"))
@planning_errors
def _manage_project_tags_dialog(
    project_id: int, project_name: str, workspace: PlanningWorkspace
) -> None:
    """Modal dialog for attaching, editing, and deleting tags on a project."""
    if not workspace.projects.projects.permissions().allows(Permission.EDIT, project_id):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    st.markdown(f"#### 📁 {project_name} `[#{project_id}]`")
    df_current_tags = get_project_tags_by_project_frame(
        workspace.tags.get_project_tags_by_project(project_id)
    )
    st.markdown(f"##### {t('planning.current_tags', default='Current Assigned Tags')}")
    if df_current_tags.empty:
        st.info(
            t("planning.no_tags_assigned", default="No tags currently attached to this project.")
        )
    else:
        for _, row in df_current_tags.iterrows():
            pt_id = int(row["id"])
            t_name = row.get("tag_name")
            g_name = row.get("tag_group_name")
            f_name = row.get("free_tag")
            display_label = (
                f"🏷️ {t_name}" if pd.notna(t_name) and str(t_name).strip() else f"🏷️ {f_name}"
            )
            if pd.notna(g_name) and str(g_name).strip():
                display_label = f"[{g_name}] {display_label}"
            c_tag, c_del = st.columns([4, 1])
            c_tag.markdown(
                f"""<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:3px 10px; border-radius:12px; font-weight:600; font-size:12px; display:inline-block; margin-top:4px;">{html.escape(display_label)}</span>""",
                unsafe_allow_html=True,
            )
            if c_del.button("🗑️", key=f"btn_del_pt_{pt_id}", help="Remove tag from project"):
                require_change(workspace.tags.delete_project_tag(pt_id))
                st.toast(t("planning.toast_tag_removed", default="Tag removed!"), icon="🗑️")
                st.rerun()
    st.divider()
    st.markdown(f"##### ➕ {t('planning.attach_new_tag', default='Attach New Tag')}")
    df_tags = get_project_tag_group_tags_frame(workspace.tags.project_tag_choices())
    tag_options = [
        (
            None,
            t(
                "planning.select_dict_tag_placeholder",
                default="-- Select from Tag Dictionary (Optional) --",
            ),
        )
    ] + [(int(r["id"]), str(r["tag"])) for _, r in df_tags.iterrows()]
    selected_tag_tuple = st.selectbox(
        t("planning.select_dict_tag", default="Dictionary Tag"),
        options=tag_options,
        format_func=lambda x: x[1],
        key="sb_attach_proj_tag",
    )
    selected_tag_id = selected_tag_tuple[0] if selected_tag_tuple else None
    free_tag_input = st.text_input(
        t("planning.free_tag_optional", default="Custom / Free Tag (Optional)"),
        placeholder="e.g. Q3-Priority, Pilot-Launch",
        key="ti_attach_proj_free_tag",
    )
    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(
            t("planning.btn_attach_tag", default="Attach Tag"),
            type="primary",
            key="btn_confirm_attach_proj_tag",
        ):
            if selected_tag_id is None and (not free_tag_input.strip()):
                st.error(
                    t(
                        "planning.tag_required_error",
                        default="Please select a dictionary tag or enter a custom tag.",
                    )
                )
            else:
                workspace.tags.create_project_tag(
                    ProjectTag(
                        project_id=project_id,
                        tag_id=selected_tag_id,
                        free_tag=free_tag_input.strip() if free_tag_input.strip() else None,
                    )
                )
                st.toast(
                    t("planning.toast_tag_attached", default="Tag attached to project!"), icon="🏷️"
                )
                st.rerun()
    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_proj_dialog"):
            st.rerun()


@dialog(t("planning.dialog_task_tags_title", default="🏷️ Manage Task Tags"))
@planning_errors
def _manage_task_tags_dialog(task_id: int, task_name: str, workspace: PlanningWorkspace,
                             alternative_event: dict | None = None) -> None:
    """Modal dialog for adding, editing, and deleting tags on a task."""
    from app.application.ports.tag_records import TaskTagRow
    from app.presentation.pages.planning_alternative_editor import selected_plan, save_task_tag

    plan = selected_plan(alternative_event, workspace) if alternative_event else None
    task = (dict(next(row for row in plan.content.tasks if row['id'] == task_id), project_id=plan.project_id)
            if plan else workspace.planning.get_milestone_by_id(task_id))
    if task is None or not workspace.projects.projects.permissions().allows(Permission.EDIT, task["project_id"]):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    task_name = task["task_name"]
    st.markdown(f"#### 📋 {task_name} `[Task #{task_id}]`")
    choices = workspace.tags.task_tag_choices()
    by_id = {row.id: row for row in choices}
    if plan:
        st.caption(plan.name)
        rows = [TaskTagRow(id=index, task_id=task_id, **row,
                          tag_name=by_id[row['tag_id']].tag if row['tag_id'] in by_id else None,
                          tag_group_name=by_id[row['tag_id']].tag_group_name if row['tag_id'] in by_id else None)
                for index, row in enumerate(plan.content.task_tags.get(task_id, []))]
    else:
        rows = workspace.tags.get_task_tags_by_task(task_id)
    df_current_tags = get_task_tags_by_task_frame(rows)
    st.markdown(f"##### {t('planning.current_tags', default='Current Assigned Tags')}")
    if df_current_tags.empty:
        st.info(
            t("planning.no_task_tags_assigned", default="No tags currently attached to this task.")
        )
    else:
        for _, row in df_current_tags.iterrows():
            tt_id = int(row["id"])
            t_name = row.get("tag_name")
            g_name = row.get("tag_group_name")
            f_name = row.get("free_tag")
            display_label = (
                f"🏷️ {t_name}" if pd.notna(t_name) and str(t_name).strip() else f"🏷️ {f_name}"
            )
            if pd.notna(g_name) and str(g_name).strip():
                display_label = f"[{g_name}] {display_label}"
            c_tag, c_del = st.columns([4, 1])
            c_tag.markdown(f"**{display_label}**")
            if c_del.button("🗑️", key=f"btn_del_tt_{tt_id}", help="Remove tag from task"):
                if plan:
                    save_task_tag(alternative_event, workspace, delete_index=tt_id)
                else:
                    require_change(workspace.tags.delete_task_tag(tt_id))
                st.toast(
                    t("planning.toast_task_tag_removed", default="Task tag removed!"), icon="🗑️"
                )
                st.rerun()
    st.divider()
    st.markdown(f"##### ➕ {t('planning.attach_new_task_tag', default='Attach New Tag to Task')}")
    df_tags = get_task_tag_group_tags_frame(choices)
    tag_options = [
        (
            None,
            t(
                "planning.select_dict_tag_placeholder",
                default="-- Select from Tag Dictionary (Optional) --",
            ),
        )
    ] + [(int(r["id"]), str(r["tag"])) for _, r in df_tags.iterrows()]
    selected_tag_tuple = st.selectbox(
        t("planning.select_dict_tag", default="Dictionary Tag"),
        options=tag_options,
        format_func=lambda x: x[1],
        key="sb_attach_task_tag",
    )
    selected_tag_id = selected_tag_tuple[0] if selected_tag_tuple else None
    free_tag_input = st.text_input(
        t("planning.free_tag_optional", default="Custom / Free Tag (Optional)"),
        placeholder="e.g. Critical-Path, Security-Review",
        key="ti_attach_task_free_tag",
    )
    col_btn_save, col_btn_close = st.columns([3, 1])
    with col_btn_save:
        if st.button(
            t("planning.btn_attach_tag", default="Attach Tag"),
            type="primary",
            key="btn_confirm_attach_task_tag",
        ):
            if selected_tag_id is None and (not free_tag_input.strip()):
                st.error(
                    t(
                        "planning.tag_required_error",
                        default="Please select a dictionary tag or enter a custom tag.",
                    )
                )
            else:
                values = dict(tag_id=selected_tag_id, free_tag=free_tag_input.strip() or None)
                if plan:
                    save_task_tag(alternative_event, workspace, values)
                else:
                    workspace.tags.create_task_tag(TaskTag(task_id=task_id, **values))
                st.toast(
                    t("planning.toast_task_tag_attached", default="Tag attached to task!"),
                    icon="🏷️",
                )
                st.rerun()
    with col_btn_close:
        if st.button(t("planning.btn_close_dialog", default="Close"), key="btn_close_task_dialog"):
            st.session_state["modal_manage_task_tag"] = None
            st.rerun()


@authorized_cache(show_spinner=False, max_entries=64, ttl=300)
def _project_pool_dialog_data(_workspace: PlanningWorkspace, revision: tuple, project_id: int,
                              plan: ProjectPlan | None = None) -> tuple:
    """Load popup references once and calculate only assigned or undefined pools."""
    pools = pools_frame(_workspace.resources.pool_choices())
    if plan is not None:
        from app.presentation.pages.planning_scenario_assignments import assignment_rows

        bounds, rows = assignment_rows(plan, None, {row['id']: row['name'] for row in pools.to_dict('records')})
        assignments = assignments_frame(rows)
    else:
        bounds = _workspace.planning.get_all_project_date_bounds().get(project_id, (None, None))
        assignments = assignments_frame(_workspace.resources.get_assignments(project_id=project_id, only_project_level=True))
    assigned_ids = sorted(set(assignments['pool_id'].astype(int))) if not assignments.empty else []
    statuses = {detail.pool_id: project_pool_status(project_id, detail)
                for detail in _workspace.pool_details(assigned_ids)} if assigned_ids else {}
    missing_capacity = [int(row['id']) for row in pools.to_dict('records') if pd.isna(row['capacity_fte'])]
    summaries = {row.pool_id: row.total_capacity_fte for row in _workspace.capacity.get_summaries(missing_capacity)} if missing_capacity else {}
    choices = [(int(row['id']), f"🏊 {row['name']} (Cap: {summaries[int(row['id'])] if pd.isna(row['capacity_fte']) else float(row['capacity_fte']):.2f} FTE)")
               for row in pools.to_dict('records')]
    return bounds, assignments, statuses, choices


def _relative_assignment_controls(key: str, start: str | None, end: str | None) -> tuple[str, int, int]:
    """Collect a relative schedule and preview its current inclusive dates."""
    from app.domain.resources.scheduling import relative_period

    anchor = st.selectbox(
        t("master_data.schedule_anchor", default="Schedule from"), ["start", "end"],
        format_func=lambda value: t(f"master_data.schedule_{value}"), key=f"{key}_anchor",
    )
    offset_col, duration_col = st.columns(2)
    with offset_col:
        offset = st.number_input(t("master_data.offset_days", default="Offset (calendar days)"),
                                 min_value=-9124, max_value=9124, value=0, step=1, key=f"{key}_offset")
    with duration_col:
        duration = st.number_input(t("master_data.duration_days", default="Duration (calendar days)"),
                                   min_value=1, max_value=9125, value=5, step=1, key=f"{key}_duration")
    st.caption(t("master_data.relative_schedule_help"))
    if (start if anchor == "start" else end):
        try:
            first, last = relative_period(start or end, end or start, anchor, offset, duration)
            st.caption(f"{first} → {last}")
        except (ValueError, OverflowError):
            st.error(t("master_data.relative_date_error", default="The relative period is outside the supported date range."))
    return anchor, offset, duration


@dialog(t("planning.dialog_project_pools_title", default="🏊 Manage Project Resource Pools"))
@planning_errors
def _manage_project_resource_pools_dialog(
    project_id: int, project_name: str, workspace: PlanningWorkspace, alternative_event: dict | None = None
) -> None:
    """Modal dialog for viewing, allocating, and unassigning resource pools at project level."""
    if not workspace.projects.projects.permissions().allows(Permission.EDIT, project_id):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    st.markdown(f"#### 📁 {project_name} `[Project #{project_id}]`")
    from app.presentation.pages.planning_alternative_editor import selected_plan
    from app.presentation.pages.planning_scenario_assignments import save_assignment

    plan = selected_plan(alternative_event, workspace) if alternative_event else None
    if plan:
        st.caption(f'{plan.name} · Capacity warnings reflect the active portfolio.')
    (p_start_str, p_end_str), df_current_assigns, statuses, pool_choices = _project_pool_dialog_data(workspace, workspace.revision(), project_id, plan)
    if p_start_str and p_end_str:
        st.caption(f"Project Timeline: {p_start_str} → {p_end_str}")
    st.markdown(f"##### {t('planning.current_pools', default='Current Assigned Resource Pools')}")
    if df_current_assigns.empty:
        st.info(
            t(
                "planning.no_pools_assigned_project",
                default="No resource pools currently assigned to this project.",
            )
        )
    else:
        for _, row in df_current_assigns.iterrows():
            assign_id = int(row["id"])
            p_id = int(row["pool_id"])
            p_name = str(row["pool_name"])
            fte_val = float(row["fte_assigned"])
            c_start = row.get("custom_start_date")
            c_end = row.get("custom_end_date")
            p_status = statuses[p_id]
            minimum_capacity = float(p_status["minimum_capacity_fte"])
            if p_status["is_overassigned"]:
                status_html = f"""<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">⚠️ Overassigned (Peak: {p_status['project_peak_assigned_fte']:.2f} / Min. effective cap: {minimum_capacity:.2f} FTE)</span>"""
            else:
                status_html = f"""<span style="background-color:#ECFDF5; color:#047857; border:1px solid #10B981; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">✅ OK (Peak: {p_status['project_peak_assigned_fte']:.2f} / Min. effective cap: {minimum_capacity:.2f} FTE)</span>"""
            if row.get("schedule_anchor") in {"start", "end"}:
                period_str = (f"{t('master_data.period_relative')}: "
                              f"{t('master_data.schedule_' + row['schedule_anchor'])} "
                              f"{int(row['offset_days']):+d} / {int(row['duration_days'])} "
                              f"{t('master_data.calendar_days')}: "
                              f"{row['effective_start_date']} → {row['effective_end_date']}")
            elif (
                pd.notna(c_start)
                and pd.notna(c_end)
                and str(c_start).strip()
                and str(c_end).strip()
            ):
                period_str = f"📅 {c_start} to {c_end} *(Custom Period)*"
            else:
                period_str = (
                    f"📅 Full Project Duration ({p_start_str or 'Start'} to {p_end_str or 'End'})"
                )
            c_info, c_del = st.columns([5, 1])
            with c_info:
                st.markdown(
                    f'<div style="background:#F8FAFC; border:1px solid #E2E8F0; border-left:4px solid #0284C7; padding:8px 10px; border-radius:6px; margin-bottom:6px;"><div style="display:flex; justify-content:space-between; align-items:center;"><b style="color:#0F172A; font-size:13px;">🏊 {p_name}</b><span style="font-weight:700; color:#0284C7; font-size:12px;">{fte_val:.2f} FTE</span></div><div style="font-size:11.5px; color:#475569; margin-top:3px;">{period_str}</div><div style="margin-top:4px;">{status_html}</div></div>',
                    unsafe_allow_html=True,
                )
            with c_del:
                if st.button(
                    "🗑️",
                    key=f"btn_del_assign_proj_{assign_id}",
                    help=t("planning.btn_unassign_pool", default="Remove pool assignment"),
                ):
                    save_assignment(alternative_event, workspace, delete_id=assign_id)
                    st.toast(
                        t(
                            "planning.toast_pool_unassigned_proj",
                            default="Project pool assignment removed!",
                        ),
                        icon="🗑️",
                    )
                    st.rerun()
    st.divider()
    st.markdown(f"##### ➕ {t('planning.assign_new_pool', default='Assign Resource Pool')}")
    if not pool_choices:
        st.warning(t('planning.no_pools_exist', default='No resource pools configured.'))
        return
    period_mode = st.radio(
        t("master_data.assignment_period_mode", default="Assignment Period Mode"),
        options=["full", "custom", "relative"],
        format_func=lambda m: (
            t("master_data.period_full_project", default="Full Project Duration (Default)")
            if m == "full"
            else t("master_data.period_custom_range", default="Custom Specific Period")
            if m == "custom" else t("master_data.period_relative", default="Offset + duration")
        ),
        key="rb_assign_proj_period_mode",
        horizontal=True,
    )
    anchor, offset, duration = (None, None, None)
    if period_mode == "relative":
        anchor, offset, duration = _relative_assignment_controls("assign_proj", p_start_str, p_end_str)
    with st.form("assign_proj_pool_form", border=False):
        sel_pool_tuple = st.selectbox(
            t("planning.select_resource_pool", default="Select Resource Pool *"),
            options=pool_choices,
            format_func=lambda x: x[1],
            key="sb_assign_proj_pool",
        )
        sel_pool_id = sel_pool_tuple[0] if sel_pool_tuple else None
        c_fte = st.container()
        with c_fte:
            fte_input = st.number_input(
                t("master_data.field_fte", default="Assigned FTE *"),
                min_value=0.1,
                max_value=100.0,
                value=1.0,
                step=0.1,
                key="ni_assign_proj_fte",
            )
        custom_start_str = None
        custom_end_str = None
        if period_mode == "custom":
            default_s = (
                datetime.datetime.strptime(p_start_str, "%Y-%m-%d").date()
                if p_start_str
                else datetime.date.today()
            )
            default_e = (
                datetime.datetime.strptime(p_end_str, "%Y-%m-%d").date()
                if p_end_str
                else default_s + datetime.timedelta(days=30)
            )
            col_s, col_e = st.columns(2)
            with col_s:
                custom_s_val = st.date_input(
                    t("master_data.custom_start_date", default="Start Date"),
                    value=default_s,
                    key="di_assign_proj_s",
                )
            with col_e:
                custom_e_val = st.date_input(
                    t("master_data.custom_end_date", default="End Date"),
                    value=default_e,
                    key="di_assign_proj_e",
                )
            if custom_s_val and custom_e_val:
                if custom_e_val < custom_s_val:
                    st.error(
                        t(
                            "master_data.date_range_error",
                            default="End Date cannot be before Start Date.",
                        )
                    )
                else:
                    custom_start_str = custom_s_val.strftime("%Y-%m-%d")
                    custom_end_str = custom_e_val.strftime("%Y-%m-%d")
        notes_input = st.text_input(
            t("master_data.field_assignment_notes", default="Notes / Allocation Purpose"),
            placeholder="e.g. Core architectural oversight, PMO support",
            key="ti_assign_proj_notes",
        )
        col_btn_save = st.container()
        with col_btn_save:
            if st.form_submit_button(
                t("planning.btn_confirm_assign_pool_proj", default="Assign Pool to Project"),
                type="primary",
                key="btn_confirm_assign_proj_pool",
            ):
                if sel_pool_id is None:
                    st.error(
                        t("planning.pool_required_error", default="Please select a resource pool.")
                    )
                elif period_mode == "custom" and (not custom_start_str or not custom_end_str):
                    st.error(
                        t(
                            "master_data.date_range_error",
                            default="End Date cannot be before Start Date.",
                        )
                    )
                else:
                    new_assignment = PoolAssignment(
                        pool_id=sel_pool_id,
                        project_id=project_id,
                        task_id=None,
                        fte_assigned=float(fte_input),
                        start_date=custom_start_str,
                        end_date=custom_end_str,
                        notes=notes_input.strip(),
                        schedule_anchor=anchor, offset_days=offset, duration_days=duration,
                    )
                    save_assignment(alternative_event, workspace, new_assignment)
                    st.toast(
                        t(
                            "planning.toast_pool_assigned_proj",
                            default="Resource pool assigned to project!",
                        ),
                        icon="🏊",
                    )
                    st.session_state["modal_manage_project_pool"] = None
                    st.rerun()
    with st.container():
        if st.button(
            t("planning.btn_close_dialog", default="Close"), key="btn_close_proj_pool_dialog"
        ):
            st.session_state["modal_manage_project_pool"] = None
            st.rerun()


@dialog(t("planning.dialog_task_pools_title", default="🏊 Manage Task Resource Pools"))
@planning_errors
def _manage_task_resource_pools_dialog(
    task_id: int, task_name: str, project_id: int | str, workspace: PlanningWorkspace,
    alternative_event: dict | None = None,
) -> None:
    """Manage task assignments using cached summaries, not full pool timelines."""
    from app.presentation.pages.planning_alternative_editor import selected_plan
    from app.presentation.pages.planning_scenario_assignments import assignment_rows, save_assignment

    plan = selected_plan(alternative_event, workspace) if alternative_event else None
    step_info = (dict(next(row for row in plan.content.tasks if row['id'] == task_id), project_id=plan.project_id)
                 if plan else workspace.planning.get_milestone_by_id(task_id))
    if step_info is None or not workspace.projects.projects.permissions().allows(Permission.EDIT, step_info["project_id"]):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    project_id, task_name = step_info["project_id"], step_info["task_name"]
    st.markdown(f"#### 📋 {task_name} `[Task #{task_id}]` (Project #{project_id})")
    if plan:
        st.caption(f'{plan.name} · Capacity warnings reflect the active portfolio.')
    task_start_str = step_info.get("start_date") if step_info else None
    task_end_str = step_info.get("end_date") if step_info else None
    if task_start_str and task_end_str:
        st.caption(f"📅 **Task Schedule:** `{task_start_str}` ➔ `{task_end_str}`")
    df_all_pools = pools_frame(workspace.resources.pool_choices())
    pool_rows = df_all_pools.to_dict("records")
    records = (assignment_rows(plan, task_id, {row['id']: row['name'] for row in pool_rows})[1]
               if plan else workspace.resources.get_assignments(task_id=task_id))
    df_current_assigns = assignments_frame(records)
    summary_ids = set(df_current_assigns["pool_id"].astype(int))
    summary_ids.update((int(row["id"]) for row in pool_rows if pd.isna(row["capacity_fte"])))
    summaries = (
        {
            summary.pool_id: summary
            for summary in workspace.capacity.get_summaries(list(summary_ids))
        }
        if summary_ids
        else {}
    )
    st.markdown(f"##### {t('planning.current_pools', default='Current Assigned Resource Pools')}")
    if df_current_assigns.empty:
        st.info(
            t(
                "planning.no_pools_assigned_task",
                default="No resource pools currently assigned to this task.",
            )
        )
    else:
        for row in df_current_assigns.to_dict("records"):
            assign_id = int(row["id"])
            p_id = int(row["pool_id"])
            p_name = str(row["pool_name"])
            fte_val = float(row["fte_assigned"])
            c_start = row.get("custom_start_date")
            c_end = row.get("custom_end_date")
            cap_detail = summaries[p_id]
            if cap_detail.is_overassigned:
                status_html = f'<span style="background-color:#FDE8EC; color:#C41039; border:1px solid #C41039; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">⚠️ Overassigned (Peak: {cap_detail.peak_assigned_fte:.2f} / Cap: {cap_detail.total_capacity_fte:.2f} FTE)</span>'
            else:
                status_html = f'<span style="background-color:#ECFDF5; color:#047857; border:1px solid #10B981; padding:2px 7px; border-radius:10px; font-weight:700; font-size:11px;">✅ OK (Peak: {cap_detail.peak_assigned_fte:.2f} / Cap: {cap_detail.total_capacity_fte:.2f} FTE)</span>'
            if row.get("schedule_anchor") in {"start", "end"}:
                period_str = (f"{t('master_data.period_relative')}: "
                              f"{t('master_data.schedule_' + row['schedule_anchor'])} "
                              f"{int(row['offset_days']):+d} / {int(row['duration_days'])} "
                              f"{t('master_data.calendar_days')}: "
                              f"{row['effective_start_date']} → {row['effective_end_date']}")
            elif (
                pd.notna(c_start)
                and pd.notna(c_end)
                and str(c_start).strip()
                and str(c_end).strip()
            ):
                period_str = f"📅 {c_start} to {c_end} *(Custom Period)*"
            else:
                period_str = f"📅 Full Task Duration ({task_start_str or 'Start'} to {task_end_str or 'End'})"
            c_info, c_del = st.columns([5, 1])
            with c_info:
                st.markdown(
                    f'<div style="background:#F8FAFC; border:1px solid #E2E8F0; border-left:4px solid #0284C7; padding:8px 10px; border-radius:6px; margin-bottom:6px;"><div style="display:flex; justify-content:space-between; align-items:center;"><b style="color:#0F172A; font-size:13px;">🏊 {p_name}</b><span style="font-weight:700; color:#0284C7; font-size:12px;">{fte_val:.2f} FTE</span></div><div style="font-size:11.5px; color:#475569; margin-top:3px;">{period_str}</div><div style="margin-top:4px;">{status_html}</div></div>',
                    unsafe_allow_html=True,
                )
            with c_del:
                if st.button(
                    "🗑️",
                    key=f"btn_del_assign_task_{assign_id}",
                    help=t("planning.btn_unassign_pool", default="Remove pool assignment"),
                ):
                    save_assignment(alternative_event, workspace, delete_id=assign_id)
                    st.toast(
                        t("planning.toast_pool_unassigned", default="Pool assignment removed!"),
                        icon="🗑️",
                    )
                    st.rerun()
    st.divider()
    st.markdown(f"##### ➕ {t('planning.assign_new_pool', default='Assign Resource Pool')}")
    if df_all_pools.empty:
        st.warning(
            t(
                "planning.no_pools_exist",
                default="No resource pools configured. Create pools in Settings > Resource Pools.",
            )
        )
        return
    pool_choices = []
    for pr in pool_rows:
        pid = int(pr["id"])
        capacity = (
            summaries[pid].total_capacity_fte
            if pd.isna(pr["capacity_fte"])
            else float(pr["capacity_fte"])
        )
        pool_choices.append((pid, f"🏊 {pr['name']} (Cap: {capacity:.2f} FTE)"))
    period_mode = st.radio(
        t("master_data.assignment_period_mode", default="Assignment Period Mode"),
        options=["full", "custom", "relative"],
        format_func=lambda m: (
            t("master_data.period_full_task", default="Full Task Duration (Default)")
            if m == "full"
            else t("master_data.period_custom_range", default="Custom Specific Period")
            if m == "custom" else t("master_data.period_relative", default="Offset + duration")
        ),
        key="rb_assign_task_period_mode",
        horizontal=True,
    )
    anchor, offset, duration = (None, None, None)
    if period_mode == "relative":
        anchor, offset, duration = _relative_assignment_controls("assign_task", task_start_str, task_end_str)
    with st.form("assign_task_pool_form", border=False):
        sel_pool_tuple = st.selectbox(
            t("planning.select_resource_pool", default="Select Resource Pool *"),
            options=pool_choices,
            format_func=lambda x: x[1],
            key="sb_assign_task_pool",
        )
        sel_pool_id = sel_pool_tuple[0] if sel_pool_tuple else None
        c_fte = st.container()
        with c_fte:
            fte_input = st.number_input(
                t("master_data.field_fte", default="Assigned FTE *"),
                min_value=0.1,
                max_value=100.0,
                value=1.0,
                step=0.1,
                key="ni_assign_task_fte",
            )
        custom_start_str = None
        custom_end_str = None
        if period_mode == "custom":
            default_s = (
                datetime.datetime.strptime(task_start_str, "%Y-%m-%d").date()
                if task_start_str
                else datetime.date.today()
            )
            default_e = (
                datetime.datetime.strptime(task_end_str, "%Y-%m-%d").date()
                if task_end_str
                else default_s + datetime.timedelta(days=14)
            )
            col_s, col_e = st.columns(2)
            with col_s:
                custom_s_val = st.date_input(
                    t("master_data.custom_start_date", default="Start Date"),
                    value=default_s,
                    key="di_assign_task_s",
                )
            with col_e:
                custom_e_val = st.date_input(
                    t("master_data.custom_end_date", default="End Date"),
                    value=default_e,
                    key="di_assign_task_e",
                )
            if custom_s_val and custom_e_val:
                if custom_e_val < custom_s_val:
                    st.error(
                        t(
                            "master_data.date_range_error",
                            default="End Date cannot be before Start Date.",
                        )
                    )
                else:
                    custom_start_str = custom_s_val.strftime("%Y-%m-%d")
                    custom_end_str = custom_e_val.strftime("%Y-%m-%d")
        notes_input = st.text_input(
            t("master_data.field_assignment_notes", default="Notes / Allocation Purpose"),
            placeholder="e.g. Lead drafting, Structural analysis",
            key="ti_assign_task_notes",
        )
        col_btn_save = st.container()
        with col_btn_save:
            if st.form_submit_button(
                t("planning.btn_confirm_assign_pool", default="Assign Pool to Task"),
                type="primary",
                key="btn_confirm_assign_task_pool",
            ):
                if sel_pool_id is None:
                    st.error(
                        t("planning.pool_required_error", default="Please select a resource pool.")
                    )
                elif period_mode == "custom" and (not custom_start_str or not custom_end_str):
                    st.error(
                        t(
                            "master_data.date_range_error",
                            default="End Date cannot be before Start Date.",
                        )
                    )
                else:
                    parsed_proj_id = int(project_id) if str(project_id).isdigit() else None
                    new_assignment = PoolAssignment(
                        pool_id=sel_pool_id,
                        project_id=parsed_proj_id,
                        task_id=task_id,
                        fte_assigned=float(fte_input),
                        start_date=custom_start_str,
                        end_date=custom_end_str,
                        notes=notes_input.strip(),
                        schedule_anchor=anchor, offset_days=offset, duration_days=duration,
                    )
                    save_assignment(alternative_event, workspace, new_assignment)
                    st.toast(
                        t("planning.toast_pool_assigned", default="Resource pool assigned to task!"),
                        icon="🏊",
                    )
                    st.session_state["modal_manage_task_pool"] = None
                    st.rerun()
    with st.container():
        if st.button(
            t("planning.btn_close_dialog", default="Close"), key="btn_close_task_pool_dialog"
        ):
            st.session_state["modal_manage_task_pool"] = None
            st.rerun()


def _handle_filter_by_resource_pool(
    gantt_event: dict[str, Any],
    pool_details_cache: dict[int, Any],
    workspace: PlanningWorkspace,
    selected_projects: list[Any],
    all_proj_ids: list[int],
    master_proj_ids: list[int] | None = None,
) -> None:
    """Handles resource pool context menu filter event.

    Queues session state modifications via pending state keys to avoid StreamlitAPIException
    from modifying widget state after widget instantiation."""
    pool_id = int(gantt_event.get("pool_id") or 0)
    group_id = gantt_event.get("group_id")
    start_date = str(gantt_event.get("start_date", "")).strip()[:10] or "0001-01-01"
    end_date = str(gantt_event.get("end_date", "")).strip()[:10] or "9999-12-31"
    clear_other = bool(gantt_event.get("clear_other_filters", True))
    pool_name = str(gantt_event.get("pool_name", ""))
    pool_ids = workspace.resources.group_pool_ids(int(group_id)) if group_id else [pool_id]
    eligible = set(st.session_state.get("planning_status_project_ids", master_proj_ids or all_proj_ids))
    if gantt_event.get("allocation_scope") == "selected":
        eligible.intersection_update(int(value) for value in selected_projects)
    details = workspace.pool_details(pool_ids, project_ids=eligible) if pool_ids else []
    matching_pids = sorted({pid for detail in details for pid in
        get_projects_consuming_pool_in_period(detail.assignments, start_date, end_date)})
    scope = str(gantt_event.get("filter_scope", "this"))
    if matching_pids and scope != "this":
        matching_pids = workspace.planning.related_project_ids(matching_pids, scope)
    ref_proj_ids = master_proj_ids if clear_other and master_proj_ids else all_proj_ids
    if clear_other:
        target_pids = matching_pids
    else:
        current_pids = [int(p) for p in selected_projects if str(p).isdigit()]
        intersected = [p for p in current_pids if p in matching_pids]
        target_pids = intersected if intersected else matching_pids
    valid_target_pids = [p for p in target_pids if p in ref_proj_ids and p in eligible]
    st.session_state["active_resource_pool_filter"] = {
        "pool_id": pool_id,
        "group_id": group_id,
        "pool_ids": pool_ids,
        "pool_name": pool_name or (details[0].pool_name if details else "Resource group"),
        "start_date": start_date,
        "end_date": end_date,
        "clear_other_filters": clear_other,
        "project_ids": valid_target_pids,
        "count": len(valid_target_pids),
    }
    st.session_state["pending_resource_pool_filter"] = {
        "clear_other": clear_other,
        "target_pids": valid_target_pids,
    }
    if valid_target_pids:
        st.toast(f"Filtered to {len(valid_target_pids)} projects consuming {pool_name}", icon="🔍")
    else:
        st.toast(f"No projects consuming {pool_name} in {start_date} → {end_date}", icon="⚠️")
    st.rerun()


def _handle_clear_resource_pool_filter(all_proj_ids: list[int] | None = None) -> None:
    """Clears the active resource pool filter and resets project selection."""
    st.session_state.pop("active_resource_pool_filter", None)
    st.session_state["pending_clear_resource_pool_filter"] = True
    st.toast("Resource pool filter cleared", icon="✖")
    st.rerun()


def _render_filtered_active_allocations(
    active_rf: dict[str, Any], pool_details_cache: dict[int, Any], workspace: PlanningWorkspace
) -> None:
    """Renders the Active Allocations on Projects & Tasks table below the resource pools table.

    Displays active allocations overlapping the filtered period, differentiating
    project-level and task-level assignments, without the action column."""
    f_pool_id = int(active_rf.get("pool_id", 0))
    f_pool_name = str(active_rf.get("pool_name", "Pool"))
    f_start = str(active_rf.get("start_date", ""))[:10]
    f_end = str(active_rf.get("end_date", ""))[:10]
    pool_ids = active_rf.get("pool_ids", [f_pool_id])
    details = workspace.pool_details(pool_ids, project_ids=set(active_rf.get("project_ids", []))) if pool_ids else []
    pool_active_assignments: list[dict[str, Any]] = []
    for a in [dict(assignment, pool_name=detail.pool_name) for detail in details for assignment in detail.assignments]:
        a_start = str(a.get("start_date", ""))[:10]
        a_end = str(a.get("end_date", ""))[:10]
        fte_val = float(a.get("fte_assigned", 0.0))
        if fte_val > 0 and a_start <= f_end and (a_end >= f_start):
            pool_active_assignments.append(a)
    st.markdown("---")
    st.write(
        f"#### 📁 / 📋 {t('settings.assignments_section_title', default='Active Allocations on Projects & Tasks')} — <span style='color:#2563EB;'>{html.escape(f_pool_name)}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Showing active resource assignments overlapping `{f_start} → {f_end}`. Project-level allocations apply across the whole project, whereas task-level allocations apply to specific steps."
    )
    if not pool_active_assignments:
        st.info(f"No active allocations found for {f_pool_name} in `{f_start} → {f_end}`.")
        return
    table_rows: list[str] = []
    total_active_fte = 0.0
    for a in pool_active_assignments:
        p_id = a["project_id"]
        p_name = html.escape(str(a.get("project_name", f"Project #{p_id}")))
        t_id = a.get("task_id")
        t_name = html.escape(str(a.get("task_name", "—")))
        fte = float(a.get("fte_assigned", 0.0))
        total_active_fte += fte
        s_date = a.get("start_date", "")
        e_date = a.get("end_date", "")
        is_custom = bool(a.get("is_custom_period", False))
        period_label = (t("master_data.period_relative") if a.get("schedule_anchor")
                        else "Custom" if is_custom else "Full Task" if t_id else "Full Project")
        notes = html.escape(str(a.get("notes", "")))
        pool_badge_name = html.escape(str(a.get("pool_name", f_pool_name)))
        proj_badge = f'<span style="color:#0369A1; font-weight:700;">📁 {p_name} [#{p_id}]</span>'
        if t_id:
            task_badge = (
                f'<span style="color:#2563EB; font-weight:600;">📋 {t_name} [#{t_id}]</span>'
            )
        else:
            task_badge = f'<span style="color:#64748B; font-style:italic; background:#F1F5F9; padding:2px 7px; border-radius:3px; border:1px dashed #CBD5E1;">— Project Level</span>'
        period_badge = f"""<span style="font-size:12px; color:#334155;">{s_date} → {e_date}</span> <span style="font-size:10px; background:#E2E8F0; color:#475569; padding:1px 5px; border-radius:3px;">{html.escape(period_label)}</span>"""
        pool_badge = f'<span style="background:#EFF6FF; color:#1D4ED8; font-weight:600; padding:2px 8px; border-radius:4px; border:1px solid #BFDBFE;">🏊 {pool_badge_name}</span>'
        table_rows.append(
            f"""<tr style="border-bottom:1px solid #E2E8F0;"><td style="padding:8px 10px; font-weight:600; color:#475569;">#{a['id']}</td><td style="padding:8px 10px;">{pool_badge}</td><td style="padding:8px 10px;">{proj_badge}</td><td style="padding:8px 10px;">{task_badge}</td><td style="padding:8px 10px;"><span style="font-weight:700; color:#0F172A; background:#F1F5F9; padding:2px 7px; border-radius:4px;">{fte:.2f} FTE</span></td><td style="padding:8px 10px;">{period_badge}</td><td style="padding:8px 10px; color:#64748B; font-size:12px;">{notes or '—'}</td></tr>"""
        )
    header_html = f"""<tr style="background:#F8FAFC; border-bottom:2px solid #CBD5E1; color:#475569; font-weight:700; font-size:12px; text-transform:uppercase;"><th style="padding:8px 10px; text-align:left;">ID</th><th style="padding:8px 10px; text-align:left;">{t('settings.col_pool', default='Resource Pool')}</th><th style="padding:8px 10px; text-align:left;">{t('settings.col_project', default='Project')}</th><th style="padding:8px 10px; text-align:left;">{t('settings.col_task', default='Task / Step')}</th><th style="padding:8px 10px; text-align:left;">{t('master_data.field_fte', default='Assigned FTE')}</th><th style="padding:8px 10px; text-align:left;">{t('master_data.field_period', default='Effective Period')}</th><th style="padding:8px 10px; text-align:left;">{t('master_data.field_notes', default='Notes')}</th></tr>"""
    footer_html = f'<tr style="background:#F1F5F9; font-weight:700; border-top:2px solid #CBD5E1; color:#0F172A;"><td colspan="4" style="padding:8px 10px; text-align:right;">Total Active Allocation:</td><td style="padding:8px 10px;"><span style="background:#2563EB; color:#FFFFFF; padding:2px 8px; border-radius:4px; font-weight:700;">{total_active_fte:.2f} FTE</span></td><td colspan="2" style="padding:8px 10px; color:#64748B; font-size:11.5px; font-weight:400;">Filtered Period: {f_start} → {f_end}</td></tr>'
    full_table_html = f"""<div style="overflow-x:auto; border:1px solid #E2E8F0; border-radius:6px; margin-bottom:12px;"><table style="width:100%; border-collapse:collapse; font-size:12.5px; text-align:left; background:#FFFFFF;"><thead>{header_html}</thead><tbody>{''.join(table_rows)}</tbody><tfoot>{footer_html}</tfoot></table></div>"""
    st.markdown(full_table_html, unsafe_allow_html=True)


@authorized_cache(ttl=60, max_entries=8, show_spinner=False, hash_funcs={tuple: repr})
def _load_planning_pool_payload(
    _workspace: PlanningWorkspace,
    revision: tuple,
    project_ids: tuple[int, ...],
    _pool_details_cache: dict[int, PoolCapacityDetail],
    pool_ids: tuple[int, ...] | None = None,
    status_project_ids: tuple[int, ...] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reuse exact selected-scope daily demand until source data or scope changes."""
    workspace = _workspace
    selected_projects = project_ids
    pool_details_cache = _pool_details_cache
    scope_pids = [int(p) for p in selected_projects if str(p).isdigit()]
    scope_pid_set = set(scope_pids)
    df_all_pools = pools_frame(workspace.resources.pool_choices())
    if pool_ids is not None:
        df_all_pools = df_all_pools[df_all_pools.id.isin(pool_ids)]
    # A fragment can retain a dictionary from an older scope. Refresh it through
    # the actor-bound capacity cache before using any allocation records.
    pool_details_cache.clear()
    pool_details_cache.update({detail.pool_id: detail for detail in workspace.pool_details(
        [int(value) for value in df_all_pools.id],
        project_ids=set(status_project_ids) if status_project_ids is not None else None
    )})
    resource_pools_payload: list[dict[str, Any]] = []
    if not df_all_pools.empty:
        for _, p_row in df_all_pools.iterrows():
            p_id = int(p_row["id"])
            p_name = str(p_row["name"])
            p_cap = pool_details_cache[p_id]
            effective_daily_capacity = (
                p_cap.capacity_calendar
            )
            if all((int(a["project_id"]) in scope_pid_set for a in p_cap.assignments)):
                scope_usage = p_cap.daily_usage
                scope_overassignments = p_cap.daily_overassignments
            else:
                scope_usage = calculate_pool_scope_daily_usage(p_cap.assignments, scope_pids)
                scope_overassignments = calculate_daily_overassignments(
                    scope_usage, p_cap.effective_capacity_fte, effective_daily_capacity
                )
            resource_pools_payload.append(
                {
                    "id": p_id,
                    "name": p_name,
                    "capacity": float(p_cap.total_capacity_fte),
                    "theoretical_capacity": (
                        float(p_cap.defined_capacity_fte)
                        if p_cap.defined_capacity_fte is not None
                        else float(p_cap.total_capacity_fte)
                    ),
                    "assigned_capacity": float(p_cap.assigned_capacity_fte),
                    "displayed_assigned_capacity": float(p_cap.effective_capacity_fte),
                    "has_assigned_resources": bool(p_cap.has_assigned_resources),
                    "used_by_selected_projects": any(
                        (
                            int(a["project_id"]) in scope_pid_set and float(a["fte_assigned"]) > 0
                            for a in p_cap.assignments
                        )
                    ),
                    "daily_assigned_capacity": effective_daily_capacity,
                    "peak_demand": float(p_cap.peak_assigned_fte),
                    "is_overassigned": bool(p_cap.is_overassigned),
                    "daily_usage": p_cap.daily_usage,
                    "overallocated_dates": [item.date for item in p_cap.daily_overassignments],
                    "selected_projects_daily_usage": scope_usage,
                    "selected_projects_overallocated_dates": [
                        item.date for item in scope_overassignments
                    ],
                    "assignments": [
                        {
                            "project_id": int(a["project_id"]),
                            "start_date": str(a.get("start_date", "")),
                            "end_date": str(a.get("end_date", "")),
                        }
                        for a in p_cap.assignments
                    ],
                }
            )
    resource_pool_hierarchy = (
        []
        if pool_ids is not None
        else _build_resource_pool_hierarchy(workspace, resource_pools_payload)
    )
    return (resource_pools_payload, resource_pool_hierarchy)


@st.fragment
@planning_errors
def _render_planning_chart(
    workspace: PlanningWorkspace,
    selected_projects: list[int],
    df_projects: pd.DataFrame,
    proj_map: dict[int, str],
    master_proj_ids: list[int],
    scope_signature: tuple,
) -> None:
    from uuid import uuid4

    feedback = st.empty()
    if error := st.session_state.pop("planning_step_form_error", None):
        feedback.error(error)
    selected_id = selected_projects[0]
    all_proj_ids = df_projects.id.tolist()
    ids = tuple(sorted(map(int, selected_projects)))
    status_project_ids = tuple(st.session_state.get("planning_status_project_ids", master_proj_ids))
    scope = (ids, status_project_ids, get_current_locale(), repr(scope_signature))
    widget_key = "planning_lazy_gantt"
    snapshot = st.session_state.get("planning_chart_snapshot")
    event = st.session_state.pop("planning_pending_change", None)
    # HTTP task reads update only the browser. Carry its bounded working set into
    # subsequent edit events so edited/dependent loaded rows receive their patches.
    component_event = st.session_state.get(widget_key)
    if snapshot and isinstance(component_event, dict) and component_event.get("scope_token") == snapshot["token"]:
        loaded = component_event.get("loaded_project_ids")
        if isinstance(loaded, list):
            snapshot["loaded"] = list(dict.fromkeys(pid for pid in loaded[-100:] if type(pid) is int and pid in ids))
    sources = workspace.sources.capture(list(ids))
    revision = sources.revision
    unchanged_scope = snapshot is not None and snapshot["scope"] == scope and 'task_source_tokens' in snapshot
    known_edit = (
        event
        and event.get("before_revision")
        and unchanged_scope
        and (event["before_revision"] == snapshot["revision"])
    )
    rebuild = not unchanged_scope or (revision != snapshot["revision"] and (not known_edit))
    if rebuild:
        details: dict[int, PoolCapacityDetail] = {}
        summaries = load_project_summaries(workspace, revision, ids)
        pools, hierarchy = _load_planning_pool_payload(workspace, revision, ids, details, status_project_ids=status_project_ids)
        # A cache miss fills current details while building the pool payload.
        # A cache hit skips that function body, so read current details once here.
        if pools and not details:
            details = {d.pool_id: d for d in workspace.pool_details(project_ids=set(status_project_ids))}
        bounds = {str(p["id"]): (p["start"], p["end"]) for p in summaries}
        loaded = list(ids) if len(ids) == 1 else []
        tasks = build_task_payload(workspace, loaded, bounds, details) if loaded else []
        snapshot = {
            "scope": scope,
            "token": uuid4().hex,
            "details": details,
            "bounds": bounds,
            "loaded": loaded,
            "revision": revision,
            "task_source_tokens": sources.tokens,
        }
        st.session_state["planning_chart_snapshot"] = snapshot
        args = dict(
            tasks=tasks,
            project_summaries=summaries,
            lazy_projects=True,
            loaded_project_ids=loaded,
            scope_token=snapshot["token"],
            all_projects=[{"id": str(r.id), "name": r.name} for r in df_projects.itertuples()],
            external_tasks={},
            project_id=selected_id,
            is_multi_project=True,
            translations=get_section_catalog("gantt", get_current_locale()),
            resource_pools=pack_pool_payloads(pools),
            resource_pool_hierarchy=hierarchy,
            active_resource_filter=st.session_state.get("active_resource_pool_filter"),
            data_revision=snapshot["token"],
            task_endpoint="/api/planning/tasks",
            task_revision=planning_revision_token(snapshot["revision"]),
            task_source_tokens=snapshot["task_source_tokens"],
            view_scope=planning_revision_token(scope),
        )
    else:
        args = {}
        patch = None
        if (
            event
            and event.get("action") == "load_project_tasks"
            and (event.get("scope_token") == snapshot["token"])
        ):
            requested = []
            for value in event.get("project_ids", [])[:25]:
                try:
                    pid = int(value)
                except (ValueError, TypeError):
                    continue
                if pid in ids and pid not in requested:
                    requested.append(pid)
            patch = {
                "replace_projects": requested,
                "tasks": build_task_payload(
                    workspace, requested, snapshot["bounds"], snapshot["details"]
                ),
            }
            loaded = [p for p in snapshot["loaded"] if p not in requested] + requested
            evicted, snapshot["loaded"] = (loaded[:-100], loaded[-100:])
            patch["evict_project_ids"] = evicted
        elif known_edit:
            changed, pool_ids = affected_task_projects(workspace, int(event["id"]))
            for pid in changed:
                snapshot["bounds"][pid] = snapshot["bounds"][str(pid)] = (
                    workspace.planning.get_project_date_bounds(pid)
                )
            if event["action"] == "update_progress":
                pool_ids = set()
            if pool_ids:
                snapshot["details"].update(
                    {d.pool_id: d for d in workspace.pool_details(list(pool_ids), project_ids=set(status_project_ids))}
                )
            refresh = changed.intersection(snapshot["loaded"])
            if event["action"] == "create_step_full":
                created_project = int(event["project_id"])
                if created_project in ids:
                    refresh.add(created_project)
                    snapshot["loaded"] = list(dict.fromkeys([*snapshot["loaded"], created_project]))
            patch = {
                "replace_projects": sorted(refresh),
                "tasks": build_task_payload(
                    workspace, refresh, snapshot["bounds"], snapshot["details"]
                ),
                "project_summaries": load_project_summaries(
                    workspace, workspace.revision(), tuple(sorted(changed.intersection(ids)))
                ),
            }
            if event["action"] == "create_step_full":
                patch["focus_project_id"] = int(event["project_id"])
            if pool_ids:
                patch["resource_pools"], _ = _load_planning_pool_payload(
                    workspace,
                    workspace.revision(),
                    ids,
                    snapshot["details"],
                    tuple(sorted(pool_ids)),
                    status_project_ids=status_project_ids,
                )
                patch["resource_pools"] = pack_pool_payloads(patch["resource_pools"])
            snapshot["revision"] = revision
            token_patch = {pid: sources.tokens[pid] for pid in changed.intersection(ids)}
            snapshot["task_source_tokens"].update(token_patch)
            args['task_source_token_patch'] = token_patch
        if patch is not None:
            metadata_ids = patch["replace_projects"]
            tags, pools = load_planning_project_metadata(
                workspace, workspace.revision(), tuple(metadata_ids)
            )
            patch["project_metadata"] = [
                {"id": str(pid), "tags": tags.get(pid, []), "pools": pools.get(pid, [])}
                for pid in metadata_ids
            ]
            patch.update(
                scope_token=snapshot["token"],
                nonce=event.get("nonce"),
                loaded_project_ids=snapshot["loaded"],
            )
            args["patch"] = patch
    response = st.session_state.pop("planning_dependency_response", None)
    if response:
        args["dependency_response"] = response
    project_response = st.session_state.pop('planning_project_dependency_response', None)
    if project_response:
        args['project_dependency_response'] = project_response
    pool_details_cache = snapshot["details"]
    permissions = workspace.projects.projects.permissions()
    args["task_revision"] = planning_revision_token(snapshot["revision"])
    args.update(scenario_payload(workspace, list(ids)))
    show_baseline = bool(st.session_state.get('planning_show_baseline', False))
    args['show_baseline'] = show_baseline
    args['baseline_tasks'] = workspace.plans.baseline_tasks(list(ids)) if show_baseline and workspace.plans else {}
    gantt_event = _interactive_gantt(
        **args,
        permissions={"edit_all": permissions.allows(Permission.EDIT),
                     "baseline_projects": workspace.plans.baseline_projects() if workspace.plans is not None else [],
                     "editable_projects": sorted(permissions.project_permissions.get(Permission.EDIT, frozenset())),
                     "approvable_projects": sorted(permissions.project_permissions.get(Permission.APPROVE, frozenset())),
                     "baseline_all": permissions.allows(Permission.SHARED) or permissions.allows(Permission.APPROVE),
                     "manage_shared": permissions.allows(Permission.SHARED)},
        filter_reset=st.session_state.get("planning_filter_reset", 0),
        key=widget_key,
        on_change=lambda: _handle_gantt_component_change(widget_key, workspace),
    )
    if gantt_event and isinstance(gantt_event, dict):
        nonce = _get_gantt_event_nonce(gantt_event)
        last_nonce = st.session_state.get("last_gantt_nonce")
        if nonce and nonce != last_nonce:
            st.session_state["last_gantt_nonce"] = nonce
            gantt_event = validate_event(gantt_event)
            action = gantt_event.get("action")
            step_id = gantt_event.get("id")
            if action in MUTATIONS:
                require_edit(alternative=action == 'manage_project_tags')
            if action in SCENARIO_ACTIONS:
                handle_scenario_event(gantt_event, workspace)
                st.rerun('planning_workspace')
            elif action == "filter_by_resource_pool":
                _handle_filter_by_resource_pool(
                    gantt_event=gantt_event,
                    pool_details_cache=pool_details_cache,
                    workspace=workspace,
                    selected_projects=selected_projects,
                    all_proj_ids=all_proj_ids,
                    master_proj_ids=master_proj_ids,
                )
            elif action == "clear_resource_pool_filter":
                _handle_clear_resource_pool_filter(master_proj_ids)
            elif action == "show_pool_allocations":
                _pool_allocations_dialog(int(gantt_event.get("pool_id") or 0), workspace,
                                         group_id=gantt_event.get("group_id"),
                                         start=gantt_event.get("start_date"), end=gantt_event.get("end_date"),
                                         project_ids=tuple(selected_projects) if gantt_event.get("allocation_scope") == "selected"
                                         else status_project_ids)
            elif action == "export_csv_template":
                from app.presentation.components.csv_download import download_project_csv

                project_id = int(gantt_event["project_id"])
                download_project_csv(project_id, nonce)
            elif action == "import_csv_template":
                _schedule_csv_dialog(workspace, int(gantt_event["project_id"]), action)
            elif action == "go_to_pool_details":
                pool_id = gantt_event.get("pool_id")
                if pool_id:
                    st.session_state["settings_active_section"] = "organization"
                    st.session_state["rb_settings_section"] = "org_structure"
                    st.session_state["settings_active_tab"] = "resource_pools"
                    st.session_state["target_resource_pool_id"] = int(pool_id)
                    st.session_state["nav_redirect"] = PAGE_SETTINGS
                    st.rerun()
            elif action == "manage_project_tags":
                p_id = gantt_event.get("project_id")
                if p_id:
                    st.session_state["modal_manage_project_tag"] = int(p_id)
                    st.rerun()
            elif action == "manage_project_pools":
                p_id = gantt_event.get("project_id")
                if p_id:
                    st.session_state["modal_manage_project_pool"] = int(p_id)
                    st.rerun()
            elif action == "log_project_event":
                if workspace.projects.open_event_dialog is not None:
                    workspace.projects.open_event_dialog(gantt_event["project_id"])
            elif action == "edit_project_details":
                p_id = gantt_event.get("project_id")
                if p_id:
                    st.session_state.pop("project_fields_editing", None)
                    st.session_state["modal_edit_project"] = int(p_id)
                    st.rerun()
            elif action == "filter_project":
                st.session_state["pending_project_context_filter"] = gantt_event
                st.rerun()
            elif action == "manage_task_tags" and step_id:
                st.session_state["modal_manage_task_tag"] = {
                    "task_id": int(step_id),
                    "task_name": str(gantt_event.get("task_name", "")),
                    "project_id": str(gantt_event.get("project_id", "")),
                }
                st.rerun()
            elif action == "manage_task_pools":
                t_id = gantt_event.get("task_id") or step_id
                if t_id:
                    st.session_state["modal_manage_task_pool"] = {
                        "task_id": int(t_id),
                        "task_name": str(gantt_event.get("task_name", "")),
                        "project_id": str(gantt_event.get("project_id", selected_id)),
                    }
                    st.rerun()
            elif action in {"update_task_full", "create_step_full"}:
                change = _apply_step_form(gantt_event, workspace, int(selected_id))
                if change:
                    st.session_state["planning_pending_change"] = change
                    st.rerun()
            elif action == "update_dates" and step_id:
                _apply_immediate_gantt_update(gantt_event, workspace)
            elif action == "update_progress" and step_id:
                _apply_immediate_gantt_update(gantt_event, workspace)
            elif action == "delete_step" and step_id:
                require_change(workspace.planning.delete_milestone(int(step_id)))
                st.toast(t("planning.toast_step_deleted", id=step_id), icon="🗑️")
                st.rerun()
    scenario_project = st.session_state.pop('planning_scenario_dialog_project', None)
    if scenario_project is not None:
        choose_alternative(scenario_project, workspace)
    create_project = st.session_state.pop('planning_create_scenario_project', None)
    if create_project is not None:
        create_alternative(create_project, workspace)
    alternative_event = st.session_state.pop('planning_alternative_editor', None)
    if alternative_event is not None:
        from app.presentation.pages.planning_alternative_editor import selected_plan

        if alternative_event['operation'] == 'manage_task_pools':
            _manage_task_resource_pools_dialog(alternative_event['id'], '', alternative_event['project_id'],
                                              workspace, alternative_event)
        elif alternative_event['operation'] == 'manage_project_pools':
            project_id = alternative_event['project_id']
            project_name = next((row['name'] for row in workspace.projects.projects.get_planning_catalog()
                                 if row['id'] == project_id), str(project_id))
            _manage_project_resource_pools_dialog(project_id, project_name, workspace, alternative_event)
        elif alternative_event['operation'] == 'manage_task_tags':
            _manage_task_tags_dialog(alternative_event['id'], '', workspace, alternative_event)
        elif alternative_event['operation'] == 'import_csv_template':
            _schedule_csv_dialog(workspace, alternative_event['project_id'], 'import_csv_template', alternative_event)
        elif alternative_event['operation'] == 'export_csv_template':
            from app.domain.planning.schedule_template import export_template
            from app.presentation.components.csv_download import download_project_csv

            plan = selected_plan(alternative_event, workspace)
            download_project_csv(plan.project_id, str(alternative_event.get('nonce', plan.revision)),
                                 content=export_template(plan.content.tasks, plan.content.dependencies))
    active_rf = st.session_state.get("active_resource_pool_filter")
    if active_rf and workspace.resources is not None:
        _render_filtered_active_allocations(
            active_rf=active_rf, pool_details_cache=pool_details_cache, workspace=workspace
        )


@st.fragment(key="planning_workspace")
@planning_errors
def render_planning_milestones(workspace: PlanningWorkspace) -> None:
    """Render planning filters and their interactive Gantt and capacity grids."""
    st.html(
        """
        <style>
        .block-container {
            padding-top: 0 !important;
            padding-bottom: 0.8rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            max-width: 100% !important;
        }
        h1, h2, h3 {
            margin-top: 0 !important;
            margin-bottom: 0.25rem !important;
            padding-top: 0 !important;
        }
        div[data-testid="stVerticalBlock"] > div {
            margin-bottom: 0.25rem !important;
        }
        /* Robust styling for multiselect selected item chips */
        div[data-baseweb="tag"],
        span[data-baseweb="tag"],
        [data-testid="stMultiSelect"] div[data-baseweb="tag"],
        [data-testid="stMultiSelect"] span[data-baseweb="tag"],
        [data-testid="stMultiSelectTag"],
        [data-baseweb="tag"] {
            background-color: #FDE8EC !important;
            background: #FDE8EC !important;
            border: 1px solid #C41039 !important;
            border-radius: 6px !important;
        }
        div[data-baseweb="tag"] *,
        span[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] div[data-baseweb="tag"] *,
        [data-testid="stMultiSelect"] span[data-baseweb="tag"] *,
        [data-testid="stMultiSelectTag"] * {
            color: #C41039 !important;
            fill: #C41039 !important;
        }
        div[data-baseweb="tag"] span,
        span[data-baseweb="tag"] span,
        [data-testid="stMultiSelect"] [data-baseweb="tag"] span {
            color: #C41039 !important;
            font-weight: 600 !important;
        }
        div[data-baseweb="tag"] svg,
        span[data-baseweb="tag"] svg,
        [data-baseweb="tag"] svg path {
            fill: #C41039 !important;
            color: #C41039 !important;
        }
        </style>
        """,
    )
    if (dashboard_projects := st.session_state.pop('dashboard_planning_projects', None)) is not None:
        _clear_all_planning_filters()
        st.session_state['ms_multi_projects'] = dashboard_projects
    revision = workspace.revision()
    params = parameters_frame(workspace.schema.property_references())
    alias_translations = workspace.schema.alias_references(get_current_locale())
    chosen_fields = set(st.session_state.get("planning_flex_fields", []))
    property_ids = tuple(
        sorted(
            (
                str(p["param_id"])
                for p in params.to_dict("records")
                if str(p["param_id"]) in chosen_fields
            )
        )
    )
    df_projects, project_filter_frame, params, project_tag_records = load_planning_catalog(
        workspace, revision, property_ids
    )
    if df_projects.empty:
        st.info(t("planning.no_projects_available", default="No projects available for planning."))
        return
    master_proj_ids = [int(p) for p in df_projects["id"].tolist()]
    proj_map = dict(zip(df_projects["id"], df_projects["name"]))
    df_all_proj_tags = pd.DataFrame(project_tag_records)
    project_tags_by_id: dict[int, list[str]] = {}
    if not df_all_proj_tags.empty:
        for r in project_tag_records:
            t_name = r.get("tag_name")
            f_name = r.get("free_tag")
            if pd.notna(t_name) and str(t_name).strip():
                tag_name = str(t_name).strip()
                project_tags_by_id.setdefault(int(r["project_id"]), []).append(tag_name)
            if pd.notna(f_name) and str(f_name).strip():
                free_tag = str(f_name).strip()
                project_tags_by_id.setdefault(int(r["project_id"]), []).append(free_tag)
    target_pid = st.session_state.pop("target_planning_project_id", None)
    if target_pid is not None:
        try:
            target_pid_int = int(target_pid)
            _clear_planning_flex_filter_state(clear_tracking=True)
            st.session_state["ms_planning_tag_filter"] = []
            st.session_state["ms_multi_projects"] = [target_pid_int]
        except (ValueError, TypeError):
            pass
    if st.session_state.pop("pending_clear_resource_pool_filter", False):
        st.session_state.pop("active_resource_pool_filter", None)
        _clear_planning_flex_filter_state(clear_tracking=True)
        st.session_state["ms_planning_tag_filter"] = []
        st.session_state["last_planning_tag_filter"] = []
        st.session_state["ms_multi_projects"] = master_proj_ids
    pending_rf = st.session_state.pop("pending_resource_pool_filter", None)
    if pending_rf is not None:
        if pending_rf.get("clear_other"):
            _clear_planning_flex_filter_state(clear_tracking=True)
            st.session_state["ms_planning_tag_filter"] = []
            st.session_state["last_planning_tag_filter"] = []
        if "target_pids" in pending_rf:
            st.session_state["ms_multi_projects"] = pending_rf["target_pids"]
    pending_project_filter = st.session_state.pop("pending_project_context_filter", None)
    if isinstance(pending_project_filter, dict):
        _focus_planning_on_project(pending_project_filter, workspace)
    active_rf = st.session_state.get("active_resource_pool_filter")
    if active_rf:
        f_pool_name = active_rf.get("pool_name", "Pool")
        f_start = active_rf.get("start_date", "")
        f_end = active_rf.get("end_date", "")
        f_count = active_rf.get("count", 0)
        b_info, b_btn = st.columns([5, 1])
        with b_info:
            st.info(
                f"🔍 **Active Filter from Resource Pool**: Showing {f_count} projects consuming **{f_pool_name}** during `{f_start} → {f_end}`."
            )
        with b_btn:
            if st.button("✖ Clear Filter", key="btn_clear_pool_filter_top", type="secondary"):
                _handle_clear_resource_pool_filter(master_proj_ids)
    project_filter_frame["_project_tags"] = project_filter_frame["id"].apply(
        lambda project_id: project_tags_by_id.get(int(project_id), [])
    )
    flex_filter_fields: dict[str, str] = {
        "name": t("portfolio.col_name", default="Project name"),
        "project_manager": t("master_data.field_project_manager", default="Project Manager"),
        "level_3_manager_name": t(
            "portfolio.filter_level_3_manager", default="Managing Function (Level 3)"
        ),
        "_project_tags": t("planning.flex_filter_project_tags", default="Project Tags"),
    }
    if not params.empty and "param_id" in params.columns:
        for _, parameter in params.iterrows():
            param_id = str(parameter["param_id"])
            param_name = property_label(parameter.to_dict(), alias_translations)
            target_column = param_id
            if param_id not in project_filter_frame.columns:
                project_filter_frame[param_id] = None
            if target_column is not None:
                field_label = param_name
                if field_label in flex_filter_fields.values():
                    field_label = f"{param_name} ({param_id})"
                flex_filter_fields[target_column] = field_label
    comparing = bool(st.session_state.get('planning_alternatives'))
    filter_columns = st.columns([1.2, 1.6, 2.4, 0.6, 1.2] if comparing else [1.2, 1.6, 3.6, 0.6],
                                vertical_alignment="bottom")
    top_flex_col, top_status_col, top_sel_col, top_clear_col = filter_columns[:4]
    with top_status_col:
        statuses = st.multiselect(t("dashboard.project_status", default="Project status"), PROJECT_STATUSES,
                                  default=["In Progress"], key="planning_statuses")
    status_project_ids = tuple(int(row.id) for row in df_projects.itertuples()
                               if not statuses or row.status in statuses)
    st.session_state["planning_status_project_ids"] = status_project_ids
    df_projects = df_projects[df_projects.id.isin(status_project_ids)]
    project_filter_frame = project_filter_frame[project_filter_frame.id.isin(status_project_ids)]
    st.session_state["planning_flex_fields"] = [field for field in st.session_state.get("planning_flex_fields", [])
                                                if field in flex_filter_fields]
    with top_clear_col:
        st.button(t("planning.clear_all_filters", default="Clear all filters"),
                  on_click=_clear_all_planning_filters, key="clear_all_planning_filters",
                  width="stretch")
    if comparing:
        with filter_columns[4]:
            st.button(t('planning.close_alternative_view', default='Close alternative view'),
                      on_click=close_alternative_view, key='close_alternative_view', width='stretch')
    active_flex_filters: dict[str, list[str]] = {}
    with top_flex_col:
        with st.popover(
            t("planning.flex_filters", default="Flexible filters"),
            icon=":material/filter_alt:",
            width="stretch",
        ):
            selected_flex_fields = st.multiselect(
                t("planning.flex_filter_fields", default="Filter fields"),
                options=list(flex_filter_fields),
                format_func=flex_filter_fields.get,
                placeholder=t(
                    "planning.flex_filter_fields_placeholder", default="Choose one or more fields"
                ),
                key="planning_flex_fields",
            )
            flex_match_mode = st.segmented_control(
                t("planning.flex_filter_match_label", default="When several values are selected"),
                options=["Any", "All"],
                default="Any",
                key="planning_flex_match_mode",
                help=t(
                    "planning.flex_filter_match_help",
                    default="Fields use AND. This controls matching within each field.",
                ),
            )
            for target_column in selected_flex_fields:
                field_label = flex_filter_fields[target_column]
                filter_options = _unique_planning_filter_options(
                    project_filter_frame[target_column]
                )
                selected_values = st.multiselect(
                    field_label,
                    options=filter_options,
                    placeholder=t("planning.flex_filter_all_values", default="All values"),
                    key=f"planning_flex_values::{target_column}",
                )
                if selected_values:
                    active_flex_filters[target_column] = selected_values
            st.button(
                t("planning.flex_filter_clear", default="Clear filters"),
                on_click=_clear_planning_flex_filter_state,
                width="stretch",
                disabled=not selected_flex_fields,
                key="btn_clear_planning_flex",
            )
    flex_signature = (
        tuple(statuses),
        flex_match_mode,
        tuple(sorted(((column, tuple(values)) for column, values in active_flex_filters.items()))),
    )
    previous_flex_signature = st.session_state.get("planning_last_flex_signature")
    flex_filters_changed = (
        previous_flex_signature is not None and previous_flex_signature != flex_signature
    )
    st.session_state["planning_last_flex_signature"] = flex_signature
    if active_flex_filters:
        project_filter_frame = _apply_planning_flex_filters(
            project_filter_frame, active_flex_filters, match_all_values=flex_match_mode == "All"
        )
        df_projects = df_projects[df_projects["id"].isin(project_filter_frame["id"].tolist())]
        st.caption(
            f"{len(active_flex_filters)} active flexible filter{('s' if len(active_flex_filters) != 1 else '')} · {len(df_projects)} matching projects"
        )
    if df_projects.empty:
        st.info(
            t(
                "planning.no_projects_available",
                default="No projects available with the current filter.",
            )
        )
        return
    all_proj_ids = df_projects["id"].tolist()
    cur_active_rf = st.session_state.get("active_resource_pool_filter")
    if cur_active_rf and "project_ids" in cur_active_rf:
        rf_pids = [p for p in cur_active_rf["project_ids"] if p in all_proj_ids]
        st.session_state["ms_multi_projects"] = rf_pids
    elif flex_filters_changed:
        st.session_state["ms_multi_projects"] = all_proj_ids
    elif "ms_multi_projects" in st.session_state:
        st.session_state["ms_multi_projects"] = [
            p for p in st.session_state["ms_multi_projects"] if p in all_proj_ids
        ]
    else:
        st.session_state["ms_multi_projects"] = []
    with top_sel_col:
        multi_header_label = f"🔍 {t('planning.select_multi_proj', default='Select Projects to Display in Multi-Gantt')} ({len(df_projects)} projects found)"
        selected_projects = st.multiselect(
            multi_header_label,
            options=all_proj_ids,
            format_func=lambda x: f"{x} - {proj_map.get(x, '')}",
            key="ms_multi_projects",
        )
        if not selected_projects and not cur_active_rf:
            selected_projects = all_proj_ids
    if not selected_projects:
        if active_rf:
            st.warning(
                f"No projects consume **{active_rf.get('pool_name')}** during `{active_rf.get('start_date')} → {active_rf.get('end_date')}`. Click 'Clear Filter' above to reset."
            )
            if st.button("✖ Clear Filter", key="btn_clear_empty_rf_filter"):
                _handle_clear_resource_pool_filter(master_proj_ids)
        else:
            st.info(
                t(
                    "planning.no_projects_available",
                    default="No projects available with the current filter.",
                )
            )
        return
    selected_id = selected_projects[0]
    proj_modal_id = st.session_state.pop("modal_manage_project_tag", None)
    if proj_modal_id:
        _manage_project_tags_dialog(
            int(proj_modal_id), proj_map.get(proj_modal_id, f"Project #{proj_modal_id}"), workspace
        )
    task_modal_info = st.session_state.pop("modal_manage_task_tag", None)
    if task_modal_info and isinstance(task_modal_info, dict):
        _manage_task_tags_dialog(
            int(task_modal_info["task_id"]), str(task_modal_info["task_name"]), workspace
        )
    task_pool_modal_info = st.session_state.pop("modal_manage_task_pool", None)
    if task_pool_modal_info and isinstance(task_pool_modal_info, dict):
        _manage_task_resource_pools_dialog(
            task_id=int(task_pool_modal_info["task_id"]),
            task_name=str(
                task_pool_modal_info.get("task_name", f"Task #{task_pool_modal_info['task_id']}")
            ),
            project_id=task_pool_modal_info.get("project_id", selected_id),
            workspace=workspace,
        )
    proj_pool_modal_id = st.session_state.pop("modal_manage_project_pool", None)
    if proj_pool_modal_id:
        _manage_project_resource_pools_dialog(
            int(proj_pool_modal_id),
            proj_map.get(int(proj_pool_modal_id), f"Project #{proj_pool_modal_id}"),
            workspace,
        )
    edit_project_modal_id = st.session_state.pop("modal_edit_project", None)
    _render_planning_chart(
        workspace,
        selected_projects,
        df_projects,
        proj_map,
        master_proj_ids,
        (
            flex_signature,
            [],
            st.session_state.get("active_resource_pool_filter"),
        ),
    )
    if edit_project_modal_id:
        open_edit_project_dialog(int(edit_project_modal_id), workspace.projects, read_only=True,
                                 allow_edit=not bool(st.session_state.get('planning_alternatives')))


@dialog("Active Allocations on Projects & Tasks", width="large")
@planning_errors
def _pool_allocations_dialog(pool_id: int, workspace: PlanningWorkspace, group_id: int | None = None,
                             *, start: str | None = None, end: str | None = None,
                             project_ids: tuple[int, ...] | None = None) -> None:
    """Reuse the Settings allocation projection for the chosen pool."""
    from app.presentation.components.resource_pool_dialogs import _render_pool_assignments_table
    from app.presentation.navigation import PAGE_PLANNING

    pool_ids = workspace.resources.group_pool_ids(group_id) if group_id else [pool_id]
    details = workspace.capacity.get_details(pool_ids) if pool_ids else []
    if not details:
        st.info("No resource pools found in this selection.")
        return
    if start and end:
        st.caption(f"{start} - {end}")
    for detail in details:
        st.subheader(detail.pool_name)
        _render_pool_assignments_table(
            scoped_assignments(detail.assignments, set(project_ids) if project_ids is not None else None, start, end),
            detail.pool_id, workspace.resources, PAGE_PLANNING, allow_unassign=False,
        )


@dialog("Schedule CSV", width="large")
@planning_errors
def _schedule_csv_dialog(workspace: PlanningWorkspace, project_id: int, action: str,
                         alternative_event: dict | None = None) -> None:
    """Load exports or validate an import only after its menu is invoked."""
    permissions = workspace.projects.projects.permissions()
    if not (permissions.allows(Permission.EDIT, project_id)
            or permissions.allows(Permission.APPROVE, project_id)):
        st.info(t("access.read_only", default="You have read-only access to this project."))
        return
    project = workspace.projects.projects.get_project_by_id(project_id)
    if project is None:
        st.error("The selected project no longer exists.")
        return
    st.subheader(project.name)
    from app.domain.planning.schedule_template import parse_template
    from app.presentation.pages.planning_alternative_editor import selected_plan, template_content

    plan = selected_plan(alternative_event, workspace) if alternative_event else None
    if plan:
        st.caption(plan.name)
    st.info("Import creates a new plan revision. Existing revisions are retained.")
    version_name = st.text_input("Version name", key=f"import_version_name_{project_id}")
    privileged = permissions.allows(Permission.SHARED) or permissions.allows(Permission.APPROVE, project_id)
    status = (st.selectbox("Revision status", ["draft", "proposed", "approved", "rejected"],
                          format_func=str.title) if privileged else "draft")
    if not privileged:
        st.caption("Revision status: Draft")
    st.checkbox("Set import as the active plan", value=False, disabled=True,
                help="Imported revisions remain inactive. Use scenario management to activate a revision.")
    st.caption(t("planning.csv_dependency_help", default=(
        "Use preceding_step, dependency_type and dependency_lag. For multiple predecessors, "
        "separate each column's values with semicolons in matching order (1;2 / FS;SS / 0;2). "
        "External references use task:123 or project:4 in preceding_step."
    )))
    from app.presentation.components.csv_upload import project_csv_upload

    content = project_csv_upload(
        t("planning.csv_upload_label"), key=f"uploader_steps_{project_id}",
    )
    if content is None:
        return
    date_format = st.selectbox(
        t("planning.csv_date_format", default="Date format in the CSV"),
        ["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"], index=1, key=f"template_date_format_{project_id}",
        help=t("planning.csv_date_help", default=(
            "Exports use YYYY-MM-DD. If your spreadsheet changed the dates, select its format. "
            "The preview shows the dates that will be saved."
        )),
    )
    steps = parse_template(content, date_format=date_format)
    steps_payload = list(csv.DictReader(io.StringIO(content.lstrip("\ufeff"))))
    for row, step in zip(steps_payload, steps, strict=True):
        row["start_date"] = step.values["start_date"]
        row["end_date"] = step.values["end_date"]
    st.dataframe(pd.DataFrame(steps_payload), width="stretch", hide_index=True)
    if st.button("Import plan revision", type="primary", disabled=not version_name.strip()):
        workspace.plans.import_revision(project_id, version_name, template_content(steps),
                                        status=status)
        st.toast(f"Imported {len(steps)} tasks as a new plan revision.")
        st.rerun()
