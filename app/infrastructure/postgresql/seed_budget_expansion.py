"""Operator-only additive WBS expansion preserving existing budget history."""

from decimal import Decimal

import psycopg

from app.domain.finance import BudgetRow
from app.domain.projects.seed_budgets import proposed_budget_rows
from app.domain.projects.seed_budget_expansion import expanded_budget_rows, expansion_project_shares, scaled_budget_rows
from app.infrastructure.postgresql.seed_budgets import _install_snapshot


def scale_current_budgets(connection: psycopg.Connection, *, approved_id: int,
                          proposed_id: int) -> dict[str, int]:
    """Create divided, whole-euro revisions from explicitly reviewed sources.

    The caller owns commit/rollback and the pre-operation backup. Source checks
    and table locks prevent accidental repeated scaling or concurrent revisions.
    """
    connection.execute('''LOCK TABLE eppm.finance_snapshot,eppm.finance_cancellation,
        eppm.finance_row,eppm.finance_amount IN SHARE ROW EXCLUSIVE MODE''')
    prepared = []
    for status, expected in (('Approved', approved_id), ('Proposed', proposed_id)):
        source = connection.execute('''SELECT s.id,s.name FROM eppm.finance_snapshot s
            WHERE status=%s AND sealed AND NOT EXISTS
            (SELECT 1 FROM eppm.finance_cancellation c WHERE c.snapshot_id=s.id)
            ORDER BY number DESC LIMIT 1''', (status,)).fetchone()
        if source is None or source[0] != expected:
            raise ValueError(f'The latest {status} revision changed; review before scaling.')
        amounts = {code: {} for code, in connection.execute(
            'SELECT code FROM eppm.finance_row WHERE snapshot_id=%s ORDER BY position', (expected,))}
        for code, year, amount in connection.execute(
            'SELECT code,year,amount FROM eppm.finance_amount WHERE snapshot_id=%s', (expected,)):
            amounts[code][year] = amount
        rows = scaled_budget_rows(tuple(BudgetRow(code, values) for code, values in amounts.items()))
        prepared.append((status, source, rows))
    return {status: _install_snapshot(connection, source[1], status, rows, base_id=source[0])
            for status, source, rows in prepared}


def expand_demo_budgets(
    connection: psycopg.Connection, *, high_budget_cap: Decimal,
    apply: bool = False,
) -> dict[str, object]:
    """Preview or atomically add budgets and mappings in the caller's transaction.

    Copy existing amounts into new sealed revisions, never edit approved history.
    A repeated/partially installed expansion is rejected before writing anything.
    Only previously unmapped projects receive a distinct WBS at 100 percent.
    """
    rows = expanded_budget_rows(high_budget_cap)
    codes = [row.code for row in rows]
    if apply:
        connection.execute('''LOCK TABLE eppm.finance_snapshot,eppm.finance_cancellation,
            eppm.finance_row,eppm.finance_amount,eppm.wbs,eppm.project_wbs,eppm.project
            IN SHARE ROW EXCLUSIVE MODE''')
    if connection.execute('SELECT 1 FROM eppm.wbs WHERE code=ANY(%s) LIMIT 1', (codes,)).fetchone():
        raise ValueError('The expansion WBS codes already exist; no changes were applied.')
    if connection.execute('SELECT 1 FROM eppm.finance_row WHERE code=ANY(%s) LIMIT 1', (codes,)).fetchone():
        raise ValueError('The expansion budget rows already exist; no changes were applied.')
    projects = connection.execute('''SELECT p.id,p.status FROM eppm.project p
        WHERE NOT EXISTS(SELECT 1 FROM eppm.project_wbs pw WHERE pw.project_id=p.id)
        ORDER BY p.id''').fetchall()
    shares = expansion_project_shares(projects, rows)
    previous = connection.execute('''SELECT s.id,s.name FROM eppm.finance_snapshot s
            WHERE s.status='Approved' AND s.sealed AND NOT EXISTS
                (SELECT 1 FROM eppm.finance_cancellation c WHERE c.snapshot_id=s.id)
            ORDER BY s.number DESC LIMIT 1''').fetchone()
    amounts = {code: {} for code, in connection.execute('SELECT code FROM eppm.wbs ORDER BY code')}
    if previous:
        for code, in connection.execute('SELECT code FROM eppm.finance_row WHERE snapshot_id=%s ORDER BY position', (previous[0],)):
            amounts.setdefault(code, {})
        for code, year, amount in connection.execute(
            'SELECT code,year,amount FROM eppm.finance_amount WHERE snapshot_id=%s', (previous[0],)):
            amounts[code][year] = amount
    combined = tuple(BudgetRow(code, values) for code, values in amounts.items()) + rows
    proposed = proposed_budget_rows(combined, seed=20260919)
    created = {}
    if apply:
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.wbs(code,description) VALUES (%s,%s)',
                               [(row.code, f'Demo budget {min(row.amounts)}-{max(row.amounts)}') for row in rows])
        identities = dict(connection.execute('SELECT code,id FROM eppm.wbs WHERE code=ANY(%s)', (codes,)))
        created['Approved'] = _install_snapshot(connection,
            previous[1] if previous else 'Demo approved budgets', 'Approved', combined,
            base_id=previous[0] if previous else None)
        created['Proposed'] = _install_snapshot(connection, 'Demo proposed budgets - expanded WBS',
            'Proposed', proposed, base_id=created['Approved'])
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO eppm.project_wbs(project_id,wbs_id,percentage) VALUES (%s,%s,100)',
                               [(project, identities[code]) for project, code in shares])
    return {'new_wbs': len(rows), 'historical_budgets': 500, 'future_budgets': 1000,
            'mapped_projects': len(shares),
            'completed_projects': sum(status == 'Completed' for _, status in projects),
            'other_projects': sum(status != 'Completed' for _, status in projects),
            'created_snapshots': created, 'applied': apply}
