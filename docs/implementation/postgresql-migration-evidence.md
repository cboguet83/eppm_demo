# PostgreSQL migration implementation evidence

## Baseline and scope

- Plan: [agreed migration handoff](postgresql-migration-plan.md).
- Branch: `codex/postgresql-migration`.
- Starting commit: `f564a5b4b49c237902415754c61fe9e77f07f7bc` (accepted main).
- Working tree was clean when the branch was created/resumed.
- Decision: [ADR 0024](../decisions/0024-postgresql-runtime.md).
- Existing features include optional hierarchy types and the accepted Finance
  edit controls, including removal of Reload latest.
- No planning-revision or stale-form feature is part of this migration.

## Host recorded on 2026-09-12

- Windows host; Python 3.14.6 in the project virtual environment.
- Docker Engine 29.7.2, 8 CPUs, 16,529,354,752 bytes available to Docker.
- Existing `eppm_demo-app-1` and `eppm_demo-keycloak-1` remain separate from test data.
- Detailed container limits and benchmark placement will be recorded with runs.

## Checks

| Check | Command / evidence | Result |
| --- | --- | --- |
| Baseline full Python suite | `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --cov=app --cov-report=term --cov-report=xml:.local/postgresql-baseline-coverage.xml --junitxml=.local/postgresql-baseline-tests.xml` | 1,496 passed, 4 failed, 1 skipped, 14 subtests; 422.47 seconds. 12,526 statements, 160 missed (98.72%, displayed as 99%). Log: `.local/postgresql-baseline-tests.log`. |
| Baseline Git state | `git status --short --branch`; `git rev-parse main origin/main codex/postgresql-migration` | Clean; all start at the baseline SHA above. |
| Hierarchy baseline repair | `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_hierarchy_ui.py tests/test_layered_organization_ui.py tests/test_layered_resource_pool_ui.py` | 20 passed in 13.92 seconds. Bind the unassigned label to the originating session, including a regression for a different caller locale. |
| PostgreSQL foundation | Explicit `.local/postgresql.env`, real isolated databases, `pytest tests/postgresql --cov=app.infrastructure.postgresql --cov=app.shared.config.database --cov-report=term-missing` | 46 passed in 6.78 seconds; 145/146 statements covered. Includes real serialization/deadlock races, timeout/shutdown, connection loss, pool reuse and exhaustion, migrations and operator checks. |
| SQLite archive | `backup_database('/app/data/ppm_mock.db', reason='postgresql-migration')`, run inside `eppm_demo-app-1` | Created `/app/data/backups/ppm_mock-before-postgresql-migration-20260912-165936-945621.db`; backup API verifies integrity. |
| PostgreSQL network | `socket.gethostbyname('postgres')`, run inside `eppm_demo-app-1` | Resolved `172.21.0.3` from the application's shared Keycloak network namespace. |

The baseline's four failures were all the unassigned hierarchy label being
reformatted in a different locale outside the Streamlit session. The small repair
preserves UI behavior and makes the existing regression suite reproducible.

## Milestones

| Milestone | State | Evidence / remaining work |
| --- | --- | --- |
| 1. Baseline and decisions | Baseline captured | ADR, full baseline test results, workload and service timings recorded. Browser load comparison remains an acceptance gate. |
| 2. PostgreSQL foundation | Additive foundation tested | Configuration, pool, migration runner, Compose, operator role provisioning and isolated tests implemented. Application lifecycle integration follows repository cutover. |
| 3. Schema and enforcement | In progress | Native baseline and permanent integrity triggers tested; RLS, trusted actor binding, protected-property audit, security transitions and cache storage remain. |
| 4. Core repositories | Pending | Organization, templates/schema, projects, tags, collaboration, Decimal budgets. |
| 5. Planning and caches | Pending | Current planning, dependencies, allocations, capacity, per-entity revisions and snapshot tests. |
| 6. Runtime cutover | Pending | Composition, authentication, operator tools, seeds, benchmarks, archive legacy migrations. |
| 7. Acceptance and documentation | Pending | Full regression/coverage, browser/load runs, backup/restore, deployment and C4 documentation. |

## Performance acceptance

Browser acceptance is not yet measured or accepted. Fixture: 10,001 projects, seed 42, existing task
bounds 0–15, representative dependencies and allocations. Compare SQLite and
PostgreSQL under equivalent recorded conditions. Run 40 readers and 10 editors
at approximately two-second intervals, three ten-minute measurements after
two-minute warm-ups. Report each scenario's browser-action-to-usable-result p95
separately, along with failures and database/pool/lock/server/rendering timings.

