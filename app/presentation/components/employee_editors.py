"""Compact function-allocation and calendar grids for employee profiles."""

from datetime import date
from uuid import uuid4

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
                f'{person.firstname} {person.lastname} ({assignment.allocation_pct:.0f}%)')
    return {identity: name + (' — ' + ', '.join(occupants[identity]) if identity in occupants else ' — Vacant')
            for identity, name in names.items()}


def employee_function_editor(employee: Employee, functions: pd.DataFrame) -> list[EmployeeFunction]:
    """Edit explicit function shares while showing the active allocation total."""
    names = {int(row.function_id): f'{row.name} [#{row.function_id}]' for row in functions.itertuples()}
    active = set(names)
    for row in employee.assignments():
        names.setdefault(row.function_id, f'Deleted function [#{row.function_id}]')
    st.markdown('#### Function assignments')
    st.caption('Allocation across active functions must not exceed 100%. Delete removes a row; Save Changes applies the changes.')
    key = f'employee_functions_{employee.employee_id}'
    rows = _draft_rows(key, [{'function': row.function_id, 'percentage': float(row.allocation_pct)}
                            for row in employee.assignments()])
    assignments = []
    with st.container(border=True):
        _headers([3, 2, 1], ['Function', 'Allocation (%)', 'Action'])
        for row in rows:
            function_cell, percentage_cell, action_cell = st.columns([3, 2, 1], vertical_alignment='center')
            identity = function_cell.selectbox('Function', list(names), index=list(names).index(row['function']),
                format_func=names.get, key=row['_key'] + '_function', label_visibility='collapsed')
            percentage = percentage_cell.number_input('Allocation (%)', min_value=0.0, max_value=100.0,
                value=row['percentage'], step=5.0, format='%.0f', key=row['_key'] + '_percentage', label_visibility='collapsed')
            action_cell.button('Delete', key=row['_key'] + '_delete', on_click=_delete_row,
                args=(key, row['_key']), help=f'Remove assignment to {names[identity]}. Save Changes to apply.')
            assignments.append(EmployeeFunction(identity, percentage))
        if not rows:
            st.caption('No function assignments.')
    st.button('Add function assignment', key=key + '_add', disabled=not names, on_click=_add_row,
        args=(key, {'function': next(iter(names), None), 'percentage': 100.0}))
    total = sum(row.allocation_pct for row in assignments if row.function_id in active)
    if total > 100:
        st.error(f'⚠ {total:.0f}% allocated across active functions. Reduce the total to 100% or less before saving.')
    else:
        st.caption(f'Allocated to active functions: {total:.0f}% · Remaining: {100 - total:.0f}%')
    return assignments


def employee_exception_editor(service: OrganizationService, employee_id: int, normal_percentage: float) -> list[EmployeeCalendarException]:
    """Add, edit and remove inclusive employee exceptions in a single grid."""
    st.markdown('#### Employee Calendar Exceptions')
    st.caption('Availability replaces the normal occupation percentage during the period. Delete removes a row; Save Changes applies the changes.')
    key = f'employee_exception_grid_{employee_id}'
    rows = _draft_rows(key, [{'id': row.exception_id, 'start': date.fromisoformat(row.start_date),
        'end': date.fromisoformat(row.end_date), 'percentage': float(row.occupation_percentage), 'reason': row.reason or ''}
        for row in service.get_employee_calendar_exceptions(employee_id)])
    items = []
    with st.container(border=True):
        _headers([2, 2, 2, 3, 1], ['Start date', 'End date', 'Availability (%)', 'Reason', 'Action'])
        for row in rows:
            first, last, availability, reason, action = st.columns([2, 2, 2, 3, 1], vertical_alignment='center')
            start = first.date_input('Start date', value=row['start'], key=row['_key'] + '_start', label_visibility='collapsed')
            end = last.date_input('End date', value=row['end'], key=row['_key'] + '_end', label_visibility='collapsed')
            percentage = availability.number_input('Availability (%)', min_value=0.0, max_value=100.0,
                value=row['percentage'], step=5.0, format='%.0f', key=row['_key'] + '_percentage', label_visibility='collapsed')
            description = reason.text_input('Reason', value=row['reason'], key=row['_key'] + '_reason', label_visibility='collapsed')
            action.button('Delete', key=row['_key'] + '_delete', on_click=_delete_row, args=(key, row['_key']),
                help=f'Remove exception from {start} to {end}. Save Changes to apply.')
            items.append(EmployeeCalendarException(employee_id, start, end, percentage,
                reason=description, exception_id=row['id']))
        if not rows:
            st.caption('No calendar exceptions.')
    st.button('Add calendar exception', key=key + '_add', on_click=_add_row,
        args=(key, {'id': None, 'start': date.today(), 'end': date.today(), 'percentage': float(normal_percentage), 'reason': ''}))
    return items


def _draft_rows(key: str, initial: list[dict]) -> list[dict]:
    """Keep dynamic widget rows stable until saved or the dialog is closed."""
    if key + '_add' not in st.session_state or st.session_state.get(key + '_source') != initial:
        st.session_state[key] = [row | {'_key': key + '_' + uuid4().hex} for row in initial]
        st.session_state[key + '_source'] = initial
    return st.session_state[key]


def _add_row(key: str, values: dict) -> None:
    st.session_state[key].append(values | {'_key': key + '_' + uuid4().hex})


def _delete_row(key: str, identity: str) -> None:
    st.session_state[key] = [row for row in st.session_state[key] if row['_key'] != identity]


def _headers(widths: list[int], labels: list[str]) -> None:
    for column, label in zip(st.columns(widths), labels):
        column.markdown(f'**{label}**')
