"""Install immutable demo Finance data and shares within the seed transaction."""

import psycopg

from app.domain.finance import BudgetRow
from app.domain.projects.seed_budgets import budget_rows, proposed_budget_rows, wbs_shares


SEED_BUDGET_NAME = 'Demo WBS budgets — ten-year plans'
SEED_PROPOSED_NAME = 'Demo WBS proposed budgets — ten-year plans'


def install_budget_definition(connection: psycopg.Connection, *, seed: int) -> None:
    """Seed linked Approved/Proposed versions without altering Finance history."""
    connection.execute('LOCK TABLE eppm.finance_snapshot IN SHARE ROW EXCLUSIVE MODE')
    existing = connection.execute(
        'SELECT id FROM eppm.finance_snapshot WHERE name=%s AND author=%s ORDER BY number DESC LIMIT 1',
        (SEED_BUDGET_NAME, 'demo-seeder')).fetchone()
    if existing:
        approved_id = existing[0]
        amounts = {code: {} for code, in connection.execute(
            'SELECT code FROM eppm.finance_row WHERE snapshot_id=%s ORDER BY position', (approved_id,))}
        for code, year, amount in connection.execute(
            'SELECT code,year,amount FROM eppm.finance_amount WHERE snapshot_id=%s ORDER BY code,year',
            (approved_id,)):
            amounts[code][year] = amount
        rows = tuple(BudgetRow(code, values) for code, values in amounts.items())
    else:
        rows = budget_rows(seed)
        approved_id = _install_snapshot(connection, SEED_BUDGET_NAME, 'Approved', rows)
    if not connection.execute(
        'SELECT 1 FROM eppm.finance_snapshot WHERE name=%s AND author=%s AND base_id=%s',
        (SEED_PROPOSED_NAME, 'demo-seeder', approved_id)).fetchone():
        _install_snapshot(connection, SEED_PROPOSED_NAME, 'Proposed',
                          proposed_budget_rows(rows, seed), base_id=approved_id)


def _install_snapshot(connection: psycopg.Connection, name: str, status: str,
                      rows: tuple[BudgetRow, ...], *, base_id: int | None = None) -> int:
    """Insert and seal an immutable seed snapshot in the caller's transaction."""
    identity = connection.execute(
        "INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at,base_id) "
        "SELECT coalesce(max(number),0)+1,%s,%s,'demo-seeder',extract(epoch FROM transaction_timestamp())::bigint,%s "
        "FROM eppm.finance_snapshot RETURNING id", (name, status, base_id)).fetchone()[0]
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.finance_row(snapshot_id,code,position) VALUES (%s,%s,%s)',
                           [(identity, row.code, index) for index, row in enumerate(rows)])
        cursor.executemany('INSERT INTO eppm.finance_amount(snapshot_id,code,year,amount) VALUES (%s,%s,%s,%s)',
                           [(identity, row.code, year, amount) for row in rows for year, amount in row.amounts.items()])
    connection.execute('UPDATE eppm.finance_snapshot SET sealed=true WHERE id=%s', (identity,))
    return identity


def assign_budget_shares(connection: psycopg.Connection, project_ids: list[int], *, seed: int) -> None:
    """Assign only newly generated In Progress projects, without replacing shares."""
    eligible = [row[0] for row in connection.execute(
        "SELECT id FROM eppm.project WHERE id=ANY(%s::bigint[]) AND status='In Progress' ORDER BY id", (project_ids,))]
    catalog = dict(connection.execute('SELECT code,id FROM eppm.wbs'))
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (%s,%s,%s)',
                           [(identity, catalog[code], percentage) for identity, code, percentage in wbs_shares(eligible, seed)])
