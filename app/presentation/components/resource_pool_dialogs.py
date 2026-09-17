"""Resource-pool controls using injected application services."""

from collections.abc import Callable
from functools import wraps
from datetime import date
from app.domain.resources.hierarchy import PoolHierarchy

import pandas as pd
import streamlit as st

from app.presentation.components.dialog import dialog
from app.presentation.components.hierarchy import hierarchy_type_selector
from app.presentation.pages.pool_types import pool_type_selector

from app.application.exceptions import OrganizationStorageError, ResourcePoolStorageError
from app.application.services.resource_pools import ResourcePoolService
from app.domain.resources.models import (
    CapacityAssignment,
    PoolCapacityException,
    PoolMapping,
    ResourcePool,
)
from app.domain.resources.rules import (
    validate_pool_name,
    validate_capacity_fte,
)
from app.presentation.components.resource_pool_frames import (
    pools_frame,
    tags_frame,
    tag_choices_frame,
)
from app.presentation.i18n import get_current_locale, t


def pool_errors[**P](render: Callable[P, None]) -> Callable[P, None]:
    """Display safe application errors on page and dialog reruns."""

    @wraps(render)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            render(*args, **kwargs)
        except (ValueError, ResourcePoolStorageError, OrganizationStorageError) as exc:
            st.error(str(exc))

    return guarded


def require_change(changed: bool) -> None:
    """Prevent a concurrent deletion from being reported as a successful save."""
    if not changed:
        raise ValueError("This record no longer exists. Please refresh and try again.")


@dialog(t("settings.dialog_add_pool", default="Create Resource Pool"))
@pool_errors
def _open_add_pool_dialog(service: ResourcePoolService, parent_pool_id: int | None = None) -> None:
    """Modal dialog to create a new resource pool."""
    new_name = st.text_input(
        t("settings.field_pool_name", default="Resource Pool Name *"),
        placeholder="e.g. Core Engineering Pool",
    )
    new_desc = st.text_area(
        t("settings.field_pool_desc", default="Description"),
        placeholder="Purpose and specialty of this pool...",
    )
    pool_type_id = pool_type_selector(service, key="new_pool_type")
    hierarchy_type_id = hierarchy_type_selector(service.get_all_hierarchy_types())
    parent_pool_id = _parent_pool_selector(service, current=parent_pool_id)
    new_capacity = st.number_input(
        t("settings.field_pool_capacity", default="Defined capacity (FTE)"),
        min_value=0.0,
        value=0.0,
        step=0.25,
        help=t(
            "settings.field_pool_capacity_help",
            default="Capacity limit used to evaluate project and task demand.",
        ),
    )
    df_tags = tag_choices_frame(service.get_tag_choices())
    tag_labels = {
        int(row["id"]): str(row["tag"])
        for _, row in df_tags.iterrows()
    }
    selected_tag_ids = st.multiselect(
        "Pool tags",
        options=list(tag_labels),
        format_func=lambda tag_id: tag_labels[tag_id],
        placeholder="Select dictionary tags",
    )
    initial_exceptions = []
    with st.expander(t('pool_exceptions.title', default='Capacity exceptions')):
        if st.checkbox('Add an initial capacity exception', key='new_pool_add_exception'):
            first = st.date_input('Start date', value=date.today(), key='new_pool_exception_start')
            last = st.date_input('End date', value=date.today(), key='new_pool_exception_end')
            reduction = st.number_input('Capacity reduction (FTE)', min_value=0.001, value=0.5,
                                        step=0.25, key='new_pool_exception_reduction')
            reason = st.text_input('Reason', key='new_pool_exception_reason')
            initial_exceptions.append(PoolCapacityException(0, first.isoformat(), last.isoformat(), reduction, reason))
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save", default="Save Pool"), type="primary", width="stretch"
    ):
        validate_pool_name(new_name)
        validate_capacity_fte(float(new_capacity))
        p_id = service.create_pool(
            ResourcePool(
                name=new_name.strip(),
                description=new_desc.strip(),
                capacity_fte=float(new_capacity),
                pool_type_id=pool_type_id,
                hierarchy_type_id=hierarchy_type_id,
                parent_pool_id=parent_pool_id,
            ),
            tag_ids=selected_tag_ids,
            capacity_exceptions=initial_exceptions,
        )
        st.session_state['target_resource_pool_id'] = parent_pool_id if parent_pool_id is not None else p_id
        st.toast(f"Resource Pool '{new_name}' created (ID: {p_id})!")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


