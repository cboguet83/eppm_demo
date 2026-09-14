"""Native seed catalogs retain editable references, demo relationships and identity safety."""

from decimal import Decimal
import random
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import psycopg
import pytest

from app.domain.projects.project import prepare_project_values
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.projects import PostgresProjectStore
from app.infrastructure.postgresql.seed_catalog import (
    DEMO_TYPES, HIERARCHY_TYPES, advance_seed_sequences, can_install_demo, ensure_reference_catalog,
    install_organization_catalog, install_schema_catalog, install_tag_catalog, install_wbs_catalog, sample_values,
)


def install(connection):
    ensure_reference_catalog(connection)
    assert can_install_demo(connection)
    install_schema_catalog(connection)
    install_organization_catalog(connection)
    install_tag_catalog(connection)


def test_wbs_seed_adds_ten_codes_and_preserves_existing_entries(pg_database):
    """Repeated WBS installation retains identities, descriptions, and other codes."""
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.wbs(code,description) VALUES ('p.1.10','Retain'),('other','Unrelated')")
        install_wbs_catalog(connection)
        before = connection.execute('SELECT id,code,description FROM eppm.wbs ORDER BY id').fetchall()
        install_wbs_catalog(connection)
        assert connection.execute('SELECT id,code,description FROM eppm.wbs ORDER BY id').fetchall() == before
        assert {row[1] for row in before} == {'other', '#xx.xx.xx', *(f'p.{number}.10' for number in range(1, 11))}
        assert before[0][2] == 'Retain'


def test_default_seeder_creates_wbs_without_projects(pg_database):
    """The catalog-only seed includes the WBS entries used by full project seeds."""
    from app.infrastructure.postgresql.seeder import install_default_data
    with psycopg.connect(pg_database.operator_url) as connection:
        assert install_default_data(connection, force=False, include_projects=False, year=2026)
        assert {row[0] for row in connection.execute('SELECT code FROM eppm.wbs')} == {'#xx.xx.xx', *(f'p.{number}.10' for number in range(1, 11))}
        assert dict(connection.execute('SELECT code,description FROM eppm.wbs')) == {**{f'p.{n}.10': f'descripttion projet {n}' for n in range(1, 11)}, '#xx.xx.xx': 'otp fictif pour plannification'}
        assert {'maintenance', 'bim', 'amo', 'etudes', 'secutite'} <= {r[0] for r in connection.execute('SELECT name FROM eppm.project_role')}


