"""Complete native demo commands preserve backup, catalog and additive policies."""

from decimal import Decimal

import psycopg
import pytest

from app.infrastructure.postgresql.backup import PostgresBackup, restore_database
from app.infrastructure.postgresql import maintenance
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.infrastructure.postgresql.seed_plan import source_fingerprint


def test_complete_native_default_seed_contains_annotations_scenarios_and_one_restorable_archive(pg_database, restore_target, clients, tmp_path):
    operator = OperatorDatabase(pg_database.operator_url)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    assert maintenance.seed_defaults(operator, backup, year=2026)
    result = maintenance.counts(operator)
    assert {key: result[key] for key in ('projects', 'tasks', 'dependencies', 'project_types', 'pools')} == {
        'projects': 5, 'tasks': 15, 'dependencies': 14, 'project_types': 5, 'pools': 33,
    }
    assert result['property_values'] > 100
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.project_tag').fetchone() == (5,)
        assert connection.execute('SELECT count(*) FROM eppm.task_tag').fetchone() == (15,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_assignment').fetchone()[0] == 11
        assert connection.execute('SELECT status,count(*) FROM eppm.project GROUP BY status').fetchall() == [('In Progress', 5)]
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone() == (0,)
        assert connection.execute('SELECT count(DISTINCT project_id) FROM eppm.resource_pool_assignment').fetchone() == (5,)
        assert connection.execute('SELECT sum(planned_budget),sum(actual_budget) FROM eppm.project').fetchone() == (
            Decimal('1250000'), Decimal('842000'),
        )
        assert connection.execute('SELECT count(*) FROM eppm.app_user').fetchone() == (0,)
    archives = list(tmp_path.glob('*.dump'))
    assert len(archives) == 1
    restore_database(archives[0], restore_target.operator_url, tools=clients)
    assert maintenance.counts(OperatorDatabase(restore_target.operator_url))['projects'] == 0
    assert not maintenance.seed_defaults(operator, backup)
    assert len(list(tmp_path.glob('*.dump'))) == 1
    assert not maintenance.seed_pool_scenarios(operator, backup, apply=True)['applied']


def test_catalog_only_install_pool_preview_apply_clear_and_reset_follow_archive_policy(pg_database, clients, tmp_path):
    operator = OperatorDatabase(pg_database.operator_url)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    assert maintenance.seed_defaults(operator, backup, include_projects=False)
    assert maintenance.counts(operator)['projects'] == 0
    assert maintenance.counts(operator)['pools'] == 33
    assert len(list(tmp_path.glob('*.dump'))) == 1
    before = operator.run(source_fingerprint)
    preview = maintenance.seed_pool_scenarios(operator, backup, apply=False, year=2026, replace=True)
    assert preview['new_pools'] == 33 and not preview['applied']
    assert operator.run(source_fingerprint) == before
    assert len(list(tmp_path.glob('*.dump'))) == 1
    assert maintenance.seed_pool_scenarios(operator, backup, apply=True, year=2026, replace=True)['applied']
    assert len(list(tmp_path.glob('*.dump'))) == 2
    assert maintenance.seed_defaults(operator, backup, force=True, year=2026)
    assert len(list(tmp_path.glob('*.dump'))) == 3
    assignment_count = operator.run(lambda c: c.execute('SELECT count(*) FROM eppm.resource_pool_assignment').fetchone()[0])
    assert assignment_count == 11
    assert maintenance.clear_pool_allocations(operator, backup) == assignment_count
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_mapping').fetchone() == (0,)
    assert maintenance.reset_database(operator, backup)['projects_deleted'] == 5
    assert maintenance.counts(operator)['pools'] == 33
    assert len(list(tmp_path.glob('*.dump'))) == 5


def test_existing_custom_catalog_gets_missing_references_without_demo_injection(pg_database, clients, tmp_path):
    operator = OperatorDatabase(pg_database.operator_url)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_type(name) VALUES ('Custom')")
    assert not maintenance.seed_defaults(operator, backup)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.employee').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.hierarchy_type').fetchone() == (7,)
        assert connection.execute('SELECT name FROM eppm.project_type ORDER BY id').fetchall() == [('Custom',), ('General',)]
    assert len(list(tmp_path.glob('*.dump'))) == 1


def test_default_seed_preserves_preexisting_pools_and_noncanonical_tag_group_choices(pg_database, clients, tmp_path):
    operator = OperatorDatabase(pg_database.operator_url)
    backup = PostgresBackup(pg_database.operator_url, tmp_path, tools=clients)
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Custom pool')")
        connection.execute("INSERT INTO eppm.tag_group(tag_group_name) VALUES ('projecttags'),('tasktags')")
    assert maintenance.seed_defaults(operator, backup)
    assert maintenance.counts(operator)['pools'] == 1
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.project_tag').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool_assignment WHERE pool_id=1').fetchone() == (0,)
        assert connection.execute('SELECT name FROM eppm.resource_pool WHERE id=1').fetchone() == ('Custom pool',)


@pytest.mark.parametrize('year', [0, 10000, True])
def test_invalid_default_seed_year_does_not_create_an_archive(pg_database, tmp_path, year):
    with pytest.raises(ValueError, match='scenario year'):
        maintenance.seed_defaults(OperatorDatabase(pg_database.operator_url), PostgresBackup(pg_database.operator_url, tmp_path), year=year)
    assert list(tmp_path.iterdir()) == []


def test_native_operator_cli_seed_preview_apply_counts_clear_and_reset(pg_database, clients, tmp_path, monkeypatch):
    from scripts.postgresql_admin import main

    monkeypatch.setenv('EPPM_TEST_OPERATOR_COMMAND_URL', pg_database.operator_url)
    prefix = ['postgresql_admin', '--url-variable', 'EPPM_TEST_OPERATOR_COMMAND_URL', '--backup-directory', str(tmp_path)]
    for options in (
        ['seed-defaults', '--without-projects'], ['seed-pools', '--year', '2026', '--replace'],
        ['seed-pools', '--year', '2026', '--replace', '--apply'], ['counts'], ['clear-allocations'], ['reset', '--all-references'],
    ):
        monkeypatch.setattr('sys.argv', prefix + options)
        main(archive_tools=clients)
    result = maintenance.counts(OperatorDatabase(pg_database.operator_url))
    assert result == {'projects': 0, 'tasks': 0, 'dependencies': 0, 'project_types': 1, 'property_values': 0, 'pools': 0}
    assert len(list(tmp_path.glob('*.dump'))) == 4
    monkeypatch.setattr('sys.argv', prefix + ['seed-defaults', '--year', '0'])
    with pytest.raises(SystemExit) as error:
        main(archive_tools=clients)
    assert error.value.code == 1
