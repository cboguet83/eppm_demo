# Design

## Context

See proposal.md for motivation. The existing `tests/postgresql/conftest.py` creates a random database in `empty_database`; `pg_database` calls the real production `migrate()` for each case. `authorized` installs fresh signing keys, accounts, sessions and grants afterward. Real pools close before database teardown. Historical upgrades, failed migrations, competing migration runners and uninitialized-startup tests depend directly on `empty_database`.

`discover_migrations()` hashes SQL and six companion Python migration sources. `eppm.database_identity.epoch` is copied by database cloning; production revision keys also contain the current database OID. `test_revisions.py` already exercises identity reuse across recreated databases. The benchmark tests compare cluster-wide `eppm_benchmark_%` database sets, so independently scheduling those cases can manufacture cleanup failures. Native browser servers use subprocesses, dynamic loopback ports and up to four pooled connections. Real OIDC/recovery tests use module-scoped Compose deployments with unique names and volumes.

The strict plugin in `tests/conftest.py` currently inspects local `session.items`. An xdist controller does not collect the suite that way, so adding `-n` alone is unsafe. Coverage already measures native subprocesses using pytest-cov 7 and the coverage subprocess patch. The CI command includes strict completion, fail-fast and 95% application coverage; JavaScript checks follow.

## Goals / Non-Goals

**Goals:** preserve fresh-database semantics and every existing test/gate while reducing repeated migration work and introducing bounded process concurrency. Make optimized and reference modes comparable, diagnosable and safe on the same isolated PostgreSQL server.

**Non-Goals:** production template support, persistent templates across invocations, business-data snapshots, transactional rollback as a substitute for independent databases, production schema changes, fewer tests, lower thresholds, retries masking flakes, unbounded workers, or parallelizing heavy deployments before isolation is demonstrated. This change does not repair or merge PR #1.

## Decisions

### 1. Own one closed template per worker and invocation

Create a lazy session-scoped migration-only template for each worker, or one for a serial session. Use random invocation/worker-qualified resource identities and keep an in-memory registry of names successfully created by that fixture. Validate distinct explicit test operator/runtime URLs before creating anything. Provision existing shared cluster roles once before workers start; workers must not rotate passwords or alter shared role grants.

Build from a fresh disposable database using real `migrate()`, compare the complete resulting ledger against `discover_migrations()` and close all template connections before exposing the template for cloning. Disable connections to the owned template while cloning; do not set a broadly cloneable global template flag. Keep ownership with the test operator and run CREATE/DROP through the maintenance database in autocommit mode. Reapply and verify required database-level ACLs/settings explicitly because PostgreSQL does not copy those from the source. Never clone an environment-selected application database or terminate unrelated sessions.

Per-worker templates avoid a cross-process template-locking protocol and keep lifecycle ownership local. Cross-invocation caching is rejected: freshness would need trustworthy server, schema, companion-code and security-state identities. Rebuilding once per worker is cheap enough to avoid that machinery. If initialization, ledger validation or cloning fails, fail explicitly and clean up owned partial resources; do not silently fall back to migration-per-test in optimized runs.

### 2. Clone migration state only; preserve explicit fresh mode

`pg_database` receives a fresh random clone per test, retaining the existing fixture value/API and separate operator/runtime access. `empty_database` remains independently fresh and unmigrated. Audit fixture dependency graphs before separating the old shared path; add a regression for callers requesting both fixtures. Seed business records, actor keys, sessions and grants only after cloning.

Use a proposed `--postgres-test-db-mode=template|fresh` option: `fresh` retains create-and-migrate reference behavior; `template` becomes the normal mode only after parity verification. Both modes must run the same collected tests. Native migration tests continue using `empty_database` in either mode. Do not modify migration bytes or the application migrator to optimize tests.

Reset the test clone's lifecycle epoch with a fresh UUID before use and verify cache keys differ even when business IDs/revisions match. Never rewrite arbitrary cache-generation rows: migration-only state must stay equivalent to a new migration. Prove sibling clones start with the same schema/reference state, independent sequences, no seeded signing secrets/sessions/business data, fresh generations on subsequent inserts, independent signed authorization and invalidation behavior. Retain copied-epoch/OID identity regressions as well as the new direct clone tests.

Register cleanup immediately after each successful CREATE, before clone initialization can fail. Close pools/processes before dropping the clone, and clones before their own template. Cleanup targets only exact names in the current invocation registry, never a prefix sweep. Normal exceptions and fail-fast paths must leave no owned resources. A forcibly killed worker may leave its owned template/database; log sanitized identities for explicit recovery, never claim reliable finalizers after SIGKILL. Include controlled worker-crash tests and, if controller cleanup is needed, restrict it to explicitly registered resources with ownership proof. Never delete another run's objects.

### 3. Start with two xdist workers and audited groups

Add a Python-3.14-compatible pytest-xdist development dependency. Keep serial execution available with `-n 0`; parallel CI starts with `-n 2 --dist=loadgroup`, never `-n auto`. Each process gets its own template, connections, temporary files and coverage data. Determine the supported dependency bound from installed tooling/official compatibility evidence before committing it.

Inventory the complete collected manifest and fixture/resource dependencies. Explicitly group every test that creates or observes cluster-wide benchmark copies together; include indirect operator-command callers. Put expensive native-browser/OIDC/recovery workloads in the same conservative scheduling group initially, preventing multiple heavy deployments/benchmarks within that group. Do not assume module scope is global across workers.

A group serializes its own members; it is not an exclusive barrier against all other tests. Audit interactions with the other worker explicitly, including global role changes, shared file outputs, fixed ports, process environment, Streamlit process state and tight timing assertions. Dynamic port selection releases its socket before server startup and is not a persistent reservation. If a genuine cross-group conflict cannot be removed with test-owned resources or correct grouping, keep that conflicting workload serialized and stop parallel CI enablement until the scheduling contract is revised and verified. Do not drop tests, weaken assertions or introduce a second partial suite that bypasses full-suite checks.

