"""Consistent SQLite snapshots shared by every seed entry point."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from inspect import signature
from pathlib import Path

from app.shared.config import config
from app.shared.logging import get_logger

_ACTIVE = ContextVar("seed_backup_active", default=False)
logger = get_logger(__name__)


def backup_database(
    db_path: str | Path | None = None,
    *,
    reason: str = "seed",
    source_path: str | Path | None = None,
) -> Path | None:
    """Back up existing data with SQLite's online backup API, including WAL data.

    A database in a data directory uses data/backups. Standalone database files
    use a data/backups directory next to the database (also isolates test DBs).
    Backup errors deliberately abort the caller before seeding can start.
    """
    target = Path(db_path or config.db_path).resolve()
    source = Path(source_path).resolve() if source_path else target
    if not source.exists() or source.stat().st_size == 0:
        return None
    directory = (
        target.parent if target.parent.name == "data" else target.parent / "data"
    ) / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / f"{target.stem}-before-{reason}-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(backup)) as destination:
            original.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"Backup integrity check failed: {backup}")
    logger.info("Database backup created: %s", backup)
    return backup


def backup_before_seed[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """One backup for a seed operation, even when it calls another seeder."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        if _ACTIVE.get():
            return function(*args, **kwargs)
        bound = signature(function).bind(*args, **kwargs)
        backup_database(bound.arguments.get("db_path"))
        token = _ACTIVE.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _ACTIVE.reset(token)

    return wrapped