### SQLite service baseline

`scripts.benchmark_migration_sqlite` ran in the existing `eppm-demo:local` image
with isolated `.local/migration-baseline` storage and no CPU or memory override.
Linux Python 3.14.7, SQLite 3.46.1, rollback journal (`delete`). Generation took
26.545 seconds. The original generator's separate pool scenario seed is 20260908,
year 2026; preserve these explicit fixture settings for the equivalent comparison.
Actual counts include 10,001 projects, 73,929 tasks, 66,173 dependency links,
10,201 resource assignments, 103 pools, 31 pool groups, 258,022 property values
and 40,004 list items. Full counts and timings are in
[`benchmarks/sqlite-baseline.json`](benchmarks/sqlite-baseline.json).

| Single-operator service operation | Samples after warm-up | Median | p95 |
| --- | --- | --- | --- |
| Portfolio page, badges deferred | 100 | 71.490 ms | 116.086 ms |
| Visible tasks for 20 projects | 100 | 117.349 ms | 156.976 ms |
| Simple task progress save | 100 | 43.977 ms | 52.577 ms |

These timings include existing service authorization/storage work for a deployment
operator. They exclude OIDC, Streamlit and browser rendering and are not evidence
of the 50-authenticated-session browser target. The SQLite fixture remains
available for that comparison before its runtime is archived.

## Intermediate commits

- `1387f1a` — bind the optional hierarchy label to the originating locale;
  20 affected Streamlit tests passed, including the new regression.
- `00c5022` — additive PostgreSQL foundation, explicit operator setup, isolated
  real-database checks and recorded SQLite baseline; 46 PostgreSQL checks passed.
- `6aa5b38` — native business schema, permanent integrity triggers, schema
  inventory and CI configuration; 77 PostgreSQL and 7 layer-boundary checks passed.
- `28e66e0` — private scope resolution and categorical-reference lifetimes;
  112 PostgreSQL checks passed.
- `977c0fd` — signed actor binding, fixed permission mapping and pool role checks;
  159 PostgreSQL checks passed.

## Native schema and integrity

`0002_business_schema.sql` translates the current business/access/finance tables
with BIGINT identities, NUMERIC euro values, native booleans/dates and JSONB.
No business records, users or grants are imported. Runtime business privileges
remain absent pending permanent row-security policies. Cache storage is a
separate required redesign, not a translation of the global revision hotspot.

`0003_integrity.sql` preserves immutable finance and audit history, hierarchy
codes, pool-group cycle checks, inclusive employee-calendar nonoverlap, WBS totals,
assignment ownership and task date/progress validity. Runtime business writes
must be serializable; operator provisioning remains separate. Narrow advisory
locks and serializable retries protect concurrent calendar, WBS and group changes.
Functions have explicit search paths and no public execution privilege.

The native-schema run passed 76 PostgreSQL tests in 13.94 seconds with 147/148
runtime statements covered. The final inventory check brought the suite to
77 passing tests in 14.08 seconds. New checks exercised actual native types,
immutable records, constraints and concurrency through a nonowner connection.
These integrity fixtures temporarily grant business-table DML only within their
isolated databases; they are not a substitute for the pending RLS acceptance
suite. Schema-inventory parity covers every existing business table; lifecycle
and derived-cache replacements are accounted for explicitly.

`.github/workflows/tests.yml` now configures Python 3.14 and PostgreSQL 18.6,
generates distinct ephemeral test credentials, runs full pytest with a 95%
coverage gate, enables the authenticated browser fixture, and runs JavaScript
checks. It has not run on GitHub because this branch has not been published.

## Scope resolution

`0004_scope_resolution.sql` adds private native scope validation/resolution and
permanent categorical-reference registration, tombstoning and grant invalidation.
Its functions are not granted to runtime callers: arbitrary scope evaluation
must not become a way to enumerate hidden projects. The subsequent actor-bound
policies will use these helpers for persisted, permission-bearing grants.

The PostgreSQL suite passed 112 tests in 34.44 seconds, including 35 new checks
for domain/native structural-validation parity, duplicate reference normalization,
missing references, categorical intersections, value changes, retyping and
deletion/recreation. The original fixed-role mapping, trusted session binding,
row policies, protected-property audit and security transition enforcement still
need implementation and direct-database acceptance tests.

