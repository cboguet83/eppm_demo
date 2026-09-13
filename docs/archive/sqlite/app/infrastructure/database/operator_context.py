"""Trusted local-operator identity for deployment-only database workflows."""

import getpass
import socket
import time
from uuid import uuid4

from app.application.services.access import AuthorizationPolicy, SessionLimits
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import DeploymentActor


def deployment_access() -> BusinessAccess:
    """Identify the local operator; never use this from a running user workflow."""
    return BusinessAccess(
        DeploymentActor(f"{getpass.getuser()}@{socket.gethostname()}", uuid4().hex),
        AuthorizationPolicy(lambda: int(time.time()), SessionLimits()),
    )
