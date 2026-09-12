"""Native project atomicity, Decimal budgets, WBS caps and callback replay."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event

import psycopg
import pytest

from app.application.exceptions import ProjectConflictError, ProjectStorageError
from app.application.services.projects import ProjectService
from app.application.services.project_types import ProjectTypeService
from app.application.services.schema import SchemaService
from app.application.services.wbs import WbsService
from app.domain.access.models import AccessDenied, Permission
from app.domain.projects.project import Project
from app.infrastructure.postgresql.projects import PostgresProjectGateway
from app.infrastructure.postgresql.project_types import PostgresProjectTypeGateway
from app.infrastructure.postgresql.schema import PostgresSchemaGateway


def gateway(authorized, user_id=4):
    return PostgresProjectGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access)


@pytest.fixture
def projects(authorized):
    return ProjectService(gateway(authorized))


def catalogs(authorized):
    access = authorized.binding(4).access
    return (SchemaService(PostgresSchemaGateway(authorized.database, authorized.key, access=access)),
            ProjectTypeService(PostgresProjectTypeGateway(authorized.database, authorized.key, access=access)))


def update(service, project_id=1, **changes):
    row = service.get_project_by_id(project_id)
    fields = dict(project_id=project_id, name=row.name, status=row.status, planned_budget=row.planned_budget,
                  actual_budget=row.actual_budget, dynamic_attributes={}, function_id=row.function_id)
    return service.update_project(**(fields | changes))


def test_project_records_and_native_budget_columns_preserve_exact_euros(projects, authorized):
    planned = Decimal('9007199254740993.12')
    identity = projects.create_project(name=' Exact ', planned_budget=planned, actual_budget='0.10')
    row = projects.get_project_by_id(identity)
    assert row.name == 'Exact' and row.planned_budget == planned and row.actual_budget == Decimal('0.10')
    assert type(row.planned_budget) is type(row.actual_budget) is Decimal
    assert update(projects, identity, planned_budget=0.2, actual_budget=Decimal('-0.125'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT planned_budget,actual_budget FROM eppm.project WHERE id=%s', (identity,)).fetchone() == (Decimal('0.2'), Decimal('-0.125'))
        connection.execute('UPDATE eppm.project SET planned_budget=NULL,actual_budget=NULL WHERE id=%s', (identity,))
    assert projects.get_project_by_id(identity).planned_budget == Decimal(0)
    assert Project(planned_budget=0.1).planned_budget == Decimal('0.1')
    for invalid in (True, 'not an amount', Decimal('NaN'), float('inf')):
        with pytest.raises(ValueError, match='finite numbers'):
            projects.create_project(name='Invalid', planned_budget=invalid)


def test_explicit_ids_sequence_preview_and_deleted_ids_are_preserved(projects, authorized):
    assert projects.generate_project_id() == 4
    assert projects.create_project(project_id=1000, name='Explicit') == 1000
    assert projects.generate_project_id() == 1001
    assert projects.create_project(name='Generated') == 1001
    assert projects.delete_project(1001)
    assert projects.generate_project_id() == 1002
    with pytest.raises(ProjectConflictError):
        projects.create_project(project_id=1000, name='Duplicate')
    assert projects.get_project_by_id(1000).name == 'Explicit'
    reader = ProjectService(gateway(authorized, 1))
    with pytest.raises(AccessDenied):
        reader.generate_project_id()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query('SELECT eppm.allocate_project_id(2000)', write=True)
    with pytest.raises(psycopg.Error) as error:
        authorized.query('SELECT eppm.allocate_project_id(NULL)', user_id=4)
    assert error.value.sqlstate == '25001'


def test_type_switches_keep_inactive_values_and_planning_loads_only_requested_active_values(projects, authorized):
    schema, types = catalogs(authorized)
    special = types.create_type('Rail')
    schema.create_parameter('p', None, 'Rail code', 'TEXT', applies_to_all=False, project_type_ids=[special])
    schema.create_parameter('n', None, 'Numeric', 'NUMBER')
    types.save_rule(special, 'p', True, has_default=True, default_value='Initial')
    identity = projects.create_project(name='Line', project_type_id=special, dynamic_attributes={'n': Decimal('0.125')})
    assert projects.get_project_by_id(identity).dynamic_attributes == {'p': 'Initial', 'n': Decimal('0.125')}
    update(projects, identity, dynamic_attributes={'p': 'Edited'})
    update(projects, identity, project_type_id=1)
    assert projects.get_project_by_id(identity).dynamic_attributes['p'] == 'Edited'
    row = next(row for row in projects.get_planning_catalog(('p', 'n')) if row['id'] == identity)
    assert row['dynamic_attributes'] == {'n': Decimal('0.125')} and row['project_template'] == 'General'
    assert all(row['dynamic_attributes'] == {} for row in projects.get_planning_catalog())
    update(projects, identity, project_type_id=special)
    assert projects.get_project_by_id(identity).dynamic_attributes['p'] == 'Edited'
    with pytest.raises(ValueError, match='Required property'):
        update(projects, project_type_id=special)
    with pytest.raises(ValueError, match='do not apply'):
        projects.create_project(name='Invalid', dynamic_attributes={'p': 'Wrong type'})
    with pytest.raises(ValueError, match='Unknown project type'):
        projects.create_project(name='Missing type', project_type_id=999)
    with pytest.raises(AccessDenied):
        projects.update_project(999, '', 'Draft', 0, 0, {})
    assert not projects.delete_project(999) and not projects.exists(999)


def test_failed_property_batch_rolls_back_master_links_and_all_prior_values(projects, authorized):
    schema, _ = catalogs(authorized)
    for param_id in ('a', 'b'):
        schema.create_parameter(param_id, None, param_id, 'TEXT')
    identity = projects.create_project(name='Original', dynamic_attributes={'a': 'old', 'b': 'old'})
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_project_value() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.param_id='b' AND NEW.text_value='reject' THEN
            RAISE EXCEPTION 'private failure detail' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER reject_project_value BEFORE INSERT ON eppm.project_property_value FOR EACH ROW EXECUTE FUNCTION eppm.reject_project_value()')
    for action in (lambda: projects.create_project(name='Rolled back', dynamic_attributes={'a': 'new', 'b': 'reject'}),
                   lambda: update(projects, identity, name='Rolled back', planned_budget='99.99',
                                  dynamic_attributes={'a': 'new', 'b': 'reject'}, custom_links=[{'url': 'https://example.test', 'alias': 'Docs'}])):
        with pytest.raises(ProjectConflictError) as error:
            action()
        assert 'private failure' not in str(error.value)
    row = projects.get_project_by_id(identity)
    assert row.name == 'Original' and row.planned_budget == 0 and row.dynamic_attributes == {'a': 'old', 'b': 'old'}
    assert projects.get_links(identity) == []
    assert len(projects.get_planning_catalog()) == 4


def test_project_reads_and_permission_projection_keep_scopes_separate(projects, authorized):
    schema, _ = catalogs(authorized)
    schema.create_parameter('p', None, 'Property', 'TEXT')
    update(projects, 3, dynamic_attributes={'p': 'Hidden'})
    reader = ProjectService(gateway(authorized, 1))
    permissions = reader.permissions()
    assert permissions.allows(Permission.EDIT, 1) and permissions.allows(Permission.READ, 2)
    assert not permissions.allows(Permission.EDIT, 2) and not permissions.allows(Permission.READ, 3)
    assert projects.permissions().allows(Permission.SHARED)
    assert reader.get_project_by_id(3) is None and not reader.exists(3)
    assert [row['id'] for row in reader.get_planning_catalog(('p',))] == [1, 2]
    assert all(row['dynamic_attributes'] == {} for row in reader.get_planning_catalog(('p',)))
    for action in (lambda: reader.create_project(name='Denied'), lambda: reader.delete_project(1),
                   lambda: reader.update_project(2, 'Denied', 'Draft', 0, 0, {})):
        with pytest.raises(AccessDenied):
            action()
    assert update(reader, name='Allowed', dynamic_attributes={'p': 'Visible'})


def test_wbs_hidden_usage_and_late_failure_restore_the_whole_project_save(projects, authorized):
    catalog = WbsService(gateway(authorized))
    identity = catalog.save('SHARED', 'Description')
    update(projects, 3, wbs_allocations=[{'wbs_id': identity, 'percentage': 60}])
    reader = ProjectService(gateway(authorized, 1))
    update(reader, wbs_allocations=[{'wbs_id': identity, 'percentage': 20}])
    assert reader.get_wbs_options(1) == [{'id': identity, 'code': 'SHARED', 'description': 'Description', 'available': 40}]
    assert authorized.query('SELECT project_id FROM eppm.project_wbs') == [(1,)]
    with pytest.raises(AccessDenied):
        reader.get_wbs_options(3)
    with pytest.raises(AccessDenied):
        reader.get_wbs_allocations(3)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query('SELECT * FROM eppm.wbs_options(3)')
    with pytest.raises(ValueError, match='only 40%'):
        update(reader, name='Rollback', planned_budget='99.95', custom_links=[{'url': 'https://example.test', 'alias': 'Docs'}],
               wbs_allocations=[{'wbs_id': identity, 'percentage': 41}])
    assert reader.get_project_by_id(1).name == 'Editable' and reader.get_links(1) == []
    assert reader.get_wbs_allocations(1) == [{'wbs_id': identity, 'percentage': 20}]
    assert catalog.can_manage() and not WbsService(gateway(authorized, 1)).can_manage()
    assert projects.get_wbs_options()[0]['available'] == 20
    update(reader, wbs_allocations=[{'wbs_id': identity, 'percentage': 40}])
    assert catalog.list_catalog()[0]['available'] == 0
    update(reader)
    assert reader.get_wbs_allocations(1)[0]['percentage'] == 40


def test_wbs_reference_edits_and_removal_keep_zero_share_references_protected(projects, authorized):
    catalog = WbsService(gateway(authorized))
    identity = catalog.save('A.1')
    assert catalog.save('#NEW_1', 'Updated', identity) == identity
    with pytest.raises(ValueError, match='already exists'):
        catalog.save('#NEW_1')
    update(projects, wbs_allocations=[{'wbs_id': identity, 'percentage': 0}])
    with pytest.raises(ValueError, match='assigned'):
        catalog.delete(identity)
    update(projects, wbs_allocations=[])
    catalog.delete(identity)
    for action in (lambda: catalog.delete(identity), lambda: catalog.save('Missing', wbs_id=identity)):
        with pytest.raises(ValueError, match='no longer exists'):
            action()
    with pytest.raises(ValueError, match='no longer exists'):
        projects.create_project(name='Rollback', wbs_allocations=[{'wbs_id': 999, 'percentage': 0}])


def test_delete_restores_dependency_graph_and_other_children_if_parent_delete_fails(projects, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,predecessor_id)
            VALUES (10,1,'First','2026-09-01','2026-09-02',NULL),(11,1,'Second','2026-09-02','2026-09-03',10),
                   (12,2,'External','2026-09-03','2026-09-04',NULL)""")
        connection.execute('INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id) VALUES (11,10),(12,11)')
        connection.execute("INSERT INTO eppm.task_tag(task_id,free_tag) VALUES (10,'Tag')")
        connection.execute("INSERT INTO eppm.project_link(project_id,url,alias) VALUES (1,'https://example.test','Docs')")
        connection.execute("""CREATE FUNCTION eppm.reject_project_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private failure detail' USING ERRCODE='23514'; END $$""")
        connection.execute('CREATE TRIGGER reject_project_delete BEFORE DELETE ON eppm.project FOR EACH ROW EXECUTE FUNCTION eppm.reject_project_delete()')
    with pytest.raises(ProjectConflictError):
        projects.delete_project(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.task_dependencies').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM eppm.project_task').fetchone()[0] == 3
        assert connection.execute('SELECT count(*) FROM eppm.task_tag').fetchone()[0] == 1
        connection.execute('DROP TRIGGER reject_project_delete ON eppm.project')
    assert projects.delete_project(1)
    assert projects.get_links(1) == [] and not projects.exists(1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT id FROM eppm.project_task').fetchall() == [(12,)]
        assert connection.execute('SELECT count(*) FROM eppm.task_dependencies').fetchone()[0] == 0


def simultaneous_services(authorized):
    barrier, attempts = Barrier(2), [0, 0]
    class GatedGateway(PostgresProjectGateway):
        def __init__(self, index):
            super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
            self.index = index
        def run(self, operation, **options):
            def callback(store):
                attempts[self.index] += 1
                if options.get('write') and attempts[self.index] == 1:
                    barrier.wait(timeout=10)
                return operation(store)
            return super().run(callback, **options)
    return [ProjectService(GatedGateway(index)) for index in range(2)], attempts


def test_concurrent_wbs_claims_revalidate_the_global_remainder_after_retry(projects, authorized):
    identity = WbsService(gateway(authorized)).save('RACE')
    services, attempts = simultaneous_services(authorized)
    def claim(index):
        try:
            services[index].update_project(index + 1, 'Saved', 'Draft', 0, 0, {},
                                           wbs_allocations=[{'wbs_id': identity, 'percentage': 60}])
            return 'saved'
        except ValueError as error:
            assert 'only 40%' in str(error)
            return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(claim, range(2))) == ['rejected', 'saved']
    assert WbsService(gateway(authorized)).list_catalog()[0]['available'] == 40
    assert sum(attempts) >= 3


