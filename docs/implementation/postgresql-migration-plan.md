# PostgreSQL migration: implementation handoff for Codex

Planning date: 2026-09-10.

Status: native runtime, tools and test ports are implemented on
`codex/postgresql-migration`; final acceptance remains incomplete. See
[current evidence](postgresql-migration-evidence.md) and the
[implemented C4 architecture](postgresql-architecture.md).
Scope is the PostgreSQL migration only.

The 2026-09-13 merge/push request releases the validated committed checkpoint,
while preserving the then-unfinished runtime cutover on the feature branch. See the
[interim checkpoint evidence](postgresql-migration-evidence.md#interim-main-checkpoint-requested-on-2026-09-13)
and the delivery note in [ADR 0024](../decisions/0024-postgresql-runtime.md).
The final migration acceptance checklist remains open.

## 1. Instructions to the implementing agent

Implement this plan when the user provides it as the implementation task. Read
`AGENTS.md`, inspect the current repository and affected tests, and follow the
existing layered architecture. Work through the milestones below, including
validation, documentation, and focused intermediate commits.

The user explicitly selected a fresh PostgreSQL database, PostgreSQL-only
operation, and a 50-user performance target on the current Docker host. The user
also explicitly requested a dedicated future branch and intermediate commits.
These decisions authorize the database architecture change described here;
record the superseding ADR rather than asking the user to choose the database
again. Preserve all other business and security decisions.

Create `codex/postgresql-migration` when implementation begins, from the latest
accepted, committed application baseline. Record that starting commit. If other
work remains in progress, use an isolated worktree without moving or committing
unrelated changes. If the migration branch already exists, inspect it and resume
its work rather than resetting or replacing it.

The repository may have evolved since planning. Recheck the actual schema,
services, tests, and decisions before implementation; include accepted features
present in the starting baseline. Do not implement unrelated planned features as
part of this migration.

Planning revisions, their PostgreSQL schema changes, and stale-edit protection
belong to the separate [task and resource planning implementation plan](planning-revisions-plan.md).
Complete and validate this database migration first. Do not add preparatory
version columns or implement the planning-revision feature in this migration.

## 2. Objective and agreed boundaries

Replace SQLite with PostgreSQL while preserving the application's existing
features, access rules, and Streamlit experience. Improve the application's
ability to handle concurrent work without assuming that a database replacement
alone will improve browser rendering or Python calculations.

- **Fresh database:** initialize PostgreSQL with reference/demo seeds and
  bootstrap application access again. Do not import SQLite business data, users,
  grants, sessions, or audit history.
- **PostgreSQL only:** no permanent dual-database support, SQLite import utility,
  or runtime SQLite fallback.
- **Existing data:** retain existing SQLite files and a consistent archive. Do
  not delete existing databases or Docker volumes.
- **Runtime:** retain Python `>=3.14,<3.15` and the existing Streamlit/custom
  component architecture.
- **Database migration only:** preserve current planning functionality. Planning
  and revision tables, version columns, historical snapshots, approval/baseline
  workflows, and stale-edit protection belong to the dedicated planning feature.
- **Performance:** 50 active users on the current Docker host; 95% of routine
  warm browsing and simple saves must complete within one second.
- **Delivery:** focused intermediate commits, tested milestones, deployment and
  recovery instructions, and evidence for acceptance. Do not merge, publish, or
  create a pull request unless separately requested.

## 3. Architecture and interface changes

### 3.1 Database, connections, and deployment

- Use PostgreSQL 18, initially pinned to `18.6`. Verify the supported PostgreSQL
  18 maintenance release when implementation begins; if a newer maintenance
  release is available, pin that release and record it. Do not use a floating
  `latest` image or change the selected major version silently.
- Pin compatible stable Psycopg 3 and connection-pool dependencies for Python
  3.14. Keep explicit SQL and the existing application/repository layers; use
  Psycopg directly without introducing an ORM.
- Add PostgreSQL to Compose with a health check and persistent Docker named
  volume mounted at `/var/lib/postgresql`. Keep application database traffic on
  the internal Compose network and avoid a Windows host-directory data mount.
- Preserve the existing local Keycloak configuration and volume. Verify that the
  application's shared Keycloak network namespace can resolve the PostgreSQL
  service. Keep Compose startup dependencies compatible with that arrangement.
- Replace `DB_NAME` and path-based runtime configuration with `DATABASE_URL` and
  validated pool/timeout settings. Supply migration/operator credentials
  separately from application credentials. Keep secrets in ignored local
  configuration or deployment secret storage; never log connection strings.
- Own one thread-safe pool per application process, injected through the
  composition root. Initial configurable defaults: minimum 2 connections,
  maximum 20, acquisition timeout 5 seconds, and statement timeout 10 seconds.
- Open and close the pool through application lifecycle hooks. Return
  connections only after commit or rollback, with transaction-local actor
  context cleared. Keep synchronous database work off the ASGI event loop.

### 3.2 Schema and database lifecycle

- Build a clean PostgreSQL baseline from the final application schema, including
  constraints, indexes, translation tables, access tables, audit records, and
  derived-cache storage. Inventory current migrations and their resulting
  invariants before translating the schema.
- Use ordered SQL migrations with a version/checksum ledger, transactional
  application, and a migration advisory lock. Apply migrations explicitly
  through deployment/operator tooling. Application startup checks schema
  compatibility without initializing, migrating, seeding, or resetting data.
- Preserve old SQLite migration sources unchanged as archived history outside
  the active runtime. Retire SQLite-specific upgrade tests once their behavioral
  equivalents have PostgreSQL coverage. Do not rewrite applied migrations.
- Use identity-backed `BIGINT` keys, native booleans and dates, and JSONB for
  structured JSON. Preserve existing external date and identifier
  representations through adapters; keep stable codes and translation-table
  conventions unchanged.
- Store euro amounts as PostgreSQL `NUMERIC` and carry `Decimal` through project
  records, services, persistence, and calculations. Do not introduce new
  rounding rules or financial concepts. Convert only at presentation boundaries
  where required, without using float intermediates for authoritative totals.
- Port seeding, reset, administrative tools, and benchmarks. Replace SQLite file
  backups with `pg_dump`/`pg_restore`, including verified restoration into an
  isolated database. Preserve the existing pre-operation backup guarantees.
- Keep ordinary app credentials unable to create or alter schema. Migration and
  operator commands receive their separate credentials explicitly.

### 3.3 Authorization and concurrent transactions

- Replace connection-local SQLite views and Python-backed triggers with
  PostgreSQL row-level security and permanent validation/audit triggers. Install
  no schema objects during ordinary requests.
- Preserve scope filtering before pagination, totals, joins, dependency labels,
  and cache access. Preserve checks on old and new owners, protected properties,
  indirect writes, upserts, and cascades. A restricted reader must not infer
  hidden projects or employee details from summaries or references.
- Derive the database role-permission mapping from the existing fixed domain
  definitions. Add parity tests between application authorization and database
  enforcement, including property-based scopes and distinct read/edit scopes.
- Use a runtime role that neither owns protected tables nor bypasses row
  security. Bind trusted actor/session context transaction-locally and keep
  operator access separate. Restrict privileged helper functions and their
  search paths; an ordinary pooled connection must not retain another actor's
  permissions or an operator's privileges.
- Use repeatable-read transactions for consistent multi-query reads. Publish
  derived caches separately so reading does not unexpectedly become a business
  write.
- Use serializable transactions for business mutations, with ordered entity
  locks where required. Serialize bootstrap/last-administrator checks and
  hierarchy mutations using narrowly scoped transaction locks. Avoid a global
  lock on all application writes.
- Add a database-independent callback transaction interface for replayable
  operations. Retry the **entire operation**, including authorization and
  validation, up to three attempts for serialization failures or deadlocks.
  Retrying an individual SQL statement is insufficient. Keep Psycopg types out
  of domain/application contracts.
- Never replay an uncertain commit or an external side effect. Translate
  exhausted retries into existing safe application errors. UI rendering and
  external calls must remain outside replayable transaction callbacks.
- Preserve original command inputs across retries. Database retries address
  serialization failures and deadlocks, not stale forms. Do not add or silently
  substitute expected-version tokens as part of this migration.
- Preserve atomic OIDC-state consumption, session expiry/revocation,
  authentication-versus-activity distinctions, immutable audit history, and
  rollback of a business/security mutation when its required audit insert fails.

### 3.4 Queries, caching, and presentation

- Port all repositories and authentication storage, including SQL parameters,
  generated IDs, upserts, JSON queries, date arithmetic, recursive queries, and
  exception translation. Do not mechanically replace SQL placeholders and
  assume SQLite and PostgreSQL have equivalent semantics.
- Preserve sorting, null handling, filters, pagination, templates, and browser
  component contracts. Update composition APIs to accept the injected database
  resource rather than filesystem paths. Preserve DTO boundaries instead of
  exposing driver rows to the UI.
- Replace the global business-display revision counter with project/pool
  cache-invalidation revisions and separate shared-catalog/security revisions.
  Unrelated project edits must not contend on one revision row. The existing
  global counter is a known concurrency risk that a direct SQL translation would
  retain. These active cache counters are neither planning history nor stale-edit
  protection; do not treat them as preparation for the separate planning feature.
- Build opaque cache tokens from revisions and effective scope read in the same
  snapshot. Detect membership changes, deletion, and database recreation.
  Preserve the browser's opaque-token contract rather than exposing database
  implementation details.
- Preserve actor isolation and revision-checked cache publication. Verify that
  a source or security change during calculation prevents stale publication.
  Session activity and derived-cache writes must not invalidate business
  displays. Restricted summaries must not reuse global warning flags.
- Retain current lazy loading, partial Streamlit reruns, pagination, and bounded
  browser updates. Limit UI changes to database integration, money conversion,
  and safe error handling. Apply the Streamlit skill when changing affected UI
  code.

## 4. Implementation milestones and intermediate commits

Each milestone requires its relevant checks and a final diff review before
committing. Make additional focused subsystem commits when a milestone is too
large to review as one change. Keep unrelated user work out of every commit.

| Milestone | Deliverable and validation before committing |
| --- | --- |
| 1. Baseline and decisions | Record the starting commit, existing test results, deterministic workload, and SQLite timings. Add an ADR superseding SQLite-specific decisions while preserving business/security guarantees. |
| 2. PostgreSQL foundation | Add Compose service, credentials/configuration, pooled connections, migration runner, and isolated PostgreSQL test fixtures. Verify startup, shutdown, pool cleanup, and migration failure recovery. |
| 3. Schema and enforcement | Add the existing application schema, constraints, row security, audit enforcement, and transaction controls. Pass direct-database security and integrity tests before connecting business features. No preparatory planning-version columns are included. |
| 4. Core repositories | Port organization, templates/schema, projects, tags, collaboration, and budgets, including Decimal contracts. Commit coherent subsystem groups with their tests. |
| 5. Existing planning and caches | Port current scheduling, dependencies, allocations, capacity calculations, portfolio queries, and cache-invalidation revisions. Validate transaction snapshot consistency, overlapping writes, and stale-cache rejection. Do not implement planning revisions or stale-form checks. |
| 6. Runtime cutover | Switch composition, authentication, operator commands, seed/reset tools, and benchmarks to PostgreSQL. Archive legacy SQLite code and remove active dependencies on it. |
| 7. Acceptance and documentation | Complete regression, browser, concurrency, performance, and backup/restore checks. Update README, configuration examples, deployment instructions, and C4 documentation. |

Keep SQLite operational during additive early milestones. Switch the runtime
once the PostgreSQL implementations are complete; temporary coexistence on the
migration branch is an implementation staging technique, not a supported final
dual-database architecture.

Maintain an implementation evidence document recording milestone commits,
commands and results, benchmark environment, relevant deviations, and remaining
work. Use the next available ADR number rather than assuming numbering has not
changed since planning.

## 5. Test and performance acceptance

### 5.1 Functional, security, and operational tests

- Run persistence and integrity tests against **real PostgreSQL**, using
  isolated databases and the restricted runtime role. Add CI with PostgreSQL 18
  and Python 3.14. Provision fixtures using separate setup credentials; do not
  accidentally run authorization tests as the database owner or superuser.
- Preserve business regression coverage: CRUD, templates, dependency rules,
  cascades, calendar overlaps, hierarchy cycles, allocation totals, translations,
  filters, and exact monetary round trips.
- Exercise concurrent bootstrap, last-administrator changes, session revocation
  versus saves, overlapping schedule transactions, cache publication races, and
  pooled connections reused by different actors. Check database integrity and
  existing application semantics; rejection of an outdated editor draft is not
  an acceptance criterion for this migration.
- Verify unauthorized direct writes, hidden dependency endpoints,
  protected-property changes, and failed audit inserts cannot bypass safeguards.
- Verify transaction rollback, whole-operation retry, pool exhaustion, database
  unavailability, connection cleanup, and safe error translation. Confirm that
  retries do not duplicate committed changes or audit events.
- Test clean initialization, repeated migration execution, checksum rejection,
  competing migration runners, failed migration rollback, and incompatible
  schema-version rejection without automatic application-side migration.
- Run existing Python/Streamlit and JavaScript tests plus authenticated browser
  workflows. Require at least 95% statement coverage, with especially strong
  authorization, financial, and transaction coverage. Do not hide untested new
  runtime code through exclusions or substitute mocked persistence for integrity
  tests.
- Verify restart persistence and a PostgreSQL backup restored into an isolated
  database, including business records, grants, audit records, and usable rebuilt
  caches. Never point destructive test cleanup at the ordinary application
  database or its volumes.

### 5.2 Reproducible responsiveness test

- Use a deterministic fixture totaling **10,001 projects**, with existing
  task-generation bounds and random seed 42, plus representative dependencies
  and resource allocations. Record actual row counts and generator settings.
- Compare SQLite and PostgreSQL on equivalent fixtures and the same recorded
  host/Docker limits. Use isolated test data, not live edits. Capture the SQLite
  baseline before retiring its runtime and benchmark adapters.
- Exercise 50 authenticated sessions: 40 readers and 10 editors, each acting
  approximately every two seconds. Include real browser workflows so the result
  captures Streamlit and rendering overhead rather than only service throughput.
- Run three ten-minute measurements after two-minute warm-ups. Measure each
  routine scenario separately: portfolio paging, visible task loading, and
  simple saves.
- Require **p95 <= 1 second from browser action to usable result**, including
  successful save confirmation. A pooled average must not hide a failing
  individual scenario. Routine nonconflicting operations must have no unexpected
  failures.
- Report cold loads, badges, bulk imports, and deliberate database transaction
  conflicts separately. Transaction-conflict handling does not demonstrate
  protection against saving an outdated form.
- Record database time, pool waits, lock waits, server processing, browser
  rendering, and unexpected failures. Record CPU, memory, Docker resource limits,
  application/database versions, connection limits, and load-generator placement.
- If the target is missed, report and investigate the measured bottleneck and
  keep acceptance incomplete rather than relaxing the target or claiming that
  PostgreSQL guarantees a speed improvement.

## 6. Cutover and recovery

1. Start PostgreSQL in separate storage, apply migrations, seed explicitly, and
   bootstrap fresh application access. Existing Keycloak identities may remain,
   but application grants must be recreated through the supported workflow.
2. Retain the previous application revision and a consistent SQLite archive.
   Obtain any SQLite snapshot through the existing supported backup workflow,
   avoiding simultaneous Windows and Linux access to the mounted database.
3. Validate fresh installation, restart persistence, schema-version rejection,
   and PostgreSQL backup restoration before adopting the migration branch.
4. Recover PostgreSQL data using PostgreSQL backups and compatible application
   commits. Returning to the old SQLite demo does **not** carry over new
   PostgreSQL edits; this plan does not include reverse synchronization.
5. Merge or publish only when separately requested and acceptance checks pass.

## 7. Completion checklist

- [x] Migration branch and starting commit recorded; unrelated work preserved.
- [x] Superseding ADR and accurate C4 documentation completed.
- [x] PostgreSQL schema, migrations, connections, and deployment tooling complete.
- [x] Preparatory version columns, planning revisions, and stale-edit handling remain outside this plan.
- [x] All repositories, authentication storage, maintenance tools, and benchmarks ported.
- [x] Authorization, audit, transaction, cache, and monetary guarantees verified.
- [x] Active runtime and tests use PostgreSQL; legacy SQLite migration history retained.
- [x] Relevant intermediate commits made with passing checks and reviewed diffs.
- [x] Full regression and coverage requirements satisfied.
- [ ] Fifty-user responsiveness target met with recorded evidence.
- [x] Fresh setup, restart, backup/restore, and recovery procedures verified.
- [ ] Final handoff lists commits, checks, benchmark results, and any remaining limitations.

Migration acceptance covers the current application's PostgreSQL operation. The
final implementation handoff must explicitly state that planning revisions,
their version columns, and stale-form overwrite protection belong to their
dedicated plan and are not implemented by this migration.

## References

These documents informed the plan. Recheck version-specific details during
implementation without silently changing the agreed architecture or targets.

- [PostgreSQL 18 release history](https://www.postgresql.org/docs/18/release.html)
- [PostgreSQL row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)
- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html)
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html)
- [Psycopg connection pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
- [Official PostgreSQL Docker image](https://hub.docker.com/_/postgres)
- [Docker Desktop filesystem guidance](https://docs.docker.com/desktop/features/wsl/best-practices/)
