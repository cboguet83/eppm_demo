"""Compact function-allocation and calendar grids for employee profiles."""

from datetime import date

import pandas as pd
import streamlit as st

from app.application.services.organization import OrganizationService
from app.domain.organization.models import Employee, EmployeeFunction, EmployeeCalendarException


def team_member_labels(service: OrganizationService, names: dict[int, str]) -> dict[int, str]:
    """Identify each employee/function share in the team's membership selector."""
    occupants: dict[int, list[str]] = {}
    for person in service.get_all_employees():
        for assignment in person.assignments():
            occupants.setdefault(assignment.function_id, []).append(
                f'{person.firstname} {person.lastname} ({assignment.allocation_pct:g}%)')
    return {identity: name + (' — ' + ', '.join(occupants[identity]) if identity in occupants else ' — Vacant')
            for identity, name in names.items()}


def employee_function_editor(employee: Employee, functions: pd.DataFrame) -> list[EmployeeFunction]:
    """Edit explicit function shares while showing the active allocation total."""
    names = {int(row.function_id): f'{row.name} [#{row.function_id}]' for row in functions.itertuples()}
    active = set(names)
    for row in employee.assignments():
        names.setdefault(row.function_id, f'Deleted function [#{row.function_id}]')
    reverse = {name: identity for identity, name in names.items()}
    st.markdown('#### Function assignments')
    st.caption('Add or remove rows. Allocation across active functions must not exceed 100%.')
    frame = pd.DataFrame([{'Function': names[row.function_id], 'Allocation (%)': row.allocation_pct}
                          for row in employee.assignments()], columns=['Function', 'Allocation (%)'])
    edited = st.data_editor(frame, hide_index=True, num_rows='dynamic', width='stretch',
        key=f'employee_functions_{employee.employee_id}', column_config={
            'Function': st.column_config.SelectboxColumn(options=list(names.values()), required=True),
            'Allocation (%)': st.column_config.NumberColumn(min_value=0, max_value=100, default=100, required=True),
        })
    rows = edited.to_dict('records')
    if any(row['Function'] not in reverse or pd.isna(row['Allocation (%)']) for row in rows):
        raise ValueError('Each function assignment needs a function and an allocation percentage.')
    assignments = [EmployeeFunction(reverse[row['Function']], float(row['Allocation (%)'])) for row in rows]
    total = sum(row.allocation_pct for row in assignments if row.function_id in active)
    if total > 100:
        st.error(f'⚠ {total:g}% allocated across active functions. Reduce the total to 100% or less before saving.')
    else:
        st.caption(f'Allocated to active functions: {total:g}% · Remaining: {100 - total:g}%')
    return assignments


def employee_exception_editor(service: OrganizationService, employee_id: int, normal_percentage: float) -> None:
    """Add, edit and remove inclusive employee exceptions in a single grid."""
    st.markdown('#### Employee Calendar Exceptions')
    st.caption('Add rows or select rows to delete. Availability replaces the normal occupation percentage during the period.')
    frame = pd.DataFrame([{'id': row.exception_id, 'Start date': date.fromisoformat(row.start_date),
        'End date': date.fromisoformat(row.end_date), 'Availability (%)': row.occupation_percentage, 'Reason': row.reason}
        for row in service.get_employee_calendar_exceptions(employee_id)],
        columns=['id', 'Start date', 'End date', 'Availability (%)', 'Reason'])
    edited = st.data_editor(frame, hide_index=True, num_rows='dynamic', width='stretch',
        key=f'employee_exception_grid_{employee_id}', disabled=['id'], column_config={
            'id': None,
            'Start date': st.column_config.DateColumn(required=True, default=date.today()),
            'End date': st.column_config.DateColumn(required=True, default=date.today()),
            'Availability (%)': st.column_config.NumberColumn(min_value=0, max_value=100, required=True, default=normal_percentage),
            'Reason': st.column_config.TextColumn(default=''),
        })
    if st.button('Save calendar exceptions', type='primary', key=f'save_employee_exception_grid_{employee_id}'):
        items = []
        for row in edited.to_dict('records'):
            if any(pd.isna(row[column]) for column in ('Start date', 'End date', 'Availability (%)')):
                raise ValueError('Each exception needs start/end dates and an availability percentage.')
            items.append(EmployeeCalendarException(employee_id, row['Start date'], row['End date'],
                float(row['Availability (%)']), reason='' if pd.isna(row['Reason']) else str(row['Reason']),
                exception_id=None if pd.isna(row['id']) else int(row['id'])))
        service.replace_employee_exceptions(employee_id, items)
        st.toast('Employee calendar exceptions saved.')
        st.rerun()
