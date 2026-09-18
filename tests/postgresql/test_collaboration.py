"""Native collaboration contracts, bounded contacts and atomic callbacks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier, Event

import psycopg
import pytest

from app.application.exceptions import CollaborationConflictError, CollaborationStorageError
from app.application.services.collaboration import CollaborationService
from app.domain.access.models import AccessDenied, Permission
from app.domain.projects.collaboration import EVENT_STATUSES
from app.infrastructure.postgresql.collaboration import PostgresCollaborationGateway


def gateway(authorized, user_id=4):
    return PostgresCollaborationGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access)


@pytest.fixture
def collaboration(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.function(function_id,name,hierarchy_level)
            VALUES (1,'Manager',1),(2,'Architect',1),(3,'Vacant function',1),(4,'Unrelated function',1)""")
        connection.execute("INSERT INTO eppm.employee(firstname,lastname,email,function_id,mobile,landline)\n            VALUES ('Alice','Smith','alice@example.test',1,'mobile-A','landline-A'),\n                   ('Bob','Jones','bob@example.test',2,'mobile-B','landline-B'),\n                   ('Charlie','Adams','charlie@example.test',1,'','landline-C'),\n                   ('Unrelated','Person','other@example.test',4,'private-mobile','private-landline')")
        connection.execute('INSERT INTO eppm.employee_function(employee_id,function_id) '
                           'SELECT employee_id,function_id FROM eppm.employee')
    service = CollaborationService(gateway(authorized))
    service.save_catalog('event_type', 'General information')
    return service


def event_values(service):
    return dict(title=' Review ', description='Review scope', deadline='2027-02-28', scope='internal',
                comment='Initial', event_type_id=service.list_catalog('event_type')[0]['id'])


@pytest.mark.parametrize('kind', ['role', 'event_type'])
def test_catalog_names_labels_fallback_and_unique_names_are_preserved(collaboration, authorized, kind):
    identity = collaboration.save_catalog(kind, ' Sponsor ')
    table = 'project_role' if kind == 'role' else 'project_event_type'
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute(f'INSERT INTO eppm.{table}_translation(catalog_id,locale,label) VALUES (%s,\'fr\',\'Parrain\')', (identity,))
    assert next(row for row in collaboration.list_catalog(kind, 'fr') if row['id'] == identity)['label'] == 'Parrain'
    assert next(row for row in collaboration.list_catalog(kind, 'de') if row['id'] == identity)['label'] == 'Sponsor'
    assert collaboration.save_catalog(kind, 'Executive sponsor', identity) == identity
    assert next(row for row in collaboration.list_catalog(kind) if row['id'] == identity)['label'] == 'Executive sponsor'
    assert next(row for row in collaboration.list_catalog(kind, 'fr') if row['id'] == identity)['label'] == 'Parrain'
    with pytest.raises(CollaborationConflictError):
        collaboration.save_catalog(kind, 'EXECUTIVE SPONSOR')
    with pytest.raises(ValueError, match='no longer exists'):
        collaboration.save_catalog(kind, 'Missing', 999)
    collaboration.delete_catalog(kind, identity)
    collaboration.delete_catalog(kind, identity)
    with pytest.raises(ValueError, match='Unknown project catalog'):
        collaboration.list_catalog('role; DROP TABLE project')
    with pytest.raises(ValueError, match='Unknown project catalog'):
        gateway(authorized).run(lambda store: store.list_catalog('untrusted', 'en'))


def test_catalog_rename_and_english_translation_roll_back_together(collaboration, authorized):
    role = collaboration.save_catalog('role', 'Original')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_translation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private failure detail' USING ERRCODE='23514'; END $$""")
        connection.execute('CREATE TRIGGER reject_translation BEFORE UPDATE ON eppm.project_role_translation FOR EACH ROW EXECUTE FUNCTION eppm.reject_translation()')
    with pytest.raises(CollaborationConflictError) as error:
        collaboration.save_catalog('role', 'Changed', role)
    assert 'private failure' not in str(error.value)
    assert collaboration.list_catalog('role') == [{'id': role, 'name': 'Original', 'label': 'Original'}]


