"""Organization exports preserve records and reauthorize every CSV download."""

import csv
from dataclasses import fields
import io

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.application.services.business_access import BusinessAccess
from app.application.services.organization import OrganizationService
from app.domain.access.models import AccessDenied
from app.domain.organization.models import Employee, FunctionType, OrgFunction, Team
from app.infrastructure.authentication.downloads import DownloadRoutes
from app.infrastructure.postgresql.organization import PostgresOrganizationGateway
from tests.postgresql.test_organization import organization
from tests.postgresql.test_access_service import administrator, identity, pg_access


def test_csv_exports_all_four_catalogs_with_stable_fields_and_safe_text(organization):
    type_id = organization.create_function_type(FunctionType('Engineering, Europe'))
    function_id = organization.create_function(OrgFunction('=SUM(1,2)', 2, function_type_id=type_id))
    parent = organization.create_team(Team('Parent'))
    child = organization.create_team(Team('Équipe "Delivery"', parent_team_id=parent))
    organization.create_employee(Employee('Ada', 'Lovelace', 'ada@example.test', 'EMP-001', function_id=function_id))
    for catalog, model, count in [('functions', OrgFunction, 1), ('function_types', FunctionType, 1),
                                  ('teams', Team, 2), ('employees', Employee, 1)]:
        reader = csv.DictReader(io.StringIO(organization.export_csv(catalog)))
        assert reader.fieldnames == [field.name for field in fields(model)]
        rows = list(reader)
        assert len(rows) == count
        if catalog == 'teams':
            row = next(row for row in rows if row['team_id'] == str(child))
            assert row['parent_team_id'] == str(parent)
            assert row['team_name'] == 'Équipe "Delivery"'
        if catalog == 'functions':
            assert rows[0]['name'] == "'=SUM(1,2)"
            assert rows[0]['function_type_id'] == str(type_id)
    with pytest.raises(ValueError, match='Unknown organization catalog'):
        organization.export_csv('app_users')


def test_empty_export_still_contains_headers(organization):
    assert list(csv.reader(io.StringIO(organization.export_csv('teams')))) == [
        [field.name for field in fields(Team)]
    ]


def test_organization_download_checks_permissions_and_revoked_sessions(pg_access):
    access = pg_access.service
    admin = administrator(pg_access)
    cookie = access.sign_in(identity('organization-export'))
    actor = access.actor(cookie)
    access.set_status(admin, actor.user_id, 'active')

    def service(current):
        return OrganizationService(PostgresOrganizationGateway(
            pg_access.gateway.database, pg_access.gateway.signer.key,
            access=BusinessAccess(current, access.policy)))

    routes = DownloadRoutes(access, lambda actor, project: '',
                            export_organization=lambda actor, catalog: service(actor).export_csv(catalog),
                            export_teams=lambda actor, deleted, template: service(actor).export_csv(
                                'teams', include_deleted=deleted, template=template))
    with TestClient(Starlette(routes=routes.routes())) as browser:
        url = '/downloads/organization/employees.csv'
        assert browser.get(url).status_code == 403
        assert browser.get('/downloads/teams/teams.csv').status_code == 403
        browser.cookies.set('eppm_session', cookie)
        assert browser.get(url).status_code == 403
        with pytest.raises(AccessDenied):
            service(actor).export_csv('employees')
        grant = access.grant(admin, actor.user_id, 'business_admin', {'kind': 'all'})
        for catalog in ('functions', 'function_types', 'teams', 'employees'):
            response = browser.get(f'/downloads/organization/{catalog}.csv')
            assert response.status_code == 200
            assert response.content.startswith(b'\xef\xbb\xbf')
            assert response.headers['content-disposition'] == f'attachment; filename="{catalog}.csv"'
            assert response.headers['cache-control'] == 'no-store'
        assert browser.head(url).status_code == 200
        hidden = service(actor).create_team(Team('Hidden team'))
        service(actor).delete_team(hidden)
        team_url = '/downloads/teams/teams.csv'
        assert len(list(csv.DictReader(io.StringIO(browser.get(team_url).text.lstrip('\ufeff'))))) == 0
        assert len(list(csv.DictReader(io.StringIO(browser.get(team_url + '?include_deleted=true').text.lstrip('\ufeff'))))) == 1
        assert browser.get('/downloads/teams/template.csv').status_code == 200
        assert browser.get(team_url + '?include_deleted=invalid').status_code == 403
        assert browser.get('/downloads/organization/app_users.csv').status_code == 403
        access.revoke(admin, grant)
        assert browser.get(url).status_code == 403
        assert browser.get(team_url).status_code == 403
        access.set_status(admin, actor.user_id, 'disabled')
        assert browser.head(url).status_code == 403


def test_organization_download_storage_failure_is_safe_and_uncached(pg_access, caplog):
    access = pg_access.service
    admin = administrator(pg_access)
    cookie = access.sign_in(identity('organization-unavailable'))
    actor = access.actor(cookie)
    access.set_status(admin, actor.user_id, 'active')
    access.grant(admin, actor.user_id, 'business_admin', {'kind': 'all'})

    def export(current, catalog):
        service = OrganizationService(PostgresOrganizationGateway(
            pg_access.gateway.database, pg_access.gateway.signer.key,
            access=BusinessAccess(current, access.policy)))
        return service.export_csv(catalog)

    routes = DownloadRoutes(access, lambda actor, project: '', export_organization=export)
    with TestClient(Starlette(routes=routes.routes())) as browser:
        browser.cookies.set('eppm_session', cookie)
        pg_access.gateway.database.close()
        response = browser.get('/downloads/organization/employees.csv')
        assert response.status_code == 503
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['error']['code'] == 'download_failed'
        assert cookie not in response.text + caplog.text
        assert pg_access.setup.runtime_url not in response.text + caplog.text
