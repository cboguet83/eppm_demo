# SQLite implementation history

These files preserve the pre-cutover implementation and tests as historical
source. They are outside the application packages and active test paths. They
are not a supported runtime, a compatibility layer or a SQLite import tool.
The migration plan explicitly retires SQLite upgrade tests after their business
invariants have real PostgreSQL coverage. Existing database files and backups
remain separate and are not changed by this source archive.

## Finance test mapping

`tests/test_finance.py` here is the unchanged original test module. The active
`tests/test_finance.py` retains its six database-independent test functions,
including all parametrized parsing, CSV, amount, blank/zero and size limits.

| Historical behavior | Active PostgreSQL evidence |
| --- | --- |
| Numbered plans, old base selection, cancellation and audit | `tests/postgresql/test_finance.py`: numbered history and concurrent cancellation tests |
| Year rollover, imports and historical zero | `tests/postgresql/test_finance.py`: rollover/CSV replacement test |
| Active readers, independent finance editor, revoked/disabled access | `tests/postgresql/test_finance.py`: active-reader and retry-revocation tests |
| Concurrent versions, validation and transaction rollback | `tests/postgresql/test_finance.py`: concurrent saves, invalid saves, late failures and replay tests |
| Sealed rows, amounts and cancellation constraints | `tests/postgresql/test_integrity.py`: sealed-finance and cancellation tests; native Finance constraint tests |
| Idempotent migration, grants and trigger retention | `tests/postgresql/test_finance.py`: migration re-entry test |
| Upgrade ledger, rollback, retry and competing migration runners | `tests/postgresql/test_foundation.py`: real native migration tests |
| Grant scopes invalidated by project removal | `tests/postgresql/test_business_security.py` and `test_scope_resolution.py` |
| Exact authenticated CSV, revoked session, safe storage errors | `tests/postgresql/test_finance_http.py` and `test_finance_browser.py` |
| Finance preserved by full reset | `tests/postgresql/test_seed_projects_reset.py`: full reset retention test |
| Finance changes leave business caches valid | `tests/postgresql/test_finance.py`: independent cache revision test |

SQLite `PRAGMA`, `sqlite_sequence`, table-rebuild and `INSERT OR REPLACE` syntax
are historical upgrade mechanics, not PostgreSQL runtime contracts. Native tests
exercise corresponding identity, migration atomicity, access and immutable
history behavior directly. No SQLite data, grants or finance history are imported.

This is an incremental archive. Other legacy test and tool ports, archival of
the old runtime itself, full application coverage and final performance/recovery
acceptance remain pending.