def test_contacts_preserve_repeated_roles_and_follow_current_function_occupants(collaboration, authorized):
    role = collaboration.save_catalog('role', 'Sponsor')
    first = collaboration.save_contact(1, role, 1)
    second = collaboration.save_contact(1, role, 2)
    collaboration.save_contact(2, role, 1)
    contacts = collaboration.list_contacts(1)
    assert [row['person'] for row in contacts] == ['Charlie Adams, Alice Smith', 'Bob Jones']
    assert contacts[0]['mobile'] == 'mobile-A' and contacts[0]['landline'] == 'landline-C, landline-A'
    with pytest.raises(CollaborationConflictError):
        collaboration.save_contact(1, role, 1)
    with pytest.raises(CollaborationConflictError):
        collaboration.save_contact(1, role, 999)
    with pytest.raises(CollaborationConflictError):
        collaboration.delete_catalog('role', role)
    with pytest.raises(ValueError, match='this project'):
        collaboration.save_contact(2, role, 3, first)
    assert collaboration.save_contact(1, role, 3, first) == first
    assert collaboration.list_contacts(1)[0]['person'] == 'Vacant function'
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("UPDATE eppm.employee_function SET function_id=3 WHERE employee_id="
                           "(SELECT employee_id FROM eppm.employee WHERE email='alice@example.test')")
        connection.execute("INSERT INTO eppm.project_role_translation VALUES (%s,'fr','Parrain')", (role,))
    assert collaboration.list_contacts(1, 'fr')[0]['person'] == 'Alice Smith'
    assert collaboration.list_contacts(1, 'fr')[0]['role'] == 'Parrain'
    collaboration.delete_contact(2, first)
    assert len(collaboration.list_contacts(1)) == 2
    collaboration.reassign_contact(1, second, 1)
    assert collaboration.list_contacts(1)[1]['person'] == 'Charlie Adams'
    with pytest.raises(ValueError, match='this project'):
        collaboration.reassign_contact(2, second, 2)
    collaboration.delete_contact(1, second)
    assert len(collaboration.list_contacts(1)) == 1


def test_contact_phone_function_is_bounded_by_project_assignment_and_current_actor(collaboration, authorized):
    role = collaboration.save_catalog('role', 'Contact')
    collaboration.save_contact(1, role, 1)
    collaboration.save_contact(3, role, 2)
    reader = CollaborationService(gateway(authorized, 1))
    contacts = reader.list_contacts(1)
    assert contacts[0]['mobile'] == 'mobile-A'
    assert reader.list_contacts(2) == reader.list_contacts(3) == []
    assert authorized.query('SELECT mobile FROM eppm.project_contacts(1)') == [('mobile-A',)]
    assert authorized.query('SELECT mobile FROM eppm.project_contacts(3)') == []
    assert authorized.query('SELECT mobile FROM eppm.project_contacts(1)', user_id=3) == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(lambda connection: connection.execute('SELECT mobile FROM eppm.project_contacts(1)').fetchall())
    assert authorized.query('SELECT mobile FROM eppm.employee') == []
    with pytest.raises(psycopg.errors.UndefinedColumn):
        authorized.query('SELECT email FROM eppm.project_contacts(1)')
    choices = reader.function_choices()
    assert len(choices) == 4 and {key for row in choices for key in row} == {'function_id', 'function_name', 'person'}
    assert any(row['person'] == 'Unrelated Person' for row in choices)
    assert 'mobile' not in str(choices) and 'landline' not in str(choices)
    with pytest.raises(AccessDenied):
        reader.list_functions()
    assert any(row['mobile'] == 'private-mobile' for row in collaboration.list_functions())
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project_contact SET project_id=3 WHERE project_id=1')
    assert reader.list_contacts(1) == []
    assert authorized.query('SELECT mobile FROM eppm.project_contacts(1)') == []


