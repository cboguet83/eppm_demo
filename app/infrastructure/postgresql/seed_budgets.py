"""Install immutable demo Finance data and shares within the seed transaction."""

import psycopg

from app.domain.projects.seed_budgets import budget_rows, wbs_shares


SEED_BUDGET_NAME = 'Demo WBS budgets — ten-year plans'


def install_budget_definition(connection: psycopg.Connection, *, seed: int) -> None:
    """Append and seal one demo Approved version without altering Finance history."""
    connection.execute('LOCK TABLE eppm.finance_snapshot IN SHARE ROW EXCLUSIVE MODE')
    if connection.execute('SELECT 1 FROM eppm.finance_snapshot WHERE name=%s AND author=%s',
                          (SEED_BUDGET_NAME, 'demo-seeder')).fetchone():
        return
    identity = connection.execute(
        "INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at) "
        "SELECT coalesce(max(number),0)+1,%s,'Approved','demo-seeder',extract(epoch FROM transaction_timestamp())::bigint "
        "FROM eppm.finance_snapshot RETURNING id", (SEED_BUDGET_NAME,)).fetchone()[0]
    rows = budget_rows(seed)
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.finance_row(snapshot_id,code,position) VALUES (%s,%s,%s)',
                           [(identity, row.code, index) for index, row in enumerate(rows)])
        cursor.executemany('INSERT INTO eppm.finance_amount(snapshot_id,code,year,amount) VALUES (%s,%s,%s,%s)',
                           [(identity, row.code, year, amount) for row in rows for year, amount in row.amounts.items()])
    connection.execute('UPDATE eppm.finance_snapshot SET sealed=true WHERE id=%s', (identity,))


def assign_budget_shares(connection: psycopg.Connection, project_ids: list[int], *, seed: int) -> None:
    """Assign only newly generated In Progress projects, without replacing shares."""
    eligible = [row[0] for row in connection.execute(
        "SELECT id FROM eppm.project WHERE id=ANY(%s::bigint[]) AND status='In Progress' ORDER BY id", (project_ids,))]
    catalog = dict(connection.execute('SELECT code,id FROM eppm.wbs'))
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (%s,%s,%s)',
                           [(identity, catalog[code], percentage) for identity, code, percentage in wbs_shares(eligible, seed)])
