"""Native dictionary upgrades, typed references and restricted runtime writes."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from app.infrastructure.postgresql.migration import discover_migrations, migrate
from app.infrastructure.postgresql.errors import MigrationError
from tests.postgresql.conftest import AuthorizedFixture


@pytest.mark.parametrize('locale', ['', '   '])
def test_runtime_translation_rejects_blank_locale(authorized: AuthorizedFixture, locale: str) -> None:
    """Enforce the planned locale rule even when authorized SQL bypasses Python."""
    identity = authorized.query(
        "INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) VALUES ('project_role','Sponsor') RETURNING id",
        user_id=4, write=True,
    )[0][0]
    with pytest.raises(psycopg.errors.CheckViolation):
        authorized.query(
            "INSERT INTO eppm.business_dictionary_translation VALUES ('project_role',%s,%s,'Rejected')",
            (identity, locale), user_id=4, write=True,
        )
    assert authorized.query(
        'SELECT locale FROM eppm.business_dictionary_translation WHERE entry_id=%s',
        (identity,), user_id=4,
    ) == []


def preceding_schema(setup, directory):
    """Install unchanged migration sources up to the dictionary upgrade."""
    for migration in (item for item in discover_migrations() if item.version < 69):
        with (directory / migration.name).open('w', encoding='utf-8') as output:
            output.write(migration.sql)
    migrate(setup.operator_url, directory=directory)


@pytest.mark.parametrize('fail_upgrade', [False, True])
@pytest.mark.parametrize('legacy_blank_locale', [False, True])
def test_dictionary_upgrade_preserves_overlapping_ids_and_rolls_back_failures(
    empty_database, tmp_path, fail_upgrade, legacy_blank_locale,
):
    preceding_schema(empty_database, tmp_path)
    with psycopg.connect(empty_database.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_role(id,name) VALUES (7,'Sponsor')")
        connection.execute("INSERT INTO eppm.project_event_type(id,name,system_code) VALUES (7,'Update',NULL),(42,'Renamed blocker','blocking_point')")
        connection.execute("INSERT INTO eppm.project_role_translation VALUES (7,'fr','Parrain'),(7,'legacy-LOCALE','Legacy')")
        if legacy_blank_locale:
            connection.execute("INSERT INTO eppm.project_role_translation VALUES (7,'','Legacy blank locale')")
        connection.execute("INSERT INTO eppm.project_event_type_translation VALUES (42,'pt','Impedimento')")
        connection.execute("INSERT INTO eppm.project_type(id,name,is_general) VALUES (1,'General',true)")
        connection.execute("INSERT INTO eppm.project(id,name) VALUES (10,'Project')")
        connection.execute("INSERT INTO eppm.function(function_id,name) VALUES (1,'Manager')")
        connection.execute("INSERT INTO eppm.project_contact(project_id,role_id,function_id) VALUES (10,7,1)")
        connection.execute("INSERT INTO eppm.project_log_event(project_id,title,event_type_id) VALUES (10,'Issue',42)")
        ledger = connection.execute('SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version').fetchall()
        if fail_upgrade:
            connection.execute('CREATE VIEW eppm.prevent_catalog_drop AS SELECT id FROM eppm.project_role')
    if fail_upgrade:
        with pytest.raises(MigrationError):
            migrate(empty_database.operator_url)
        with psycopg.connect(empty_database.operator_url) as connection:
            assert connection.execute("SELECT to_regclass('eppm.business_dictionary_entry')").fetchone() == (None,)
            assert connection.execute('SELECT id,name FROM eppm.project_role').fetchall() == [(7,'Sponsor')]
            assert connection.execute('SELECT version,name,checksum FROM eppm.schema_migration ORDER BY version').fetchall() == ledger
        return
    assert migrate(empty_database.operator_url) == (
        '0069_shared_business_dictionaries.sql', '0070_dictionary_locale_integrity.sql',
        '0071_project_update_headroom.sql',
    )
    assert migrate(empty_database.operator_url) == ()
    with psycopg.connect(empty_database.operator_url) as connection:
        assert connection.execute('SELECT dictionary_code,id,code,name,system_code FROM eppm.business_dictionary_entry ORDER BY dictionary_code,id').fetchall() == [
            ('project_event_type',7,'entry_7','Update',None),
            ('project_event_type',42,'entry_42','Renamed blocker','blocking_point'),
            ('project_role',7,'entry_7','Sponsor',None),
        ]
        expected_labels = [
            ('project_event_type',42,'pt','Impedimento'),
            ('project_role',7,'fr','Parrain'),
            ('project_role',7,'legacy-LOCALE','Legacy'),
        ]
        if legacy_blank_locale:
            expected_labels.append(('project_role',7,'','Legacy blank locale'))
        assert connection.execute('SELECT dictionary_code,entry_id,locale,label FROM eppm.business_dictionary_translation ORDER BY dictionary_code,locale').fetchall() == sorted(expected_labels)
        assert connection.execute("SELECT convalidated FROM pg_constraint WHERE conname='dictionary_locale_nonblank'").fetchone() == (not legacy_blank_locale,)
        assert connection.execute('SELECT role_id FROM eppm.project_contact').fetchall() == [(7,)]
        assert connection.execute('SELECT event_type_id FROM eppm.project_log_event').fetchall() == [(42,)]
        assert connection.execute('SELECT version,name,checksum FROM eppm.schema_migration WHERE version<69 ORDER BY version').fetchall() == ledger
        new_id = connection.execute("INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) VALUES ('project_role','New') RETURNING id").fetchone()[0]
        assert new_id > 42
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("INSERT INTO eppm.business_dictionary_translation VALUES ('project_role',%s,'','Rejected')", (new_id,))
        with pytest.raises(psycopg.errors.RestrictViolation), connection.transaction():
            connection.execute("DELETE FROM eppm.business_dictionary_entry WHERE dictionary_code='project_role' AND id=7")


def test_runtime_dictionary_membership_permissions_and_immutable_fields(authorized):
    role = authorized.query("INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) VALUES ('project_role','Sponsor') RETURNING id", user_id=4, write=True)[0][0]
    event = authorized.query("INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) VALUES ('project_event_type','Update') RETURNING id", user_id=4, write=True)[0][0]
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name) VALUES (1,'Manager')")
    for source, parameters in [
        ("INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) VALUES ('project_role','Denied')", ()),
        ("UPDATE eppm.business_dictionary_entry SET name='Denied' WHERE dictionary_code='project_role' AND id=%s", (role,)),
    ]:
        with pytest.raises((psycopg.Error, ValueError)):
            authorized.query(source, parameters, user_id=1, write=True)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        authorized.query('INSERT INTO eppm.project_contact(project_id,role_id,function_id) VALUES (1,%s,1)', (event,), user_id=4, write=True)
    with pytest.raises(psycopg.Error):
        authorized.query("INSERT INTO eppm.project_contact(project_id,role_id,function_id,role_dictionary_code) VALUES (1,%s,1,'project_event_type')", (event,), user_id=4, write=True)
    for column, value in [('id', 123), ('dictionary_code','project_event_type'), ('code','forged'), ('system_code','blocking_point')]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            authorized.query(f'UPDATE eppm.business_dictionary_entry SET {column}=%s WHERE dictionary_code=\'project_role\' AND id=%s', (value,role), user_id=4, write=True)
    assert authorized.query('SELECT code FROM eppm.business_dictionary ORDER BY code') == [('project_event_type',),('project_role',)]


def test_dictionary_classification_is_event_only_and_concurrent_safe(authorized):
    role = authorized.query("INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) VALUES ('project_role','Blocking Point') RETURNING system_code", user_id=4, write=True)
    assert role == [(None,)]
    def insert_blocker(_):
        try:
            return authorized.query("INSERT INTO eppm.business_dictionary_entry(dictionary_code,name) VALUES ('project_event_type','Blocking Point') RETURNING id", user_id=4, write=True)
        except psycopg.errors.UniqueViolation:
            return []
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(insert_blocker, range(2)))
    assert sum(bool(result) for result in results) == 1
    assert authorized.query("SELECT count(*) FROM eppm.business_dictionary_entry WHERE system_code='blocking_point'") == [(1,)]
    authorized.query("UPDATE eppm.business_dictionary_entry SET name='Renamed' WHERE system_code='blocking_point'", user_id=4, write=True)
    assert authorized.query("SELECT name FROM eppm.business_dictionary_entry WHERE system_code='blocking_point'") == [('Renamed',)]
