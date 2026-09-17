"""Pool CSV attachments require a current authorized browser session."""

from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.application.services.business_access import BusinessAccess
from app.application.services.resource_pools import ResourcePoolService
from app.application.services.resource_pool_csv import parse_pools
from app.domain.resources.models import ResourcePool
from app.infrastructure.authentication.downloads import DownloadRoutes
from app.infrastructure.postgresql.resource_pools import PostgresResourcePoolGateway
from tests.postgresql.test_access_service import administrator, identity, pg_access


def test_pool_downloads_are_csv_and_recheck_visibility_permissions_and_sessions(pg_access):
    access = pg_access.service
    admin = administrator(pg_access)
    cookie = access.sign_in(identity('pool-export'))
    actor = access.actor(cookie)
    access.set_status(admin, actor.user_id, 'active')

    def pools(current):
        return ResourcePoolService(PostgresResourcePoolGateway(
            pg_access.gateway.database, pg_access.gateway.signer.key,
            access=BusinessAccess(current, access.policy)))

    routes = DownloadRoutes(access, lambda actor, project: '', export_pools=lambda actor, deleted, template:
                           pools(actor).export_csv(include_deleted=deleted, template=template))
    with TestClient(Starlette(routes=routes.routes())) as browser:
        url = '/downloads/resource-pools/pools.csv'
        template_url = '/downloads/resource-pools/template.csv'
        assert browser.get(url).status_code == 403
        browser.cookies.set('eppm_session', cookie)
        assert browser.get(url).status_code == 403
        assert browser.get(template_url).status_code == 403
        grant = access.grant(admin, actor.user_id, 'business_admin', {'kind': 'all'})
        pools(actor).create_pool(ResourcePool('Visible, "quoted"', capacity_fte=2.5))
        hidden = pools(actor).create_pool(ResourcePool('Hidden'))
        pools(actor).delete_pool(hidden)
        response = browser.get(url)
        assert response.status_code == 200
        assert response.headers['content-type'] == 'text/csv; charset=utf-8'
        assert response.headers['content-disposition'] == 'attachment; filename="resource_pools.csv"'
        assert response.headers['cache-control'] == 'no-store'
        assert response.content.startswith(b'\xef\xbb\xbfpool_id,name,')
        assert [pool.name for pool in parse_pools(response.content)] == ['Visible, "quoted"']
        assert len(parse_pools(browser.get(url + '?include_deleted=true').content)) == 2
        assert browser.get(template_url).text.lstrip('\ufeff').count('\n') == 1
        assert browser.get(url + '?include_deleted=invalid').status_code == 403
        assert browser.get('/downloads/resource-pools/unknown.csv').status_code == 403
        access.revoke(admin, grant)
        assert browser.get(url).status_code == 403
        access.set_status(admin, actor.user_id, 'disabled')
        assert browser.head(template_url).status_code == 403
