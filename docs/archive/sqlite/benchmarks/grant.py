"""Grant benchmark access through the unchanged SQLite image's real services."""

import json
import os

from app.security import create_access_service
from app.shared.config import config
from app.shared.config.authentication import AuthenticationConfig

access = create_access_service(config.db_path, AuthenticationConfig.from_environment(os.environ))
actor = access.actor(os.environ["LOAD_ADMIN_COOKIE"])
access.grant(actor, actor.user_id, "business_admin", {"kind": "all"})
viewer = int(os.environ["LOAD_VIEWER_ID"])
access.set_status(actor, viewer, "active")
access.grant(actor, viewer, "project_viewer", {"kind": "all"})
print(json.dumps({"granted": True}))
