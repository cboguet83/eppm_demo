"""Temporary SQLite fixture for the remaining unported regression modules."""

from contextlib import closing
from pathlib import Path
import secrets

import pytest

from app.application.services.access import AccessService, AuthorizationPolicy, DeploymentAccessService, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import VerifiedIdentity
from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.access import SqliteAccessGateway


@pytest.fixture
def business(tmp_path: Path):
    path = str(tmp_path / "business.db")
    init_db(path)
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO project(id,name) VALUES(1,'Visible'),(2,'Hidden')")
        conn.execute("INSERT INTO project_task(id,project_id,task_name,start_date,end_date) VALUES(10,1,'Visible task','2026-01-01','2026-01-05'),(20,2,'Hidden task','2026-01-01','2026-01-05')")
        conn.execute("INSERT INTO task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES(10,20,'FS',0)")
        conn.execute("UPDATE project_task SET predecessor_id=20 WHERE id=10")
        conn.execute("INSERT INTO schema_parameters(param_id,param_name,param_type) VALUES('DEPT','Department','ENUM')")
        conn.execute("INSERT INTO schema_param_options(param_id,option_value) VALUES('DEPT','Finance'),('DEPT','Delivery')")
        conn.execute("INSERT INTO project_property_value(project_id,param_id,kind,text_value) VALUES(1,'DEPT','text','Finance')")
        conn.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES(1,'Reference pool',3)")
        conn.execute("INSERT INTO resource_pool_assignment(id,pool_id,project_id,task_id,fte_assigned) VALUES(1,1,1,10,1),(2,1,2,20,2)")
    policy = AuthorizationPolicy(lambda: 1000, SessionLimits())
    service = AccessService(SqliteAccessGateway(path), policy, "https://provider.example.test", lambda: secrets.token_urlsafe(32))

    def login(subject: str):
        return service.actor(service.sign_in(VerifiedIdentity(service.issuer, subject, "", subject, 1000, 100000, True)))

    admin, editor = login("admin"), login("editor")
    DeploymentAccessService(service.gateway, lambda: 1000, "test", lambda: secrets.token_urlsafe(16)).bootstrap(admin.user_id)
    service.set_status(admin, editor.user_id, "active")
    service.grant(admin, editor.user_id, "project_editor", {"kind": "projects", "project_ids": [1]})
    service.grant(admin, admin.user_id, "business_admin", {"kind": "all"})
    return path, service, admin, BusinessAccess(editor, policy), BusinessAccess(admin, policy)
