"""Unified OTP/year budget table with exact text-valued monetary editing."""

from functools import partial
from importlib.resources import files

import streamlit as st

from app.application.exceptions import FinanceStorageError
from app.application.services.project_budget import ProjectBudgetService
from app.domain.access.models import AccessDenied
from app.domain.finance import euro_text
from app.domain.project_budget import EDITABLE_KINDS, ROW_LABELS


def _save(service: ProjectBudgetService, project_id: int, key: str, state: dict) -> None:
    result = st.session_state.get(key, {})
    event = result.get('save') if isinstance(result, dict) else getattr(result, 'save', None)
    if (not isinstance(event, dict) or not isinstance(event.get('nonce'), str)
            or len(event['nonce']) > 64 or event['nonce'] == state.get('handled')):
        return
    state.update(handled=event['nonce'], error='', message='')
    try:
        changed = service.save(project_id, event.get('revision'), event.get('edits'))
        state['message'] = 'Budget saved.' if changed else 'No amounts changed.'
        state['generation'] = state.get('generation', 0) + 1
    except (AccessDenied, ValueError, FinanceStorageError) as error:
        state['error'] = str(error)


def render_project_budget(project_id: int, service: ProjectBudgetService) -> None:
    """Render the latest five nature rows per WBS using the supplied workbook layout."""
    try:
        view = service.view(project_id)
    except (AccessDenied, FinanceStorageError) as error:
        st.error(str(error))
        return
    if not view.rows:
        st.info('Assign a WBS to the project to enter its budget.')
        return
    st.caption('Amounts in EUR. Budget-Live is the current working project budget; Commitment is the forecast.')
    key = f'project_budget_{project_id}'
    state = st.session_state.setdefault(f'{key}_state', {})
    assets = files('app').joinpath('presentation', 'assets')
    component = st.components.v2.component('eppm_project_budget', html='<section class="project-budget"></section>',
        js=assets.joinpath('project_budget_grid.js').read_text(encoding='utf-8'),
        css=assets.joinpath('project_budget_grid.css').read_text(encoding='utf-8'))
    data = {'revision': view.revision, 'token': f'{view.revision}:{state.get("generation", 0)}',
            'can_edit': view.can_edit, 'years': list(service.years()),
            'error': state.get('error', ''), 'message': state.get('message', ''),
            'rows': [{'wbs': row.wbs, 'kind': row.kind, 'label': ROW_LABELS[row.kind],
                      'version': row.version, 'editable': row.kind in EDITABLE_KINDS,
                      'amounts': {str(year): euro_text(amount) for year, amount in row.amounts.items()}}
                     for row in view.rows]}
    component(data=data, key=key, height='content', on_save_change=partial(_save, service, project_id, key, state))
