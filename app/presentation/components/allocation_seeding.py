"""Preview and confirmation dialogs for resource-pool demo allocations."""

import pandas as pd
import streamlit as st

from app.application.exceptions import DatabaseMaintenanceError
from app.application.services.maintenance import MaintenanceService
from app.domain.resources.allocation_generation import AllocationGenerationRequest


def render_pool_allocation_controls(service: MaintenanceService) -> None:
    """Expose generation and demand clearing in the database-seeding section."""
    st.divider()
    if st.button("Generate pool allocations", key="generate_pool_allocations", width="stretch"):
        _generate_allocations_dialog(service)
    if st.button("Clear pool allocations", key="clear_pool_allocations", width="stretch"):
        _clear_allocations_dialog(service)


@st.dialog("Clear pool allocations")
def _clear_allocations_dialog(service: MaintenanceService) -> None:
    """Require confirmation before clearing all project and task demand."""
    st.warning("Remove every pool allocation from projects and tasks? Pools, employees, teams, and their memberships will be retained. A backup is created first.")
    if st.button("Confirm clear allocations", type="primary", key="confirm_clear_allocations"):
        try:
            removed = service.clear_pool_allocations()
        except DatabaseMaintenanceError as error:
            st.error(str(error))
            return
        st.cache_data.clear()
        st.session_state["seeding_status_message"] = f"Cleared {removed} pool allocations."
        st.rerun()
    if st.button("Cancel", key="cancel_clear_allocations"):
        st.rerun()


@st.dialog("Generate pool allocations", width="large")
def _generate_allocations_dialog(service: MaintenanceService) -> None:
    """Configure a feasible mix, inspect its preview, and explicitly apply it."""
    st.caption("Allocation uses available resource capacity, or the defined capacity for unstaffed pools. Overallocated and underallocated percentages apply to the selected pools; the remainder are fully allocated.")
    first, second = st.columns(2)
    allocated = first.number_input("Pools allocated (% of all pools)", min_value=0.0, max_value=100.0, value=80.0, key="seed_allocated_pct")
    average = second.number_input("Average allocation (% of capacity)", min_value=0.0, max_value=1100.0, value=80.0, key="seed_average_pct")
    first, second = st.columns(2)
    over = first.number_input("Overallocated pools (% of selected pools)", min_value=0.0, max_value=100.0, value=20.0, key="seed_over_pct")
    maximum = second.number_input("Maximum overallocation (% excess above 100%)", min_value=0.0, max_value=1000.0, value=50.0, key="seed_max_excess_pct")
    first, second = st.columns(2)
    under = first.number_input("Underallocated pools (% of selected pools)", min_value=0.0, max_value=100.0, value=50.0, key="seed_under_pct")
    unstaffed = second.number_input("Pools without employees or teams (% of all pools)", min_value=0.0, max_value=100.0, value=10.0, key="seed_unstaffed_pct")
    request = AllocationGenerationRequest(allocated, average, over, maximum, under, unstaffed)
    st.info("Generation replaces current project/task allocations. It removes resource mappings for the unstaffed pools and adds an employee to other pools when needed. Unstaffed pools without a positive capacity receive their current available capacity, or 1 FTE when none exists. Projects and task dates are retained.")
    if st.button("Preview allocations", key="preview_allocations"):
        try:
            report = service.generate_pool_allocations(request)
        except (ValueError, DatabaseMaintenanceError) as error:
            st.session_state.pop("pool_allocation_preview", None)
            st.error(str(error))
            return
        st.session_state["pool_allocation_preview"] = (request, report)
    preview = st.session_state.get("pool_allocation_preview")
    if preview is None or preview[0] != request:
        return
    report = preview[1]
    st.write(
        f"{report['allocated_pools']} of {report['total_pools']} pools allocated: "
        f"{report['overallocated_pools']} overallocated, {report['underallocated_pools']} underallocated, "
        f"{report['fully_allocated_pools']} fully allocated. Average: {report['average_allocation_pct']:.2f}%. "
        f"{report['unstaffed_pools']} pools without resources."
    )
    st.caption(
        f"Replace {report['assignments_removed']} allocations with {report['assignments_created']}. "
        f"Remove {report['mappings_removed']} resource mappings; add {report['mappings_created']}. "
        f"Set {report['capacity_limits_initialized']} missing/zero capacity limits. "
        "Pool counts are rounded to whole pools. FTE is rounded down to 0.001, so achieved percentages can be slightly below their targets."
    )
    st.dataframe(pd.DataFrame(report["rows"]).rename(columns={
        "pool_id": "Pool ID", "pool_name": "Pool", "allocation_pct": "Allocation (%)",
        "target_allocation_pct": "Target allocation (%)", "maximum_allocation_pct": "Peak allocation (%)",
        "unstaffed": "Without resources", "capacity_fte": "Available FTE",
    }), hide_index=True, width="stretch")
    if st.button("Apply allocation preview", type="primary", key="apply_allocation_preview"):
        try:
            service.generate_pool_allocations(request, apply=True, expected_fingerprint=report["fingerprint"])
        except (ValueError, DatabaseMaintenanceError) as error:
            st.error(str(error))
            return
        st.session_state.pop("pool_allocation_preview", None)
        st.cache_data.clear()
        st.session_state["seeding_status_message"] = "Pool allocations generated successfully. A backup was saved."
        st.rerun()
