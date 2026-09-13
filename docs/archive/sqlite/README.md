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

## Hierarchy test mapping

`tests/test_hierarchy_types.py` here preserves the original SQLite suite. The
active `tests/postgresql/test_hierarchy_types.py` retains all catalog validation,
labels, optional team/pool/group assignments and Settings authorization checks.
The old SQLite column-add upgrade is replaced by native reference-install
rollback/retry and migration re-entry checks against existing entities. Native
foreign-key and stable-code constraints are exercised directly. PostgreSQL
migration DDL atomicity remains covered in `test_foundation.py`.

The existing hierarchy Settings/dialog and browser workflows moved to
`tests/postgresql/test_hierarchy_ui.py` and `test_hierarchy_browser.py`, using
real native services and sessions. The seven editable reference values are
installed explicitly by parent test setup, never by a rendering application.

## Project-template test mapping

`tests/test_project_types.py` preserves the unchanged original module. Active
`tests/postgresql/test_project_type_workflows.py` retains its six template/value
workflows and verifies explicit operator reentry preserves user defaults,
applicability and a deliberately empty generated workload. The UI draft and
all-property-widget workflows are retained in `test_project_type_views.py`.

| Historical behavior | Active PostgreSQL evidence |
| --- | --- |
| All/selected/future types, required inheritance, defaults, inactive values, typed empty values and deletion guards | `test_project_type_workflows.py`, `test_project_types.py`, `test_project_type_contracts.py` |
| Seed counts, schedule bounds, custom catalog append and deleted high identities | `test_bulk_seed.py`: native bounds, custom-template/sequence-gap and append tests |
| Deterministic generated records | `test_bulk_seed_golden.py`: independent baseline hashes for projects, properties, selections, tasks and dependencies |
| Project-only and full resets, retained references and valid regenerated projects | `test_seed_projects_reset.py`, `test_maintenance_defaults.py`, `test_seed_catalog.py` |
| Restorable pre-operation backup and operator reentry | `test_bulk_seed.py`: archive/restore/append test; `test_maintenance_defaults.py`: complete demo and catalog tests |
| Migration atomicity, reentry and checksums | `test_foundation.py`: native migration, failed-DDL rollback and competing-runner tests |

The old SQLite JSON-column conversion, `.before-project-types.bak` file and
pre-existing orphan-reporting tests describe retired SQLite upgrades. The fresh
PostgreSQL database does not import those records. Its migration rollback and
native foreign-key enforcement are tested directly. Native resets deliberately
retain identity high-water marks so old grants cannot attach to reused project
IDs; deterministic seed comparisons therefore use independently initialized
fixtures, not reset-and-reuse of historical identifiers.

This is an incremental archive. Other legacy test and tool ports, archival of
the old runtime itself, full application coverage and final performance/recovery
acceptance remain pending.

## Project experience test mapping

`tests/test_project_experience.py` preserves the original SQLite module unchanged.
Its active PostgreSQL counterpart retains employee phone fields, contact
reassignment, alias translations and constraints, property tabs, confirmation
dialogs, component event validation and component registration. The native seed
check runs explicit operator seeding with an actual pre-operation archive.

The retired SQLite landline-column upgrade and translation-table DDL failure
describe an old database conversion that the fresh PostgreSQL deployment does
not perform. Native migration reentry preserves existing employee phones and
aliases in `tests/postgresql/test_project_experience.py`; checksummed migration
reentry and atomic DDL rollback across all pending files are covered by
`test_migrations_initialize_once_and_runtime_cannot_modify_the_ledger` and
`test_failed_migrations_rollback_schema_and_all_prior_pending_files` in
`tests/postgresql/test_foundation.py`.

## Project links and menu test mapping

`tests/test_project_ui_updates.py` preserves the unchanged original module.
Its active native counterpart retains unrestricted link counts, scoped edits,
URL validation, inspection-only links, pool popup fields, CSV context-menu
actions and the shared menu style. Native migration reentry preserves links;
real PostgreSQL constraints reject blank aliases and the backed-up operator
reset removes links. The retired SQLite index-collision migration test maps to
the actual pending-DDL rollback and ledger tests in `test_foundation.py`, which
are run alongside the ported workflow suite.
