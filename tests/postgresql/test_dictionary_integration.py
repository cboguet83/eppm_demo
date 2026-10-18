"""Shared catalog edits preserve revision, project scope and system identities."""

import psycopg
import pytest

from app.application.services.collaboration import CollaborationService
from app.application.services.dictionaries import DictionaryService
from app.application.exceptions import DictionaryConflictError
from app.domain.access.models import Permission
from app.domain.dictionaries import dictionary_edit
from app.infrastructure.postgresql.collaboration import PostgresCollaborationGateway
from app.infrastructure.postgresql.dictionaries import PostgresDictionaryGateway
from app.infrastructure.postgresql.revisions import snapshot
from tests.postgresql.test_dashboard import service as dashboard_service


def services(authorized, user_id=4):
    options = {'access': authorized.binding(user_id).access}
    dictionary = DictionaryService(PostgresDictionaryGateway(authorized.database,authorized.key,**options))
    collaboration = CollaborationService(PostgresCollaborationGateway(authorized.database,authorized.key,**options))
    return dictionary, collaboration


def revision(authorized):
    return snapshot(authorized.database,authorized.key,authorized.binding(1).access)


def test_translated_contacts_and_blockers_follow_commit_revision_and_project_scope(authorized):
    dictionary, admin = services(authorized)
    _, reader = services(authorized,1)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.function(function_id,name) VALUES (1,'Manager')")
    role = dictionary.save_entry('project_role','Sponsor',translations={'fr':'Parrain'})
    blocker = dictionary.save_entry('project_event_type','Blocking Point',translations={'fr':'Blocage'})
    for project in (1,3):
        admin.save_contact(project,role,1)
        admin.save_event(project,title='Visible' if project==1 else 'Private',description='',
                         deadline=None,scope='internal',comment='',event_type_id=blocker,status='active')
    dashboard = dashboard_service(authorized)
    assert reader.list_contacts(1,'fr')[0]['role']=='Parrain'
    assert reader.list_contacts(3,'fr') == []
    assert dashboard.issues([1],'fr')[0]['event_type']=='Blocage'
    assert dashboard.report([1]).issue_count == 1
    before = revision(authorized)
    dictionary.save_entry('project_role','Executive sponsor',role,{'fr':'Parrain principal'})
    dictionary.save_entry('project_event_type','Renamed blocker',blocker,{'fr':'Blocage renommé'})
    after = revision(authorized)
    assert before.catalog != after.catalog
    assert reader.list_contacts(1,'fr')[0]['role']=='Parrain principal'
    issues = dashboard.issues([1],'fr')
    assert [(row['title'],row['event_type']) for row in issues]==[('Visible','Blocage renommé')]
    assert dashboard.report([1]).issue_count == 1
    assert authorized.query("SELECT system_code FROM eppm.business_dictionary_entry WHERE dictionary_code='project_event_type' AND id=%s", (blocker,)) == [('blocking_point',)]
    with pytest.raises(DictionaryConflictError):
        dictionary.delete_entry('project_event_type',blocker)


def test_rolled_back_dictionary_edits_do_not_publish_labels_or_revision(authorized):
    dictionary, _ = services(authorized)
    identity = dictionary.save_entry('project_role','Sponsor',translations={'fr':'Parrain'})
    before = revision(authorized)
    gateway = PostgresDictionaryGateway(authorized.database,authorized.key,access=authorized.binding(4).access)
    def abort(store):
        store.save_entry('project_role',dictionary_edit('Uncommitted',{'fr':'Invisible'}),identity)
        raise ValueError('Deliberate transaction rollback')
    with pytest.raises(ValueError,match='Deliberate'):
        gateway.run(abort,write=True,permission=Permission.SHARED)
    assert revision(authorized) == before
    assert dictionary.translations('project_role',identity)=={'en':'Sponsor','fr':'Parrain'}


def test_dictionary_identity_guard_and_excluded_catalogs_remain_independent(authorized):
    dictionary, _ = services(authorized)
    identity = dictionary.save_entry('project_role','Sponsor')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        priorities = connection.execute('SELECT * FROM eppm.strategic_priority ORDER BY id').fetchall()
        connection.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES ('ZONE','Zone','ENUM')")
        option = connection.execute("INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES ('ZONE','North') RETURNING id").fetchone()[0]
        for column,value in [('id',identity+100),('code','forged'),('dictionary_code','project_event_type'),('system_code','blocking_point')]:
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(f'UPDATE eppm.business_dictionary_entry SET {column}=%s WHERE dictionary_code=\'project_role\' AND id=%s',(value,identity))
        assert connection.execute('SELECT * FROM eppm.strategic_priority ORDER BY id').fetchall()==priorities
        assert connection.execute('SELECT param_id,option_value FROM eppm.schema_param_options WHERE id=%s',(option,)).fetchone()==('ZONE','North')