@dialog(t("settings.dialog_edit_pool", default="Edit Resource Pool"))
@pool_errors
def _open_edit_pool_dialog(service: ResourcePoolService, pool_id: int) -> None:
    """Modal dialog to edit an existing resource pool."""
    pool = service.get_pool_by_id(pool_id)
    if not pool:
        st.error("Resource pool not found.")
        return
    container = bool(PoolHierarchy(service.get_all_pools()).children.get(pool_id))
    if container:
        st.info("This pool is a container. Capacity is calculated from its children; assign its leaf pools to projects and tasks.")
    edit_name = st.text_input(
        t("settings.field_pool_name", default="Resource Pool Name *"), value=pool.name
    )
    edit_desc = st.text_area(
        t("settings.field_pool_desc", default="Description"), value=pool.description
    )
    pool_type_id = pool_type_selector(service, current=pool.pool_type_id, key=f"pool_type_{pool_id}")
    hierarchy_type_id = hierarchy_type_selector(service.get_all_hierarchy_types(), pool.hierarchy_type_id)
    parent_pool_id = _parent_pool_selector(service, current=pool.parent_pool_id, pool_id=pool_id)
    edit_capacity = st.number_input(
        t("settings.field_pool_capacity", default="Defined capacity (FTE)"),
        min_value=0.0,
        value=float(pool.capacity_fte or 0.0),
        disabled=container,
        step=0.25,
        help=t(
            "settings.field_pool_capacity_help",
            default="Capacity limit used to evaluate project and task demand.",
        ),
    )
    df_tags = tag_choices_frame(service.get_tag_choices())
    tag_labels = {
        int(row["id"]): str(row["tag"])
        for _, row in df_tags.iterrows()
    }
    existing_pool_tags = tags_frame(service.get_pool_tags(pool_id))
    existing_tag_ids = (
        [int(tag_id) for tag_id in existing_pool_tags["tag_id"].tolist()]
        if not existing_pool_tags.empty
        else []
    )
    selected_tag_ids = st.multiselect(
        "Pool tags",
        options=list(tag_labels),
        default=[identity for identity in existing_tag_ids if identity in tag_labels],
        format_func=lambda tag_id: tag_labels[tag_id],
        placeholder="Select dictionary tags",
    )
    col_save, col_cancel = st.columns(2)
    if col_save.button(
        t("settings.btn_save_changes", default="Save Changes"), type="primary", width="stretch"
    ):
        validate_pool_name(edit_name)
        validate_capacity_fte(float(edit_capacity))
        require_change(
            service.update_pool(
                ResourcePool(
                    id=pool_id,
                    name=edit_name.strip(),
                    description=edit_desc.strip(),
                    capacity_fte=0.0 if container else float(edit_capacity),
                    pool_type_id=pool_type_id,
                    hierarchy_type_id=hierarchy_type_id,
                    parent_pool_id=parent_pool_id,
                ),
                tag_ids=selected_tag_ids + [identity for identity in existing_tag_ids if identity not in tag_labels],
            )
        )
        st.toast("Resource Pool updated successfully!")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()

    if not container and not service.get_mappings_by_pool(pool_id):
        with st.expander(t('pool_exceptions.title', default='Capacity exceptions')):
            _capacity_exceptions_editor(service, pool_id)


def _parent_pool_selector(service: ResourcePoolService, *, current: int | None = None,
                          pool_id: int | None = None) -> int | None:
    """Offer valid ancestry and preview conversion warnings before saving."""
    tree = PoolHierarchy(service.get_all_pools())
    excluded = set(tree.descendants(pool_id)) if pool_id in tree.pools else set()
    options = [None, *(identity for identity in tree.pools if identity not in excluded)]
    selected = st.selectbox("Parent pool", options, index=options.index(current) if current in options else 0,
        format_func=lambda identity: "No parent (root pool)" if identity is None else tree.pools[identity].name,
        key=f"parent_pool_{pool_id}")
    if selected is not None and (pool_id is None or selected != current):
        warning = service.parent_pool_warning(selected)
        if warning:
            st.warning(warning)
        else:
            st.caption("The parent becomes a container and its capacity is calculated from its children.")
    return selected


