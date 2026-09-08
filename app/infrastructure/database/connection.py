"""Database connection management for SQLite."""

import sqlite3
from typing import Optional

from app.shared.config import config
from app.shared.logging import get_logger

logger = get_logger(__name__)


def get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates and returns a SQLite connection with foreign keys enabled.

    Args:
        db_path: Filepath to the SQLite database. If None, uses default from config.

    Returns:
        sqlite3.Connection: Connected SQLite database object.
    """
    target_path = db_path if db_path is not None else config.db_path
    conn = sqlite3.connect(target_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
