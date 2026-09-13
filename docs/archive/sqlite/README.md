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

## Allocation generation test mapping

`tests/test_allocation_generation.py` preserves the unchanged original module.
The active root module retains pure rounding, request validation and capacity
period boundaries, using the native capacity-period helper. Its former SQLite
integration cases are covered in `tests/postgresql/test_allocation_seed.py`:

| Historical behavior | Native evidence |
| --- | --- |
| Read-only preview, requested daily mix, one backup and retained project/task data | Preview/apply/archive-restore test and actor-bound capacity comparison |
| Stale preview and writer-time fingerprint checks | Reviewed-source-change test checks both the service and typed plan application |
| Impossible mixes before writes or backup | Invalid-mix test and three unfulfillable-source cases |
| Failed clear, preserved demand, retained pool/mapping rows and repeated clear | Failed-clear and successful-clear membership test with actual dump archives |
| Foreign-key failure restores earlier deletes | Native failed plan test verifies original demand and staffing |
| Zero mappings retain identity; empty pools receive staff and fallback capacity | Zero-percent mapping and empty-pool tests |
| Deterministic report and mutation parity | `test_allocation_seed_golden.py` compares independent baseline hashes |

PostgreSQL applies typed frozen plans inside the complete operator callback.
The retired generic SQLite SQL-list executor and database-wide writer lock are
not part of that native contract; actual serializable replay and a single
pre-operation archive are verified directly.

## Application shell test mapping

`tests/test_layered_shell.py` retains the original SQLite module unchanged.
The active root tests now exercise routing, deep links, language selection,
fragment reruns and launcher validation without storage. Native tests in
`tests/postgresql/test_layered_shell.py` verify actual page reruns preserve
project data and Settings deep links retain their selected section. A fresh
interpreter renders Dashboard, Portfolio, Planning, Settings and Finance using
only restricted PostgreSQL credentials and rejects indirect legacy storage
imports. The existing native operator-command test covers explicit CLI seeding,
archive creation, unchanged data after archive failure and safe exit status;
the UI never calls that operator path.

## Dashboard test mapping

`tests/test_dashboard.py` preserves the unchanged SQLite module. The active root
suite retains pure money rounding, filter, hierarchy and quarterly capacity
calculations. `tests/postgresql/test_dashboard_workflows.py` retains catalog
facets, scoped reports and issues, competing hidden demand, finance cancellation,
calendar-day invalidation, drillthrough and safe actual pool-outage behavior.
`tests/postgresql/test_dashboard_ui.py` retains all ten UI cases with a native
scoped editor, separate administrators and real persistent budget plans.

The retired dashboard migration's one-time SQLite session revocation is not
performed when starting a fresh PostgreSQL database. Native migration reentry
instead verifies preservation of event contents, stable blocker codes and both
active and revoked current sessions. SQLite data and upgrade source remain
historical artifacts; no native import or compatibility path is introduced.

## Layered maintenance test mapping

`tests/test_layered_maintenance.py` retains the original SQLite module unchanged.
Its native evidence is provided by these real PostgreSQL suites:

| Historical behavior | Native evidence |
| --- | --- |
| Explicit startup, default counts, idempotence, forced generation | `test_maintenance_gateway.py` verifies fresh migration, catalog preservation and one archive per mutation |
| Invalid counts/types and malformed scenario options before storage | Expanded gateway validation cases reject every original malformed input before any connection or archive |
| Recoverable seed/reset archives and preserved budgets | `test_maintenance_defaults.py` and `test_maintenance_write.py` restore actual dumps into separate databases |
| Project/full reset counts, constraints, references and accounts | `test_seed_projects_reset.py` checks cascades, retained finance/accounts and monotonic identities |
| Reset failure rolls back earlier child deletions | Gateway trigger-rejection case retains the complete source fingerprint, counts and pre-operation dump |
| Backup failure or unavailable storage | Native write/archive failure tests and an actual refused operator connection verify safe errors and unchanged sources |
| Invalid schema is never interpreted as an empty database | Gateway tests reject unmigrated and malformed native schemas without changing sentinel data or creating archives |
| Pool preview/apply/idempotence and CLI options | Native default-maintenance and operator-command tests exercise the real generators, argument parsers and archive policy |

The old empty-file initialization case becomes explicit migration of a fresh
native database. No SQLite file-opening behavior remains in the supported tools.
## HTTP and session transport test mapping

The original `test_session_transport.py`, `test_planning_http.py` and
`test_portfolio_http.py` are retained unchanged under this archive's `tests/`.
Their database-backed cases now run in `tests/postgresql/`; root session tests
retain pure CSV boundary validation. Native fixtures use actual PostgreSQL
sessions, restricted process resources and a separate operator bootstrap.