def test_native_demo_catalog_has_current_definitions_relationships_and_editable_hierarchy_types(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.schema_parameters').fetchone() == (31,)
        assert connection.execute('SELECT count(*) FROM eppm.function').fetchone() == (60,)
        assert connection.execute('SELECT count(*) FROM eppm.employee').fetchone() == (50,)
        assert connection.execute('SELECT count(*) FROM eppm.team_function').fetchone() == (31,)
        assert connection.execute('SELECT count(*) FROM eppm.resource_pool').fetchone() == (0,)
        assert tuple(row[0] for row in connection.execute('SELECT code FROM eppm.hierarchy_type ORDER BY id')) == HIERARCHY_TYPES
        assert connection.execute('SELECT count(*) FROM eppm.hierarchy_type_translation').fetchone() == (35,)
        assert connection.execute('SELECT count(*) FROM eppm.team WHERE hierarchy_type_id IS NOT NULL').fetchone() == (0,)
        assert connection.execute("SELECT name FROM eppm.project_event_type WHERE system_code='blocking_point'").fetchone() == ('Blocking Point',)
        assert connection.execute('SELECT count(*) FROM eppm.project').fetchone() == (0,)
        assert connection.execute('SELECT count(*) FROM eppm.app_user').fetchone() == (0,)
        assert not can_install_demo(connection)


def test_reference_seed_markers_preserve_edited_and_removed_choices(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("DELETE FROM eppm.hierarchy_type WHERE code='brigade'")
        connection.execute("UPDATE eppm.hierarchy_type_translation SET label='Configured team' WHERE locale='en'")
        connection.execute('DELETE FROM eppm.project_event_type')
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.hierarchy_type').fetchone() == (6,)
        assert connection.execute('SELECT count(*) FROM eppm.project_event_type').fetchone() == (0,)
        assert connection.execute("SELECT DISTINCT label FROM eppm.hierarchy_type_translation WHERE locale='en'").fetchall() == [('Configured team',)]
        connection.execute("INSERT INTO eppm.operator_seed_state(catalog) VALUES ('demo')")
        assert not can_install_demo(connection)


def test_existing_reference_choices_are_not_replaced_on_first_operator_initialization(pg_database):
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.hierarchy_type(code) VALUES ('custom')")
        connection.execute("INSERT INTO eppm.project_event_type(name) VALUES ('Custom event')")
        connection.execute("INSERT INTO eppm.project_type(name,is_general) VALUES ('General',true)")
    OperatorDatabase(pg_database.operator_url).run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT code FROM eppm.hierarchy_type').fetchall() == [('custom',)]
        assert connection.execute('SELECT name FROM eppm.project_event_type').fetchall() == [('Custom event',)]
        assert can_install_demo(connection)
        connection.execute("INSERT INTO eppm.project_type(name) VALUES ('User template')")
        assert not can_install_demo(connection)


def test_generated_native_properties_validate_every_actual_template_and_keep_decimal_numbers(pg_database):
    OperatorDatabase(pg_database.operator_url).run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        store = PostgresProjectStore(connection)
        choices = store.choices()
        ordered = {}
        for identity, option in connection.execute('SELECT param_id,option_value FROM eppm.schema_param_options ORDER BY display_order,id'):
            ordered.setdefault(identity, []).append(option)
        for name, identity in connection.execute('SELECT name,id FROM eppm.project_type'):
            assert name in DEMO_TYPES
            template = store.template(identity)
            for index in range(1, 4):
                sample = sample_values(template, ordered, index, random.Random(42))
                values = prepare_project_values(template, choices, sample, creating=True)
                if name in ('Infrastructure', 'Renovation'):
                    assert isinstance(values['PRM_018'], Decimal)
                else:
                    assert 'PRM_018' not in values
                assert 'PRM_011' in values
                if name == 'Infrastructure' and index % 2:
                    assert 'railway' in values['PRM_011']


def test_seeded_explicit_ids_advance_sequences_and_normal_creates_do_not_collide(pg_database):
    OperatorDatabase(pg_database.operator_url).run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute("INSERT INTO eppm.function(name,hierarchy_level) VALUES ('New role',1) RETURNING function_id").fetchone()[0] > 60
        assert connection.execute("INSERT INTO eppm.employee(firstname,lastname,email,employee_code) VALUES ('New','Person','new@example.test','NEW') RETURNING employee_id").fetchone()[0] > 50
        assert connection.execute("INSERT INTO eppm.resource_pool(name) VALUES ('New pool') RETURNING id").fetchone()[0] > 0
        assert connection.execute("INSERT INTO eppm.schema_groups(group_name,display_order) VALUES ('New group',6) RETURNING id").fetchone()[0] > 5


def test_missing_required_enum_choices_fail_generation_without_mutating_definitions(pg_database):
    OperatorDatabase(pg_database.operator_url).run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        identity = connection.execute("SELECT id FROM eppm.project_type WHERE name='Infrastructure'").fetchone()[0]
        template = PostgresProjectStore(connection).template(identity)
        with pytest.raises(ValueError, match='required property PRM_017'):
            sample_values(template, {}, 2, random.Random(42))
        assert connection.execute('SELECT count(*) FROM eppm.project').fetchone() == (0,)


def test_seed_markers_are_private_operator_metadata(authorized):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query('SELECT * FROM eppm.operator_seed_state', user_id=4)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query("INSERT INTO eppm.operator_seed_state(catalog) VALUES ('demo')", user_id=4, write=True)


def test_populated_organization_and_tag_choices_are_kept_on_catalog_installation(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(install, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("UPDATE eppm.team SET team_name='Configured team' WHERE team_id=1")
        connection.execute("UPDATE eppm.employee SET firstname='Configured person' WHERE employee_id=1")
        connection.execute("UPDATE eppm.tag_group SET tag_group_name='Project Tags' WHERE tag_group_name='project_tag'")
    operator.run(lambda connection: (install_organization_catalog(connection), install_tag_catalog(connection)), write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.tag_group').fetchone() == (2,)
        assert connection.execute('SELECT team_name FROM eppm.team WHERE team_id=1').fetchone() == ('Configured team',)
        assert connection.execute('SELECT firstname FROM eppm.employee WHERE employee_id=1').fetchone() == ('Configured person',)


def test_repairing_an_explicit_task_identity_holds_concurrent_inserts_until_the_sequence_is_safe(pg_database):
    operator = OperatorDatabase(pg_database.operator_url)
    operator.run(ensure_reference_catalog, write=True)
    with psycopg.connect(pg_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project(name) VALUES ('Existing')")
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) "
                           "VALUES (100,1,'Explicit','2026-01-01','2026-01-02')")
    ready = Event()
    pids = []

    def insert():
        with psycopg.connect(pg_database.operator_url) as connection:
            pids.append(connection.execute('SELECT pg_backend_pid()').fetchone()[0])
            ready.set()
            return connection.execute("INSERT INTO eppm.project_task(project_id,task_name,start_date,end_date) "
                "VALUES (1,'Concurrent','2026-01-01','2026-01-02') RETURNING id").fetchone()[0]

    with psycopg.connect(pg_database.operator_url) as repair, ThreadPoolExecutor(max_workers=1) as executor:
        repair.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        advance_seed_sequences(repair, (('project_task', 'id'),))
        pending = executor.submit(insert)
        try:
            assert ready.wait(5)
            deadline = monotonic() + 5
            with psycopg.connect(pg_database.operator_url, autocommit=True) as inspector:
                while monotonic() < deadline:
                    row = inspector.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s', (pids[0],)).fetchone()
                    if row == ('Lock',):
                        break
                    sleep(0.01)
                else:
                    pytest.fail('The concurrent insert did not wait for sequence repair.')
            assert not pending.done()
        finally:
            repair.commit()
        assert pending.result(timeout=5) == 101
