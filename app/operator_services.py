"""Explicit PostgreSQL deployment composition, separate from runtime actors."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from secrets import token_urlsafe
import socket
from time import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.application.services.access import DeploymentAccessService
    from app.application.services.maintenance import MaintenanceService
    from app.infrastructure.postgresql.backup import PostgresTools


def create_maintenance_service(
    operator_url: str | None = None, *, backup_directory: Path | None = None,
    archive_tools: PostgresTools | None = None,
) -> MaintenanceService:
    """Compose backed-up maintenance with explicit operator credentials.

    The operator environment is the only default connection source. There is
    no fallback to runtime credentials or a database file. Construction does
    not connect; mutation commands create their archive before database writes.
    """
    from app.application.services.maintenance import MaintenanceService
    from app.infrastructure.postgresql.maintenance_gateway import PostgresMaintenanceGateway

    url = os.environ.get('DATABASE_OPERATOR_URL', '') if operator_url is None else operator_url
    directory = backup_directory if backup_directory is not None else Path(
        os.environ.get('DATABASE_BACKUP_DIRECTORY', '.local/backups'),
    )
    return MaintenanceService(PostgresMaintenanceGateway(url, directory, archive_tools=archive_tools))


def create_deployment_access_service(operator_url: str | None = None) -> DeploymentAccessService:
    """Compose audited account bootstrap/recovery without a business-actor bypass."""
    from app.application.services.access import DeploymentAccessService
    from app.infrastructure.postgresql.access import PostgresDeploymentAccessGateway
    from app.infrastructure.postgresql.pool import OperatorDatabase

    url = os.environ.get('DATABASE_OPERATOR_URL', '') if operator_url is None else operator_url
    return DeploymentAccessService(
        PostgresDeploymentAccessGateway(OperatorDatabase(url)), lambda: int(time()),
        f'{getpass.getuser()}@{socket.gethostname()}', lambda: token_urlsafe(16),
    )
