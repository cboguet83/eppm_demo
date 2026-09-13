"""Client timing subclasses used exclusively in the preserved SQLite image.

SQL execution includes SQLite's native lock waiting; that library does not expose
a separate lock-wait counter. Its connection and transaction behavior is retained.
"""

import sqlite3
from typing import Any


def install(timed: Any) -> None:
    """Keep the native factory's arguments, results and errors while adding timers."""
    class Cursor(sqlite3.Cursor):
        pass

    class Connection(sqlite3.Connection):
        def cursor(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
            if not args:
                kwargs.setdefault("factory", Cursor)
            return super().cursor(*args, **kwargs)

        def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
            return self.cursor().execute(*args, **kwargs)

        def executemany(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
            return self.cursor().executemany(*args, **kwargs)

        def executescript(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
            return self.cursor().executescript(*args, **kwargs)

    for cls, methods in ((Cursor, ("execute", "executemany", "executescript", "fetchone", "fetchmany", "fetchall")),
                         (Connection, ("commit", "rollback", "__exit__"))):
        for method in methods:
            setattr(cls, method, timed("db_client_" + method, getattr(cls, method)))
    original = sqlite3.connect
    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        if len(args) < 6:
            kwargs.setdefault("factory", Connection)
        return original(*args, **kwargs)
    sqlite3.connect = timed("db_connect", connect)
