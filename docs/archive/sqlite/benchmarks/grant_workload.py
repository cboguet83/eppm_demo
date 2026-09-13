"""Grant distinct load users through the preserved SQLite application's services."""

import json
import os

from app.security import create_access_service
from app.shared.config import config
from app.shared.config.authentication import AuthenticationConfig

access = create_access_service(config.db_path, AuthenticationConfig.from_environment(os.environ))
actor = access.actor(os.environ["LOAD_ADMIN_COOKIE"])
accounts = json.loads(os.environ["LOAD_ACCOUNT_ROLES"])
for user_id, role in accounts:
    assert role in {"project_editor", "project_viewer"}
    access.set_status(actor, user_id, "active")
    access.grant(actor, user_id, role, {"kind": "all"})
print(json.dumps({"granted": len(accounts)}))
