"""Financial transaction schema upgrades and native integrity constraints."""

import psycopg
from psycopg import sql
import pytest

from app.infrastructure.postgresql.migration import check_schema, discover_migrations, migrate


def test_live_budget_upgrade_preserves_existing_transaction_history(empty_database, tmp_path):
    migrations = discover_migrations()
    for item in migrations[:61]:
        (tmp_path / item.name).write_bytes(item.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES ('Retained')")
        connection.execute("""INSERT INTO eppm.project_financial_transaction
            (project_id,fiscal_year,amount,currency,exchange_rate,amount_base_currency,financial_record_type,spending_type,wbs)
            VALUES (1,2026,100,'USD',0.9,90,'COMMITMENT','ORDER','A')""")
        before = connection.execute('SELECT * FROM eppm.project_financial_transaction').fetchall()
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[61:])
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute('SELECT * FROM eppm.project_financial_transaction').fetchall() == before


def test_upgrade_retains_existing_finance_and_project_data(empty_database, tmp_path):
    migrations = discover_migrations()
    for item in migrations[:60]:
        (tmp_path / item.name).write_bytes(item.sql.encode('utf-8'))
    migrate(empty_database.operator_url, directory=tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
        connection.execute("INSERT INTO eppm.project(name) VALUES ('Retained')")
        connection.execute("INSERT INTO eppm.finance_snapshot(number,name,status,author,created_at) VALUES (1,'Existing budget','Approved','test',900)")
        connection.execute("INSERT INTO eppm.finance_row(snapshot_id,code,position) VALUES (1,'Historical-WBS',0)")
        connection.execute("INSERT INTO eppm.finance_amount(snapshot_id,code,year,amount) VALUES (1,'Historical-WBS',2026,123.45)")
        connection.execute('UPDATE eppm.finance_snapshot SET sealed=true WHERE id=1')
        before = connection.execute('SELECT to_jsonb(p) FROM eppm.project p ORDER BY id').fetchall()
        budget_before = connection.execute('SELECT to_jsonb(s) FROM eppm.finance_snapshot s').fetchall()
    assert migrate(empty_database.operator_url) == tuple(item.name for item in migrations[60:])
    assert migrate(empty_database.operator_url) == ()
    with psycopg.connect(empty_database.operator_url) as connection:
        check_schema(connection)
        assert connection.execute('SELECT to_jsonb(p) FROM eppm.project p ORDER BY id').fetchall() == before
        assert connection.execute('SELECT to_jsonb(s) FROM eppm.finance_snapshot s').fetchall() == budget_before
        assert connection.execute('SELECT amount::text FROM eppm.finance_amount').fetchall() == [('123.45',)]
        columns = dict(connection.execute("""SELECT column_name,is_nullable FROM information_schema.columns
            WHERE table_schema='eppm' AND table_name='project_financial_transaction'"""))
        assert 'status' not in columns and 'wbs_id' not in columns
        for field in ('project_id', 'fiscal_year', 'amount', 'currency', 'exchange_rate',
                      'amount_base_currency', 'financial_record_type', 'spending_type', 'wbs'):
            assert columns[field] == 'NO'
        assert columns['source_transaction_id'] == 'YES'
        foreign_tables = {row[0] for row in connection.execute("""SELECT confrelid::regclass::text
            FROM pg_constraint WHERE conrelid='eppm.project_financial_transaction'::regclass AND contype='f'""")}
        assert foreign_tables == {'eppm.project', 'eppm.project_financial_transaction'}


@pytest.mark.parametrize(('field', 'value'), [
    ('wbs', ''), ('wbs', None), ('spending_type', None), ('project_id', 999),
    ('fiscal_year', 0), ('amount', None), ('amount', 'NaN'), ('currency', 'EURO'),
    ('exchange_rate', 0), ('exchange_rate', 'NaN'), ('amount_base_currency', 'NaN'),
    ('financial_record_type', 'DRAFT'), ('source_transaction_id', 999),
])
def test_database_rejects_invalid_required_values_and_references(authorized, field, value):
    fields = dict(project_id=1, fiscal_year=2026, amount='1.01', currency='EUR', exchange_rate='1',
                  amount_base_currency='1.01', financial_record_type='ACTUAL', spending_type='Future type', wbs='Unknown')
    fields[field] = value
    query = sql.SQL('INSERT INTO eppm.project_financial_transaction ({}) VALUES ({})').format(
        sql.SQL(',').join(map(sql.Identifier, fields)), sql.SQL(',').join(sql.Placeholder() for _ in fields))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        with pytest.raises(psycopg.IntegrityError):
            with connection.transaction():
                connection.execute(query, tuple(fields.values()))
        assert connection.execute('SELECT count(*) FROM eppm.project_financial_transaction').fetchone() == (0,)


def test_project_deletion_cascades_its_unreferenced_transactions(authorized):
    from tests.postgresql.test_financial_transactions import service, transaction

    finance = service(authorized)
    finance.create(transaction())
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('DELETE FROM eppm.project WHERE id=1')
        assert connection.execute('SELECT count(*) FROM eppm.project_financial_transaction').fetchone() == (0,)