The port preserves live WebSocket revocation, spoofed-header rejection, origin
checks, atomic logout/audit failure, bounded requests, scoped task/dependency
hydration, scoped allocation badges, session-activity neutrality and rejection
of responses whose data or permissions changed during calculation. The former
SQLite progress-handler assertion now measures the actual native query with
`EXPLAIN (ANALYZE, BUFFERS)`, including row scan bounds after 5,000 unrelated
tasks and dependencies are inserted.
## WBS test mapping

`tests/test_wbs.py` retains the unchanged SQLite module. Its root replacement
keeps pure code/percentage validation and a storage-independent save helper.
The native `tests/postgresql/test_wbs.py` and `test_wbs_ui.py` cover catalog
authorization, hidden-project capacity, atomic project/link/share saves,
competing claims, both backed-up reset modes, migration reentry, Settings CRUD,
custom project forms, integer row editing and retained drafts. Direct native
SQL verifies caps, references and old/new owners; hidden UPDATE/DELETE targets
affect zero rows under PostgreSQL RLS instead of exposing an inaccessible row.

The fractional-SQL regression discovered PostgreSQL's implicit integer rounding.
Migration 0021 retains exact numeric input until whole-percentage/range checks
pass. Application and dashboard reads explicitly retain integer DTO values.
Additional native tests cover fractional/nonfinite INSERT and UPDATE, upgrade
from the previous applied schema and exact preservation of 0/35/100% shares.
## Shared popup test mapping

The unchanged original `tests/test_dialog.py` is retained here. Root tests keep
storage-independent completion and wrapper-convention checks. Native popup
tests check fresh permissions on fragment interactions, use actual project-ID
previews, and dispatch Cancel for nine creation dialogs. A repeatable-read
fingerprint of every native table and sequence verifies that cancellation
changes no persisted state. Project-detail preparation and reference-cache
tests also moved to native fixtures and retain their read/order bounds.
## Authentication state and HTTP test mapping

`app/infrastructure/authentication/state.py` preserves the retired SQLite Authlib
state adapter. Active runtime code uses `PostgresOidcState`; its signatures,
bounded expiry, atomic consumption and worker-thread database operations are
tested in `tests/postgresql/test_oidc_state.py`. The original
`tests/test_oidc_authentication.py` is archived unchanged; its complete HTTP/JOSE
contracts now run in `tests/postgresql/test_oidc_authentication.py`, with additional
native persistence and audit checks in `test_oidc_http.py`. Pure login-destination
validation remains in the root tests. No old SQLite authentication data is imported.
## Database, seed and historical schema-upgrade mapping

The original database, pool-scenario, seed-backup and legacy-schema-upgrade test
modules are archived unchanged. PostgreSQL starts fresh under ADR 0024; renaming
old SQLite tables, converting prefixed SQLite IDs and adding columns to old
SQLite employee tables remain historical upgrade mechanics, not an import path.

| Retained contract | Active PostgreSQL evidence |
| --- | --- |
| Core tables, employee availability default, explicit migration reentry | `test_database_contracts.py`, `test_foundation.py`, `test_integrity.py` |
| Independent parameter names, all enum choices, required defaults, aliases and effective project templates | `test_database_contracts.py` |
| Default counts, idempotent seeding and forced reset | `test_database_contracts.py`, `test_maintenance_defaults.py`, `test_seed_projects_reset.py` |
| All 25 units/four staffing categories, real employee capacity, two allocations per pool, five units per service and preserved project data | `test_pool_seed_scenarios.py` |
| Empty/task-free workloads and additive scenario reentry | `test_pool_seed_scenarios.py`, `test_bulk_seed.py` |
| One pre-mutation native archive, append preservation, actual restore and failure before mutation | `test_maintenance_write.py`, `test_bulk_seed.py`, `test_maintenance_defaults.py` |

Test paths above are relative to `tests/postgresql/`. A migrated PostgreSQL
database already contains schema/metadata, so its first explicit seed also gets
a native archive. SQLite's initial nonexistent-file case required none. Runtime
requests neither install schema nor initialize demo data in the new architecture.
## Complete access-security contract mapping

The unchanged `tests/test_access_security.py` is retained here. Its database-backed
contracts now run in `tests/postgresql/test_access_security_contracts.py`, with
native actor-bound callbacks for permission evaluation and separate operator
connections for independent persisted-state inspection. Scope/session-configuration
validators remain in the root test module without storage imports.

The port retains structured private-data-free logs, damaged-grant isolation,
cookie rotation, pending/disabled last-admin protection, malformed and missing
references, deleted/reused identifiers, reset preservation, access explanations,
issuer/subject separation, current-value scopes, immediate revocation, idle expiry
beyond token/eight-hour boundaries, shared-cookie activity, competing bootstrap,
mixed disable/revoke races, mandatory recovery audit rollback and verified MFA.
Native audit UPDATE/DELETE rejection uses real PostgreSQL constraints and savepoints.
Reset checks use explicit backed-up native maintenance, with native foreign-key
integrity covered by the existing integrity suites.