def _capacity_exceptions_editor(service: ResourcePoolService, pool_id: int) -> None:
    """Edit, append or remove exception rows and save the whole grid atomically."""
    items = service.capacity_exceptions(pool_id)
    frame = pd.DataFrame([{'id': item.id, 'Start date': date.fromisoformat(item.start_date),
        'End date': date.fromisoformat(item.end_date), 'Capacity reduction (FTE)': item.reduction_fte,
        'Reason': item.reason} for item in items],
        columns=['id', 'Start date', 'End date', 'Capacity reduction (FTE)', 'Reason'])
    st.caption(t('pool_exceptions.help', default='Reductions are in FTE, not percentages. Overlapping reductions add together; effective capacity cannot fall below zero. Both dates are included.'))
    st.caption('Add rows at the bottom. Select rows to delete them. Save exceptions applies all grid changes together.')
    edited = st.data_editor(frame, num_rows='dynamic', hide_index=True, width='stretch',
        key=f'pool_exception_grid_{pool_id}', disabled=['id'], column_config={
            'id': None,
            'Start date': st.column_config.DateColumn(required=True, default=date.today()),
            'End date': st.column_config.DateColumn(required=True, default=date.today()),
            'Capacity reduction (FTE)': st.column_config.NumberColumn(required=True, min_value=.001, default=.5, format='%.3f'),
            'Reason': st.column_config.TextColumn(default=''),
        })
    if st.button('Save exceptions', type='primary', key=f'pool_exception_grid_save_{pool_id}'):
        rows = []
        for record in edited.to_dict('records'):
            if any(pd.isna(record[column]) for column in ('Start date', 'End date', 'Capacity reduction (FTE)')):
                raise ValueError('Each exception needs a start date, end date and capacity reduction.')
            rows.append(PoolCapacityException(pool_id, record['Start date'].isoformat(), record['End date'].isoformat(),
                float(record['Capacity reduction (FTE)']), '' if pd.isna(record['Reason']) else str(record['Reason']),
                None if pd.isna(record['id']) else int(record['id'])))
        service.replace_capacity_exceptions(pool_id, rows)
        st.toast('Capacity exceptions saved.')
        st.rerun()


@dialog(t("settings.delete_confirm_title", default="Confirm Deletion"))
@pool_errors
def _open_delete_pool_dialog(service: ResourcePoolService, pool_id: int, pool_name: str) -> None:
    """Modal dialog to confirm deletion of a resource pool."""
    st.warning(
        f"Are you sure you want to delete Resource Pool **{pool_name}** (ID: #{pool_id})?"
    )
    st.caption(
        "The pool will be marked as deleted and excluded from calculations. "
        "Its mappings and project/task assignments will be retained."
    )
    col_confirm, col_cancel = st.columns(2)
    if col_confirm.button(
        t("settings.btn_confirm_delete", default="Yes, Delete"), type="primary", width="stretch"
    ):
        require_change(service.delete_pool(pool_id))
        st.toast(f"Resource Pool '{pool_name}' deleted.")
        st.rerun()
    if col_cancel.button(t("settings.btn_cancel", default="Cancel"), width="stretch"):
        st.rerun()


def _remove_mapping_row(pool_id: int, kind: str, identity: int) -> None:
    """Remove a draft row and synchronize its selection before widgets rerender."""
    selection_key = f"mapping_{'teams' if kind == 'team' else 'employees'}_{pool_id}"
    st.session_state[selection_key] = [
        selected for selected in st.session_state[selection_key] if selected != identity
    ]
    st.session_state.pop(f'mapping_pct_{pool_id}_{kind}_{identity}', None)


