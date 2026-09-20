"""Persist report fixtures in the authoritative transaction table."""

from decimal import Decimal

import psycopg


def set_project_amounts(connection: psycopg.Connection, project_id: int,
                       planned: Decimal | str | int = 0, actual: Decimal | str | int = 0) -> None:
    """Replace fixture transactions with exact EUR commitments and actuals."""
    connection.execute('DELETE FROM eppm.project_financial_transaction WHERE project_id=%s', (project_id,))
    with connection.cursor() as cursor:
        cursor.executemany('''INSERT INTO eppm.project_financial_transaction(project_id,fiscal_year,
            amount,currency,exchange_rate,amount_base_currency,financial_record_type,spending_type,wbs)
            VALUES(%s,2026,%s,'EUR',1,%s,%s,'CAPEX','TEST')''',
            [(project_id, value, value, kind) for value, kind in ((planned, 'COMMITMENT'), (actual, 'ACTUAL'))])


def create_financed_project(service, *, planned_budget=0, actual_budget=0, **fields):
    """Create project metadata separately from its financial transactions."""
    identity = service.create_project(**fields)
    service._gateway.run(lambda store: set_project_amounts(store.connection, identity, planned_budget, actual_budget), write=True)
    return identity
