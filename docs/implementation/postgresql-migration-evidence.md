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
| 3. Schema and enforcement | Pending | Inventory all final SQLite invariants; native PostgreSQL schema, RLS, audit and concurrency tests. |
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
- The baseline and additive PostgreSQL foundation form the next reviewed
  milestone commit; its hash will be recorded with the subsequent schema work.
