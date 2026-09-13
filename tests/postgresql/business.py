"""Real PostgreSQL counterpart of the scoped business regression fixture."""

import secrets

import psycopg
from psycopg import sql
import pytest

from app.application.services.access import AccessService, AuthorizationPolicy, DeploymentAccessService, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import VerifiedIdentity
from app.infrastructure.postgresql.access import PostgresAccessGateway, PostgresDeploymentAccessGateway
from app.infrastructure.postgresql.authorization import configure_signing_key
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.seed_catalog import ensure_reference_catalog
from app.runtime import RuntimeResources


@pytest.fixture
def business(pg_database, database):
    """Authenticate real accounts and inject one restricted native process pool."""
    key = secrets.token_bytes(32)
    configure_signing_key(pg_database.operator_url, key.hex())
    path = RuntimeResources(database, key)
    with psycopg.connect(pg_database.operator_url) as conn:
        ensure_reference_catalog(conn)
        conn.execute("INSERT INTO eppm.project(id,name) VALUES(1,'Visible'),(2,'Hidden')")
        conn.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date) VALUES(10,1,'Visible task','2026-01-01','2026-01-05'),(20,2,'Hidden task','2026-01-01','2026-01-05')")
        conn.execute("INSERT INTO eppm.task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(10,20,'FS',0)")
        conn.execute("UPDATE eppm.project_task SET predecessor_id=20 WHERE id=10")
        conn.execute("INSERT INTO eppm.schema_parameters(param_id,param_name,param_type) VALUES('DEPT','Department','ENUM')")
        conn.execute("INSERT INTO eppm.schema_param_options(param_id,option_value) VALUES('DEPT','Finance'),('DEPT','Delivery')")
        conn.execute("INSERT INTO eppm.project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance')")
        conn.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES(1,'Reference pool',3)")
        conn.execute("INSERT INTO eppm.resource_pool_assignment(id,pool_id,project_id,task_id,fte_assigned) VALUES(1,1,1,10,1),(2,1,2,20,2)")
        for table in ("project", "project_task", "resource_pool", "resource_pool_assignment"):
            conn.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s,'id'),(SELECT max(id) FROM eppm.{}))").format(sql.Identifier(table)), ("eppm." + table,))
    policy = AuthorizationPolicy(lambda: 1000, SessionLimits())
    service = AccessService(PostgresAccessGateway(database, key, policy), policy, "https://provider.example.test", lambda: secrets.token_urlsafe(32))

    def login(subject: str):
        return service.actor(service.sign_in(VerifiedIdentity(service.issuer, subject, "", subject, 1000, 100000, True)))

    admin, editor = login("admin"), login("editor")
    DeploymentAccessService(PostgresDeploymentAccessGateway(OperatorDatabase(pg_database.operator_url)), lambda: 1000, "test", lambda: secrets.token_urlsafe(16)).bootstrap(admin.user_id)
    service.set_status(admin, editor.user_id, "active")
    service.grant(admin, editor.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    service.grant(admin, admin.user_id, "business_admin", {"kind": "all"})
    return path, service, admin, BusinessAccess(editor, policy), BusinessAccess(admin, policy)