def test_contacts_and_catalog_edits_use_authoritative_project_permissions(collaboration, authorized):
    role = collaboration.save_catalog('role', 'Sponsor')
    own = collaboration.save_contact(1, role, 1)
    readonly = collaboration.save_contact(2, role, 2)
    reader = CollaborationService(gateway(authorized, 1))
    assert reader.can_edit(1) and not reader.can_edit(2) and not reader.can_edit(3)
    for action in (lambda: reader.save_catalog('role', 'Denied'), lambda: reader.delete_catalog('role', role),
                   lambda: reader.save_contact(2, role, 1), lambda: reader.save_contact(3, role, 1),
                   lambda: reader.delete_contact(2, readonly), lambda: reader.reassign_contact(2, readonly, 1)):
        with pytest.raises(AccessDenied):
            action()
    assert reader.save_contact(1, role, 3, own) == own
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.query('UPDATE eppm.project_contact SET project_id=2 WHERE id=%s', (own,), write=True)


def test_useful_links_have_no_slot_limit_and_keep_project_qualified_updates(collaboration, authorized):
    identities = [collaboration.save_link(1, f'https://example.test/{index}', f'Link {index}') for index in range(120)]
    assert len(collaboration.list_links(1)) == 120
    assert collaboration.list_links(2) == []
    assert collaboration.save_link(1, ' https://example.test/new ', ' New alias ', identities[0]) == identities[0]
    assert collaboration.list_links(1)[0] == {'id': identities[0], 'url': 'https://example.test/new', 'alias': 'New alias'}
    with pytest.raises(ValueError, match='this project'):
        collaboration.save_link(2, 'https://example.test', 'Wrong owner', identities[0])
    collaboration.delete_link(2, identities[0])
    assert len(collaboration.list_links(1)) == 120
    collaboration.delete_link(1, identities[0])
    assert len(collaboration.list_links(1)) == 119
    readonly = collaboration.save_link(2, 'https://example.test', 'Readonly')
    hidden = collaboration.save_link(3, 'https://example.test', 'Hidden')
    reader = CollaborationService(gateway(authorized, 1))
    assert reader.list_links(3) == []
    with pytest.raises(AccessDenied):
        reader.delete_link(2, readonly)
    with pytest.raises(AccessDenied):
        reader.save_link(3, 'https://example.test', 'Denied')
    reader.delete_link(3, hidden)
    assert collaboration.list_links(3)


@pytest.mark.parametrize('status', EVENT_STATUSES)
def test_events_round_trip_all_states_and_keep_global_events_project_scoped(collaboration, authorized, status):
    values = event_values(collaboration)
    identity = collaboration.save_event(1, **values, status=status)
    row = collaboration.list_events(1)[0]
    assert row['title'] == 'Review' and row['status'] == status and row['deadline'] == '2027-02-28'
    datetime.strptime(row['created_at'], '%Y-%m-%d %H:%M:%S')
    values.update(scope='global', deadline=None, comment='Updated')
    assert collaboration.save_event(1, **values, status='closed', event_id=identity) == identity
    updated = collaboration.list_events(1)[0]
    assert updated['comment'] == 'Updated' and updated['scope'] == 'global' and updated['deadline'] is None
    assert updated['created_at'] == row['created_at'] and updated['updated_at'] >= row['updated_at']
    with pytest.raises(ValueError, match='this project'):
        collaboration.save_event(2, **values, event_id=identity)
    with pytest.raises(CollaborationConflictError):
        collaboration.delete_catalog('event_type', values['event_type_id'])
    collaboration.save_event(3, **values)
    assert CollaborationService(gateway(authorized, 1)).list_events(3) == []


def test_event_paging_and_dates_are_independent_of_database_session_format(collaboration, authorized):
    values = event_values(collaboration)
    selected_gateway = gateway(authorized)
    def seed(store):
        for index in range(105):
            store.save_event(1, {**values, 'title': str(index), 'status': 'new'}, None)
    selected_gateway.run(seed, write=True)
    assert len(collaboration.list_events(1)) == 50
    assert len(collaboration.list_events(1, limit=999)) == 100
    assert collaboration.list_events(1, offset=-5, limit=0)[0]['title'] == '104'
    assert [row['title'] for row in collaboration.list_events(1, offset=100)] == ['4', '3', '2', '1', '0']
    def formatted(store):
        store.connection.execute("SET LOCAL datestyle='German, DMY'")
        store.connection.execute("SET LOCAL timezone='Pacific/Honolulu'")
        return store.list_events(1, 'en', offset=0, limit=1)
    assert selected_gateway.run(formatted) == collaboration.list_events(1, limit=1)
    with pytest.raises(ValueError, match='page'):
        collaboration.list_events(1, limit=True)


