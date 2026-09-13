"""Inspect only the disposable copy inside the preserved SQLite baseline image."""

from contextlib import closing
import json
import sqlite3

from app.shared.config import config

tables = (
    "project", "project_task", "task_dependencies", "resource_pool",
    "resource_pool_group", "resource_pool_assignment", "app_user",
)
with closing(sqlite3.connect(config.db_path)) as connection, connection:
    assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    connection.execute("ANALYZE")
    counts = {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0] for name in tables}
print(json.dumps(counts))