### Next implementation work

1. Add actor-bound permission projections and RLS without granting arbitrary
   scope resolution. Derive fixed role permissions from `ROLE_PERMISSIONS` and
   test database/application parity, including MFA and distinct read/edit scopes.
2. Protect old/new owners and indirect writes, mask hidden predecessor IDs and
   employee details, and require atomic audit. Preserve scope invalidation when
   internal triggers change assignments; avoid a user-settable bypass flag.
3. Bind trusted session references transaction-locally. Verify pooled reuse,
   expiration/revocation, bootstrap and last-administrator races. Synchronous
   access work must leave the ASGI loop at cutover.
4. Implement per-project/per-pool and shared/security cache revisions, then port
   repositories and complete callback replay through application services.
5. Complete all remaining milestones and acceptance gates in the agreed plan;
   the application still uses SQLite and the migration is not ready for adoption.

## Trusted actor binding

`0005_actor_authorization.sql` adds signed transaction-local context, session
validation and the fixed role/permission projection. The private signing key
and role mapping are protected by privileges and default-deny RLS. Only the
actor/permission interface is executable by runtime connections. Arbitrary
scope resolution remains private. Business-table RLS and atomic access changes
are still separate pending work.

The initial actor-binding run passed 158 PostgreSQL tests in 31.61 seconds.
It exercised actual runtime connections, HMAC forgery/replay, malformed signed
context, account/session validity, MFA, distinct read/edit scopes, permission
mapping parity, key rotation, and session/account/grant revocation locks.
Earlier revocation forces complete replay and reauthorization; later revocation
waits for the authorized writer. Reads do not extend authentication/activity.
The new migration also hardens all earlier helper search paths against temporary
object shadowing without changing their applied migration files.

Final validation passed 159 PostgreSQL tests in 31.64 seconds, including denial
of a login able to `SET ROLE` to a non-inherited BYPASSRLS role. The PostgreSQL
runtime/config subset covered 180/181 statements (99.45%); actor binding covered
all 33 statements. This subset measurement does not replace the full-codebase
95% acceptance gate. Commands and full output are retained in
`.local/postgresql-actor-final.log`.

## Business row security and audit

`0006_business_security.sql` installs RLS and permanent write guards on all 45
existing business tables. Scope filters apply before aggregate, page and join
results. Runtime users cannot read hidden predecessor columns; the permanent
task projection masks hidden endpoints, and dependency rows require both ends
to be visible. Raw employee contact/staffing records require shared-business
administration; the existing portfolio manager-label projection stays available.

Writes check old and new owners, including conflict targets and indirect task
references. Protected categorical/template mutations append audit with the
signed actor/correlation, and a failed audit insert rolls back the entire save.
No-op protected upserts remain allowed without audit noise. Task tags and
assignments are checked/deleted before the owner disappears, preserving safe
native cascades. Runtime pool reset also discards temporary tables, verified by
reusing the same backend for an administrator and a scoped reader.

Finance reads remain available to any valid active account, independently of
portfolio grants. Finance writes require the separate global capability and
persist trusted attribution. Its all-scope marker cannot enumerate project IDs
through permission helpers. Private scope evaluation remains unexposed.

The first combined RLS, PostgreSQL regression and layer-boundary run passed
198 checks in 47.02 seconds. Additional indirect task-tag upserts and protected
list-item cases passed in the 35-test security run (11.15 seconds). Final finance
scope/attribution checks follow in the final validation record below.

Next required work: bounded native access-administration/authentication
operations, bootstrap/last-admin concurrency and security audit, security/cache
revision redesign, all repository ports and the runtime cutover. Business RLS
is not evidence of completion of these remaining requirements. Existing integrity
fixtures now use a real bound business administrator and production grants;
they no longer grant blanket runtime DML privileges in their test databases.

Final validation passed 202 checks in 48.56 seconds, comprising 195 real
PostgreSQL/configuration checks and 7 layer-boundary checks. The complete command
output is in `.local/postgresql-business-final.log`. It includes the finance-only
project-ID regression, trusted finance attribution, protected list upserts and
dependent-tag ownership checks. No application repository has been switched to
the new runtime yet; full regression/coverage, authenticated browser performance,
and restore acceptance remain pending.