Budget connections including fixture pools, deliberate concurrency tests and native-server pools; record maximum observed connections, memory and disk usage. Higher worker counts are outside initial enablement. A repeated flake or worse runtime/resource pressure blocks enabling parallel CI; a serial reference run remains available for diagnosis, not as a silent replacement of a failed parallel gate.

### 4. Keep one full-suite invocation and aggregate proof

Keep all test paths collected in one pytest invocation, with no `-k`, path exclusions or conditional PR filters. Adapt strict mode to gather complete collected node IDs from workers at the controller, validate identical collection across workers, require both PostgreSQL and real authenticated-browser groups, and reconcile final outcomes for every selected test. Handle subtests without counting them as independent collected nodes. Worker loss, missing outcomes, empty/missing required groups, collection errors, deselection that removes required groups, and required collection/runtime skips must fail. Workers must not independently require that their scheduled subset contain every group. Preserve normal non-strict local runs and original nonzero pytest exit codes.

Add real two-worker pytester subprocess cases for success, missing prerequisites, required import/runtime skips, missing groups, collection divergence, failure/fail-fast and worker crash/missing reports. Preserve the current serial plugin tests. Do not let xdist worker restarts or reruns conceal failure or duplicate successful execution.

Use pytest-cov's combined worker coverage plus the existing native-subprocess patch and graceful termination. Assert worker and child-process application lines contribute to the final combined measurement, and missing/crashed workers cannot produce green completion. Keep `source=app`, exclusions, the aggregate 95% threshold and real container OIDC as its separate behavior gate. Do not add per-worker coverage thresholds or compare only one worker's report. Fresh coverage paths are required for each measured run; no stale data or concurrent writes into the baseline file.

### 5. Measure each stage before enabling CI

First reconcile the prerequisite setup PR and establish a clean full serial/fresh baseline on an exact revision. Latest upstream CI at planning time: run 38911540632 stopped with one browser timeout and 1,487 passes; it is not acceptance. Prior passing local baseline (3,219 tests, five subtests, 97.69%, 40m36s) is historical context, not a substitute for the new comparison. Stop and report upstream failures rather than absorbing unrelated repairs without a focused task.

Compare A: serial/fresh, B: serial/template and C: two-worker/template on the same application revision and declared machine/server/tool versions, with coverage enabled and equivalent collected node IDs. Include template construction, all test setup/call/teardown and worker startup in pytest wall time; separately report total CI job time including image/browser provisioning. Run the identical representative database cohort three times per mode, interleaving modes to reduce warm-cache bias; require template median preparation time to improve by at least 50%. Then require complete A/B/C success, all Node checks and at least two successful C full runs with identical outcomes and no owned-resource leaks. Exclude setup-only numbers from whole-suite speedup claims.

Promotion requires a measured full C wall time at least 25% lower than A on comparable resources, alongside unchanged gates and acceptable recorded resource use. This is a proposed acceptance target, not a predicted result. If it is not reached, keep CI serial and leave the performance acceptance task open with actual findings; do not declare completion or lower correctness gates. CI gets the proven template/two-worker flags only after these checks. Full PR CI still runs automatically on every PR and must pass on the final archived revision.

## Risks / Trade-offs

- Copied security/cache state → migration-only template, per-test seeding, clone identity and cross-clone authorization regressions.
- Stale schema or altered companion migration code → no persistent cache, exact ledger/checksum verification, mutation/rebuild regression across sessions.
- Open template sessions or partial creation → quiescent template, immediate ownership registration, bounded failure/cleanup tests.
- Shared-cluster observations → explicit grouped inventory and concurrent-run tests; a group is not an exclusivity guarantee.
- Worker/controller disagreement → complete collection/outcome reconciliation and negative parallel tests before CI changes.
- Coverage regression → combined worker/native child measurements and unchanged 95% gate.
- CPU/memory/disk/connection contention → fixed two-worker cap, resource evidence and serial diagnostic fallback; no database tuning that weakens durability/security.
- Dirty local workspace or stacked PR → preserve the user's Compose port edit; isolate this change's commits and document upstream base explicitly.

## Migration Plan

Planning is committed on `codex/test-performance-templates` without code changes. Apply only after a new user request. Reconcile later setup corrections through an explicit merge into this feature branch without rewriting task history; record the new base. PR #1 must be green and merged before this change's PR can target main as a focused diff. Its merge needs separate user approval; this plan does not grant it.

Implement and verify each numbered task in its own commit. Keep reference execution available throughout rollout. After complete acceptance, verify OpenSpec, archive in a separate lifecycle commit, publish a PR to main and require its final full CI. Merge only after explicit approval using a merge commit. If rollback is needed, disable template/parallel selection through a new reviewed task/commit; preserve historical task commits and all tests/gates.

## Source references

- [PostgreSQL CREATE DATABASE](https://www.postgresql.org/docs/18/sql-createdatabase.html): connection-free template cloning, autocommit requirement and database-level settings/ACL limitations.
- [pytest-xdist execution model](https://pytest-xdist.readthedocs.io/en/stable/how-it-works.html) and [worker fixture lifecycle](https://pytest-xdist.readthedocs.io/en/stable/how-to.html): worker collection and per-worker session fixtures.
- [pytest-xdist distribution](https://pytest-xdist.readthedocs.io/en/stable/distribution.html): bounded workers and loadgroup scheduling.
- [pytest-cov distributed testing](https://pytest-cov.readthedocs.io/en/stable/xdist.html): combined workers and measured subprocesses.