def test_concurrent_explicit_and_generated_ids_do_not_overwrite_projects(projects, authorized):
    services, _ = simultaneous_services(authorized)
    def create(index):
        return services[index].create_project(project_id=500 if index else None, name=str(index))
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(create, range(2)))
    assert len(set(result)) == 2 and result[1] == 500
    assert [projects.get_project_by_id(identity).name for identity in result] == ['0', '1']
    assert projects.generate_project_id() > max(result)


def test_project_replay_preserves_original_property_links_and_wbs_commands(projects, authorized):
    schema, _ = catalogs(authorized)
    schema.create_parameter('p', None, 'Tags', 'TAGS')
    identity = WbsService(gateway(authorized)).save('RETRY')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.project_attempt')
        connection.execute('GRANT USAGE ON SEQUENCE eppm.project_attempt TO eppm_runtime')
        connection.execute("""CREATE FUNCTION eppm.retry_project_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.project_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER retry_project_once BEFORE INSERT ON eppm.project_wbs FOR EACH ROW EXECUTE FUNCTION eppm.retry_project_once()')
    submitted, links, shares, attempts = {'p': ['Original']}, [{'url': 'https://example.test', 'alias': 'Docs'}], [{'wbs_id': identity, 'percentage': 30}], []
    class ChangedInputGateway(PostgresProjectGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts.append(1)
                if len(attempts) == 2:
                    submitted['p'][:] = ['Changed']
                    links[0]['alias'] = 'Changed'
                    shares[0]['percentage'] = 99
                return operation(store)
            return super().run(callback, **options)
    selected = ProjectService(ChangedInputGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    result = selected.create_project(name='Original', dynamic_attributes=submitted, custom_links=links, wbs_allocations=shares)
    assert len(attempts) == 2 and submitted == {'p': ['Changed']}
    assert projects.get_project_by_id(result).dynamic_attributes == {'p': ['Original']}
    assert projects.get_links(result)[0]['alias'] == 'Docs'
    assert projects.get_wbs_allocations(result)[0]['percentage'] == 30


def test_project_read_and_its_values_share_one_snapshot(projects, authorized):
    schema, _ = catalogs(authorized)
    schema.create_parameter('p', None, 'Property', 'TEXT')
    update(projects, dynamic_attributes={'p': 'Original'})
    ready, changed = Event(), Event()
    def read(store):
        first = store.find(1)
        ready.set()
        assert changed.wait(10)
        return first, store.find(1)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(gateway(authorized).run, read)
        assert ready.wait(10)
        try:
            update(projects, name='Changed', dynamic_attributes={'p': 'Changed'})
        finally:
            changed.set()
        first, second = future.result()
    assert first == second and first.dynamic_attributes == {'p': 'Original'}


def test_missing_general_and_native_storage_outage_keep_safe_errors(projects, authorized, caplog):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project_type SET is_general=false')
    with pytest.raises(ValueError, match='General project type is missing'):
        projects.create_project(name='No general')
    authorized.database.close()
    with pytest.raises(ProjectStorageError) as error:
        projects.get_project_by_id(1)
    assert 'postgresql://' not in str(error.value) + caplog.text


def test_categorical_defaults_and_changes_keep_native_protected_audit(projects, authorized):
    schema, types = catalogs(authorized)
    schema.create_parameter('region', None, 'Region', 'ENUM', initial_options=['North', 'South'])
    types.save_rule(1, 'region', has_default=True, default_value='North')
    identity = projects.create_project(name='Defaulted')
    assert projects.get_project_by_id(identity).dynamic_attributes == {'region': 'North'}
    update(projects, dynamic_attributes={'region': 'North'})
    reader = ProjectService(gateway(authorized, 1))
    with pytest.raises(AccessDenied):
        update(reader, dynamic_attributes={'region': 'South'})
    assert projects.get_project_by_id(1).dynamic_attributes['region'] == 'North'
    with psycopg.connect(authorized.setup.operator_url) as connection:
        before = connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone()[0]
    update(projects, dynamic_attributes={'region': 'South'})
    with psycopg.connect(authorized.setup.operator_url) as connection:
        assert connection.execute('SELECT count(*) FROM eppm.app_security_audit').fetchone()[0] > before
    with pytest.raises(ValueError):
        update(projects, dynamic_attributes={'region': 'Unknown'})