def test_contact_resolution_keeps_one_snapshot_during_reassignment(collaboration, authorized):
    role = collaboration.save_catalog('role', 'Sponsor')
    contact = collaboration.save_contact(1, role, 1)
    ready, changed = Event(), Event()
    def read(store):
        first = store.list_contacts(1, 'en')
        ready.set()
        assert changed.wait(10)
        return first, store.list_contacts(1, 'en')
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(gateway(authorized, 1).run, read)
        assert ready.wait(10)
        try:
            collaboration.reassign_contact(1, contact, 2)
        finally:
            changed.set()
        first, second = future.result()
    assert first == second and first[0]['mobile'] == 'mobile-A'
    assert CollaborationService(gateway(authorized, 1)).list_contacts(1)[0]['mobile'] == 'mobile-B'


def test_concurrent_catalog_renames_replay_the_whole_name_and_label_change(collaboration, authorized):
    role = collaboration.save_catalog('role', 'Original')
    barrier, attempts = Barrier(2), [0, 0]
    class GatedGateway(PostgresCollaborationGateway):
        def __init__(self, index):
            super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
            self.index = index
        def run(self, operation, **options):
            def callback(store):
                attempts[self.index] += 1
                if attempts[self.index] == 1:
                    barrier.wait(timeout=10)
                return operation(store)
            return super().run(callback, **options)
    def rename(index):
        return CollaborationService(GatedGateway(index)).save_catalog('role', str(index), role)
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(rename, range(2))) == [role, role]
    row = collaboration.list_catalog('role')[0]
    assert row['name'] == row['label'] and sum(attempts) >= 3


def test_storage_outage_is_translated_without_private_connection_details(collaboration, authorized, caplog):
    authorized.database.close()
    with pytest.raises(CollaborationStorageError) as error:
        collaboration.list_catalog('role')
    assert 'postgresql://' not in str(error.value) + caplog.text


def test_blocking_event_type_rename_preserves_the_existing_system_identity(collaboration, authorized):
    identity = collaboration.save_catalog('event_type', 'Blocking Point')
    collaboration.save_catalog('event_type', 'Renamed blocking event', identity)
    assert authorized.query('SELECT system_code FROM eppm.project_event_type WHERE id=%s', (identity,), user_id=4) == [('blocking_point',)]


def test_contact_function_has_no_public_execute_and_filters_before_private_aggregation(collaboration, authorized):
    role = collaboration.save_catalog('role', 'Contact')
    collaboration.save_contact(1, role, 1)
    collaboration.save_contact(3, role, 4)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        function = connection.execute("""SELECT prosecdef,provolatile,proconfig FROM pg_proc
            WHERE oid='eppm.project_contacts(bigint)'::regprocedure""").fetchone()
        assert function[0] and function[1] == 's'
        assert 'search_path=pg_catalog, eppm, pg_temp' in function[2]
        assert not connection.execute("""SELECT EXISTS(SELECT 1 FROM pg_proc p,
            LATERAL aclexplode(p.proacl) privilege WHERE p.oid='eppm.project_contacts(bigint)'::regprocedure
            AND privilege.grantee=0 AND privilege.privilege_type='EXECUTE')""").fetchone()[0]
    # A caller-provided project id, including a nonexistent one, never selects other functions.
    assert authorized.query('SELECT mobile FROM eppm.project_contacts(999)') == []
    assert authorized.query('SELECT mobile FROM eppm.project_contacts(3)') == []
    assert authorized.query('SELECT mobile FROM eppm.project_contacts(3)', user_id=2) == [('private-mobile',)]
