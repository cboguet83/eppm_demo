"""Resource-pool settings backed by typed catalog and capacity use cases."""

import pandas as pd
import streamlit as st

from app.application.services.organization import OrganizationService
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.pool_capacity import PoolCapacityService
from app.presentation.components.organization_frames import (
    functions_frame,
    teams_frame,
    employees_frame,
)
from app.presentation.components.resource_pool_frames import (
    pools_frame,
    mappings_frame,
    tags_frame,
)
from app.presentation.components.resource_pool_dialogs import (
    pool_errors,
    require_change,
    _open_add_pool_dialog,
    _open_edit_pool_dialog,
    _open_delete_pool_dialog,
    _open_add_pool_mapping_dialog,
    _render_pool_groups_management,
    _render_pool_assignments_table,
)
from app.presentation.i18n import get_current_locale, t


@pool_errors
def render_resource_pools(
    service: ResourcePoolService,
    capacity: PoolCapacityService,
    organization: OrganizationService,
    planning_page: str,
) -> None:
    """Render summaries and fetch full capacity details only for the selected pool."""
    df_funcs = functions_frame(organization.get_all_functions())
    df_teams = teams_frame(organization.get_all_teams())
    df_emps = employees_frame(organization.get_all_employees())
    all_pool_details = capacity.get_summaries()
    total_pools = len(all_pool_details)
    total_portfolio_capacity = sum((p.total_capacity_fte for p in all_pool_details))
    total_assigned_capacity = sum((p.assigned_capacity_fte for p in all_pool_details))
    peak_portfolio_assigned = sum((p.peak_assigned_fte for p in all_pool_details))
    overassigned_pools_count = sum((1 for p in all_pool_details if p.is_overassigned))
    st.subheader(
        f"{t('settings.pools_title', default='Resource Pools Management')} ({total_pools} {t('settings.stat_pools', default='Pools')} • {total_portfolio_capacity:.2f} {t('settings.stat_capacity', default='FTE Capacity')})"
    )
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric(t("settings.kpi_total_pools", default="Total Pools"), total_pools)
    kpi2.metric(
        t("settings.kpi_total_capacity", default="Defined Capacity"),
        f"{total_portfolio_capacity:.2f} FTE",
    )
    kpi3.metric(
        t("settings.kpi_assigned_capacity", default="Assigned Capacity"),
        f"{total_assigned_capacity:.2f} FTE",
    )
    kpi4.metric(
        t("settings.kpi_peak_demand", default="Peak Active Demand"),
        f"{peak_portfolio_assigned:.2f} FTE",
    )
    if overassigned_pools_count > 0:
        kpi5.metric(
            t("settings.kpi_overassigned_pools", default="Overassigned Pools"),
            str(overassigned_pools_count),
            delta=f"+{overassigned_pools_count} Alert",
            delta_color="inverse",
            delta_arrow="off",
        )
    else:
        kpi5.metric(t("settings.kpi_overassigned_pools", default="Overassigned Pools"), "0")
    st.divider()
    _render_pool_groups_management(service)
    st.divider()
    col_sel, col_add_btn = st.columns([4, 1])
    with col_add_btn:
        if st.button(
            t("settings.btn_create_pool", default="Create Pool"),
            type="primary",
            width="stretch",
        ):
            _open_add_pool_dialog(service)
    df_all_pools = pools_frame(service.get_all_pools())
    if df_all_pools.empty:
        st.info(
            t(
                "settings.no_pools_registered",
                default="No resource pools registered yet. Click 'Create Pool' to add one.",
            )
        )
    else:
        pool_id_map = {int(p.pool_id): p for p in all_pool_details}
        pool_options = df_all_pools["id"].tolist()
        target_pool_id = st.session_state.pop("target_resource_pool_id", None)
        if target_pool_id is not None and int(target_pool_id) in pool_options:
            st.session_state["sb_selected_resource_pool"] = int(target_pool_id)
        with col_sel:
            selected_pool_id = st.selectbox(
                t(
                    "settings.select_pool_to_inspect",
                    default="Select Resource Pool to Inspect & Configure",
                ),
                options=pool_options,
                format_func=lambda pid: (
                    f"#{pid} - {pool_id_map[pid].pool_name} (Defined {pool_id_map[pid].total_capacity_fte:.2f} FTE | Assigned {pool_id_map[pid].assigned_capacity_fte:.2f} FTE {('| OVERASSIGNED' if pool_id_map[pid].is_overassigned else '| OK')})"
                    if pid in pool_id_map
                    else f"Pool #{pid}"
                ),
                key="sb_selected_resource_pool",
            )
        details = capacity.get_details([selected_pool_id])
        current_detail = details[0] if details else None
        if current_detail:
            c_info, c_actions = st.columns([4, 1])
            with c_info:
                st.markdown(
                    f"### **{current_detail.pool_name}** `[Pool #{current_detail.pool_id}]`"
                )
                pool_obj = service.get_pool_by_id(selected_pool_id)
                if pool_obj:
                    type_labels = {record.id: record.label(get_current_locale())
                                   for record in service.get_all_pool_types()}
                    st.text(t("pool_types.type", default="Pool type") + ": " + type_labels.get(pool_obj.pool_type_id, ""))
                if pool_obj and pool_obj.hierarchy_type_id is not None:
                    hierarchy_labels = {record.id: record.label(get_current_locale())
                                        for record in service.get_all_hierarchy_types()}
                    st.text(t("hierarchy.type") + ": " + hierarchy_labels.get(pool_obj.hierarchy_type_id, ""))
                if pool_obj and pool_obj.description:
                    st.caption(f"{pool_obj.description}")
                pool_tags = tags_frame(service.get_pool_tags(selected_pool_id))
                if not pool_tags.empty:
                    tag_text = " ".join(
                        (f"`{row['tag_name']}`" for _, row in pool_tags.iterrows())
                    )
                    st.markdown(f"{tag_text}")
            with c_actions:
                c_edit, c_del = st.columns(2)
                if c_edit.button(
                    "", key=f"btn_edit_pool_{selected_pool_id}", help="Edit pool details"
                ):
                    _open_edit_pool_dialog(service, selected_pool_id)
                if c_del.button("", key=f"btn_del_pool_{selected_pool_id}", help="Delete pool"):
                    _open_delete_pool_dialog(service, selected_pool_id, current_detail.pool_name)
            if current_detail.is_overassigned:
                st.error(
                    f"**DAILY OVERASSIGNMENT ALERT**: Peak daily demand of **{current_detail.peak_assigned_fte:.2f} FTE** exceeds defined pool capacity of **{current_detail.total_capacity_fte:.2f} FTE** by **+{current_detail.peak_excess_fte:.2f} FTE**!\n\n**Deduplicated assigned capacity**: {current_detail.assigned_capacity_fte:.2f} FTE.\n\n**Overassigned Period(s)**: {(', '.join(current_detail.overassignment_intervals) if current_detail.overassignment_intervals else 'Active overlapping assignments')}"
                )
            else:
                st.success(
                    f"**CAPACITY NORMAL**: Defined pool capacity is **{current_detail.total_capacity_fte:.2f} FTE**; deduplicated assigned capacity is **{current_detail.assigned_capacity_fte:.2f} FTE**. Peak active daily demand is **{current_detail.peak_assigned_fte:.2f} FTE**."
                )
            st.divider()
            st.write(
                f"#### / {t('settings.mapped_teams_funcs', default='Assigned Teams & Employees')} (0% - 100%)"
            )
            df_pool_maps = mappings_frame(service.get_mappings_by_pool(selected_pool_id))
            col_m_add, _ = st.columns([2, 3])
            with col_m_add:
                if st.button(
                    t("settings.btn_add_mapping", default="Assign Team or Employee"),
                    key=f"btn_add_map_{selected_pool_id}",
                ):
                    _open_add_pool_mapping_dialog(service, selected_pool_id, df_teams, df_emps)
            if df_pool_maps.empty:
                st.info(
                    t(
                        "settings.no_mappings_in_pool",
                        default="No teams or employees assigned to this pool yet. Click 'Assign Team or Employee' above.",
                    )
                )
            else:
                team_lookup = (
                    dict(zip(df_teams["team_id"], df_teams["team_name"]))
                    if not df_teams.empty
                    else {}
                )
                func_lookup = (
                    dict(zip(df_funcs["function_id"], df_funcs["name"]))
                    if not df_funcs.empty
                    else {}
                )
                employee_lookup = (
                    {
                        int(
                            row["employee_id"]
                        ): f"{str(row['firstname']).strip()} {str(row['lastname']).strip()}".strip()
                        for _, row in df_emps.iterrows()
                    }
                    if not df_emps.empty
                    else {}
                )
                for _, m_row in df_pool_maps.iterrows():
                    m_id = int(m_row["id"])
                    m_type = str(m_row["target_type"]).lower()
                    m_tid = int(m_row["target_id"])
                    m_pct = float(m_row["allocation_pct"])
                    if m_type == "team":
                        target_label = team_lookup.get(m_tid, f"Team #{m_tid}")
                        icon = "Team:"
                    elif m_type == "employee":
                        target_label = employee_lookup.get(m_tid, f"Employee #{m_tid}")
                        icon = "Employee:"
                    else:
                        target_label = func_lookup.get(m_tid, f"Function #{m_tid}")
                        icon = "Legacy function:"
                    mc1, mc2, mc3 = st.columns([3, 2, 1])
                    mc1.markdown(f"**{icon}** `{target_label}` `[#{m_tid}]`")
                    new_pct = mc2.number_input(
                        f"Allocation % (#{m_id})",
                        min_value=0.0,
                        max_value=100.0,
                        value=m_pct,
                        step=5.0,
                        key=f"num_alloc_pct_{m_id}",
                        label_visibility="collapsed",
                    )
                    if abs(new_pct - m_pct) > 0.01:
                        require_change(service.update_mapping(m_id, float(new_pct)))
                        st.rerun()
                    if mc3.button(
                        "", key=f"btn_del_map_{m_id}", help="Remove mapping from pool"
                    ):
                        require_change(service.delete_mapping(m_id))
                        st.toast("Mapping removed from pool.")
                        st.rerun()
            st.divider()
            st.write(
                f"#### {t('settings.dedup_breakdown_title', default='Deduplicated Assigned Capacity Breakdown')}"
            )
            st.caption(
                t(
                    "settings.dedup_caption",
                    default="Shows unique employees contributing to assigned capacity. Employees reached through several teams or assigned directly and through a team are counted once.",
                )
            )
            if not current_detail.contributing_resources:
                st.caption("No contributing functions found.")
            else:
                dedup_table_data = []
                for cf in current_detail.contributing_resources:
                    status_str = (
                        "Considered Once (Direct Override)"
                        if cf.is_deduplicated
                        else "Standard"
                    )
                    dedup_table_data.append(
                        {
                            "Resource type": cf.resource_type.title(),
                            "Resource ID": cf.resource_id,
                            "Resource": cf.resource_name,
                            "Function": cf.function_name,
                            "Nominal FTE": f"{cf.nominal_fte:.2f}",
                            "Effective %": f"{cf.effective_allocation_pct:.1f}%",
                            "Effective FTE": f"{cf.effective_fte:.2f}",
                            "Source": f"{cf.source_type.title()} ({cf.source_name})",
                            "Deduplication Rule": status_str,
                        }
                    )
                st.dataframe(pd.DataFrame(dedup_table_data), width="stretch", hide_index=True)
            st.divider()
            st.write(
                f"#### / {t('settings.assignments_section_title', default='Active Allocations on Projects & Tasks')}"
            )
            _render_pool_assignments_table(
                current_detail.assignments, selected_pool_id, service, planning_page
            )
