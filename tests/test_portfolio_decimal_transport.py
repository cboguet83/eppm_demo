"""Exact portfolio decimals reach the component without a float intermediary."""

from decimal import Decimal
import json
from types import SimpleNamespace

from app.presentation.components import portfolio_table


def test_component_payload_preserves_decimal_cells_facets_queries_and_statistics(monkeypatch):
    captured = []
    def mount(**options):
        captured.append(options['data'])
        return SimpleNamespace(row_click=7)
    monkeypatch.setattr(portfolio_table.st.components.v2, 'component', lambda *args, **kwargs: mount)
    exact = Decimal('9007199254740993.01234567890123456789')
    rows = [{'project_id': 7, 'planned_budget': exact, 'name': 'Exact', 'status': None, 'is_overallocated': False}]
    facet = {'values': [{'value': exact, 'count': 1}], 'stats': [('Average', exact)]}
    page_info = {'facet': facet, 'query': {'filters': {'planned_budget': {'values': [exact]}}}}
    assert portfolio_table.portfolio_project_table(rows, [{'key': 'planned_budget', 'format': 'currency'}], 7,
                                                  key='exact', page_info=page_info) == 7
    payload = json.loads(json.dumps(captured[0], allow_nan=False))
    assert payload['rows'][0] == dict(rows[0], planned_budget=str(exact))
    assert payload['page_info']['facet'] == {'values': [{'value': str(exact), 'count': 1}], 'stats': [['Average', str(exact)]]}
    assert payload['page_info']['query']['filters']['planned_budget']['values'] == [str(exact)]
    assert rows[0]['planned_budget'] is exact and facet['values'][0]['value'] is exact
