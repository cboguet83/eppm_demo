"""Finance downloads use actual PostgreSQL sessions and exact native amounts."""

from datetime import date

from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.application.services.business_access import BusinessAccess
from app.application.services.finance import FinanceService
from app.infrastructure.authentication.finance import FinanceDownloadRoutes
from app.infrastructure.postgresql.finance import PostgresFinanceGateway
from tests.postgresql.test_access_service import administrator, identity, pg_access as pg_access


def test_native_finance_download_rechecks_active_session_on_every_get_and_head(pg_access):
    access = pg_access.service
    admin = administrator(pg_access)
    access.grant(admin, admin.user_id, 'finance_editor', {'kind': 'all'})
    def finance(actor):
        gateway = PostgresFinanceGateway(pg_access.gateway.database, pg_access.gateway.signer.key,
                                        access=BusinessAccess(actor, access.policy))
        return FinanceService(gateway, lambda: date(2026, 6, 1))
    first = finance(admin).save([{'code': 'A', 'amounts': {'2026': '92233720368547758.07'}}],
                                base_id=None, name='Exact', status='Approved', year=2026)
    cookie = access.sign_in(identity('download-reader'))
    reader = access.actor(cookie)
    access.set_status(admin, reader.user_id, 'active')
    routes = FinanceDownloadRoutes(access, lambda actor, snapshot_id: finance(actor).export(snapshot_id))
    with TestClient(Starlette(routes=routes.routes())) as client:
        url = f'/downloads/finance/{first}/budget.csv'
        assert client.get(url).status_code == 403
        client.cookies.set('eppm_session', cookie)
        response = client.get(url)
        assert response.status_code == 200 and '92233720368547758.07' in response.text
        assert response.text.startswith('\ufeffwbs_code;description;2026')
        assert response.headers['cache-control'] == 'no-store' and 'attachment' in response.headers['content-disposition']
        assert client.head(url).status_code == 200
        assert client.get('/downloads/finance/999/budget.csv').status_code == 403
        access.set_status(admin, reader.user_id, 'disabled')
        assert client.get(url).status_code == client.head(url).status_code == 403


def test_finance_download_returns_safe_uncached_failure_when_native_storage_is_unavailable(pg_access, caplog):
    """An actual unavailable pool must not expose connection details in HTTP or logs."""
    access = pg_access.service
    admin = administrator(pg_access)
    cookie = access.sign_in(identity('download-unavailable'))
    access.set_status(admin, access.actor(cookie).user_id, 'active')

    def export(actor, snapshot_id):
        gateway = PostgresFinanceGateway(pg_access.gateway.database, pg_access.gateway.signer.key,
                                        access=BusinessAccess(actor, access.policy))
        return FinanceService(gateway, lambda: date(2026, 6, 1)).export(snapshot_id)

    with TestClient(Starlette(routes=FinanceDownloadRoutes(access, export).routes())) as client:
        client.cookies.set('eppm_session', cookie)
        pg_access.gateway.database.close()
        response = client.get('/downloads/finance/1/budget.csv')
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'download_failed'
        assert response.headers['cache-control'] == 'no-store'
        assert 'postgresql' not in response.text.lower()
        assert pg_access.setup.runtime_url not in caplog.text