@dialog(t("settings.dialog_add_mapping", default="Assign Team or Employee to Pool"), width="large")
@pool_errors
def _open_add_pool_mapping_dialog(
    service: ResourcePoolService, pool_id: int, df_teams: pd.DataFrame, df_employees: pd.DataFrame
) -> None:
    """Manage several employee and team mappings with individual percentages."""
    PoolHierarchy(service.get_all_pools()).require_leaf(pool_id)
    existing = {
        (row.target_type, row.target_id): row
        for row in service.get_mappings_by_pool(pool_id)
    }
    teams = {int(row.team_id): row.team_name for row in df_teams.itertuples()}
    employees = {
        int(row.employee_id): f"{row.firstname} {row.lastname}".strip()
        for row in df_employees.itertuples()
    }
    st.caption(
        'Select employees and teams to map. Each selection adds a grid row at 100%. '
        'Edit allocations or remove rows below. Save applies all changes together.'
    )
    selected_teams = st.multiselect(
        'Teams', list(teams),
        default=[identity for kind, identity in existing if kind == 'team' and identity in teams],
        format_func=lambda identity: f'{teams[identity]} [#{identity}]',
        key=f'mapping_teams_{pool_id}',
    )
    selected_employees = st.multiselect(
        'Employees', list(employees),
        default=[identity for kind, identity in existing if kind == 'employee' and identity in employees],
        format_func=lambda identity: f'{employees[identity]} [#{identity}]',
        key=f'mapping_employees_{pool_id}',
    )
    desired: list[PoolMapping] = []
    with st.container(border=True, key=f'pool_mapping_grid_{pool_id}'):
        widths = [1, 3, 2, 1]
        for column, heading in zip(st.columns(widths), ['Type', 'Name', 'Allocation (%)', 'Action']):
            column.markdown(f'**{heading}**')
        if not selected_teams and not selected_employees:
            st.caption('No mappings. Select a team or employee above to add a row.')
        for kind, identities, labels in [
            ('team', selected_teams, teams), ('employee', selected_employees, employees)
        ]:
            for identity in identities:
                current = existing.get((kind, identity))
                type_cell, name_cell, allocation_cell, action_cell = st.columns(
                    widths, vertical_alignment='center', wrap=False,
                )
                type_cell.text(kind.title())
                name_cell.text(labels[identity])
                percentage = allocation_cell.number_input(
                    f'{kind.title()}: {labels[identity]} - Allocation (%)',
                    min_value=0.0, max_value=100.0,
                    value=float(current.allocation_pct) if current else 100.0,
                    step=5.0, key=f'mapping_pct_{pool_id}_{kind}_{identity}',
                    label_visibility='collapsed',
                )
                action_cell.button(
                    'Remove', key=f'remove_mapping_{pool_id}_{kind}_{identity}',
                    on_click=_remove_mapping_row, args=(pool_id, kind, identity),
                )
                desired.append(PoolMapping(pool_id, kind, identity, percentage))
    save, cancel = st.columns(2)
    if save.button('Save mappings', type='primary', width='stretch'):
        service.save_mappings(pool_id, desired)
        st.toast('Mappings saved.')
        st.rerun()
    if cancel.button('Cancel', width='stretch'):
        st.rerun()


def _render_pool_assignments_table(
    assignments: list[CapacityAssignment],
    selected_pool_id: int,
    service: ResourcePoolService,
    planning_page: str,
    *,
    allow_unassign: bool = True,
) -> None:
    """Show navigation and optional unassignment actions on each allocation row."""
    from app.presentation.components.action_table import action_table

    if not assignments:
        st.info(t("settings.no_assignments_for_pool", default="This pool is not currently assigned to any project or task."))
        return
    rows = [{
        "id": int(row["id"]), "project": row["project_name"],
        "task": row["task_name"] if row["task_id"] else "Project level",
        "fte": f"{row['fte_assigned']:.2f}",
        "period": f"{row['start_date']} → {row['end_date']}",
        "notes": row.get("notes") or "—", "accessible_name": row["project_name"],
    } for row in assignments]
    event = action_table(rows, [
        ("id", "ID"), ("project", t("settings.col_project", default="Project")),
        ("task", t("settings.col_task", default="Task / Step")),
        ("fte", "Assigned FTE"), ("period", "Effective period"), ("notes", "Notes"),
    ], {"open": t("settings.go_to", default="Go to"), **({"unassign": "Unassign"} if allow_unassign else {})},
        key=f"pool_assignments_{selected_pool_id}")
    if event is None:
        return
    chosen = next(row for row in assignments if row["id"] == event["id"])
    if event["action"] == "unassign":
        _confirm_unassign(service, selected_pool_id, int(chosen["id"]), str(chosen["project_name"]))
    elif event["action"] == "open":
        st.session_state.pop("active_resource_pool_filter", None)
        st.session_state.pop("pending_resource_pool_filter", None)
        st.session_state.pop("target_planning_task_id", None)
        st.session_state["target_planning_project_id"] = int(chosen["project_id"])
        st.session_state["ms_multi_projects"] = [int(chosen["project_id"])]
        if chosen.get("task_id"):
            st.session_state["target_planning_task_id"] = int(chosen["task_id"])
        st.session_state["nav_redirect"] = planning_page
        st.rerun()


@dialog("Confirm unassignment")
@pool_errors
def _confirm_unassign(
    service: ResourcePoolService, pool_id: int, assignment_id: int, project_name: str,
) -> None:
    """Require explicit confirmation before removing the selected allocation."""
    st.write(f"Unassign allocation #{assignment_id} from {project_name}?")
    with st.container(horizontal=True):
        if st.button("Confirm unassign", type="primary", key=f"confirm_unassign_{assignment_id}"):
            current = service.get_assignment_by_id(assignment_id)
            if current is None or current.pool_id != pool_id:
                st.error("The allocation no longer exists in this pool.")
                return
            require_change(service.delete_assignment(assignment_id))
            st.toast("Allocation removed.")
            st.rerun()
        if st.button("Cancel", key=f"cancel_unassign_{assignment_id}"):
            st.rerun()
