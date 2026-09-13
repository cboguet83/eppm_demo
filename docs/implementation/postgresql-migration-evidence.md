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
| 3. Schema and enforcement | Native enforcement tested | Native integrity, RLS, actor binding, audit, access administration, per-entity revisions and private derived-cache storage implemented. Final cutover and clean deployment validation remain. |
| 4. Core repositories | Native adapters tested | Organization, schema, tags, collaboration, templates, projects, WBS and Decimal budget adapters use complete callbacks. Browser money inputs and runtime composition remain staged. |
| 5. Planning and caches | In progress | Native scheduling, resources, private staffing, revisions, guarded caches, bounded portfolio queries and aggregate-only dashboard reads implemented. Final runtime integration remains. |
| 6. Runtime cutover | In progress | Native authentication/access adapters and callback service integration implemented; composition, operator tools, seeds, benchmarks and legacy archive remain. |
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
- `86b3d30` — business RLS, owner guards and protected-change audit;
  202 PostgreSQL and layer-boundary checks passed.
- `b67acf9` — native audited access administration and concurrent bootstrap;
  232 PostgreSQL and layer-boundary checks passed, plus bootstrap rollback.
- `57de07e` — PostgreSQL authentication and callback access workflows;
  454 broad checks and 238 follow-up authentication checks passed.
- `26a2118` — native organization workflows and minimal reference projections;
  197 existing, 80 native and 47 replay/foundation checks passed.
- `607ea06` — native project templates and exact typed property values;
  82 existing, 139 native and 40 follow-up checks passed.
- `768efc1` — native schema settings and atomic callback edits;
  47 existing and 165 native checks passed.
- `78b96cb` — native tag catalogs, assignments and scoped paging;
  49 existing and 101 native/security checks passed.
- `46eb0a5` — native collaboration and bounded project contact details;
  95 existing, 17 useful-link and 177 native/security checks passed.
- `8c5ece1` — native projects, WBS allocations and Decimal budget reports;
  177 existing and 177 native/security checks passed.
- `93292d3` — native resource pools, groups, mappings and assignments;
  75 existing and 17 final native resource checks passed, with broader integrity
  and transaction regressions recorded below.
- `98beab7` — native immutable finance plans and Decimal allocated budgets;
  79 existing, 186 broader native/security/HTTP/domain and 8 browser checks passed.
- `80a0ef4` — native task scheduling, dependency graphs and atomic replacements;
  146 existing, 194 broader native and 45 final scheduling checks passed.
- `e5723db` — native capacity snapshots and private staffing aggregates;
  37 existing and 40 final capacity/integrity checks passed.
- `787c32c` — scoped project/pool revision fingerprints and independent writers;
  528 native checks passed, with 100% native revision-adapter statement coverage.
- `851f0d2` — authorized capacity/planning caches and separate publication;
  570 native checks passed, with 100% native cache-adapter statement coverage.
- `3f8d4a1` — scoped portfolio paging, exact facets and Decimal component transport;
  54 combined checks and 3 browser checks passed, with 100% native adapter coverage.
- `c344f53` — scoped dashboard reports and private competing-demand aggregates;
  638 native/dashboard/layer checks passed, with 99.26% native dashboard adapter coverage.

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

## Native access administration

`0007_access_administration.sql` adds bounded registration, account status,
grant and revocation functions with native access-management, MFA and recent
authentication checks. They include immutable audit and security revision
updates atomically. Fixed-role scopes are canonicalized before idempotent
grant insertion; invalidated grants require explicit revocation/recreation.
Scope-configuration functions expose categorical references and bounded project
labels to access administrators without granting business/portfolio reads.
Account and assignment reads are limited to self or an access administrator;
pending accounts may read their own profile but not assignments.

Bootstrap/recovery uses a separate operator-only function, requires a verified
OIDC identity and explicit attribution/reason, and writes the completion marker,
grant, account state and audit together. The narrow administration advisory lock
plus serializable replay protects concurrent bootstrap and last-admin removal.
Runtime actors have no direct security DML or operator-function privilege.

The complete PostgreSQL and layer-boundary run passed 232 checks in 56.63 seconds
(`.local/postgresql-access-final.log`). It includes concurrent self-disable and
self-revocation by two administrators, competing initial bootstraps, invalid and
stale categorical grants, scope catalog parity, mandatory audit rollback for
registration/grant/revocation/status, and self/admin row isolation.

The additional bootstrap audit-failure test passed in 0.24 seconds
(`.local/postgresql-bootstrap-audit.log`), verifying rollback of activation,
assignment and the once-only completion marker when required audit fails.

Remaining security work includes signed pre-session OIDC/state/session operations,
the PostgreSQL access repository and callback service integration, supported
operator CLI integration, and revision/cache integration for protected changes.
The application still uses SQLite; the milestone is not final migration acceptance.

## Native authentication and access-service integration

`0008_authentication.sql` and the PostgreSQL access/state adapters now implement
verified identity creation, concurrent first login, session rotation/lookup,
explicit activity, audited logout and single-use OIDC state. Purpose-specific
server proofs bind each pre-session operation to its exact payload, backend and
transaction. Raw runtime SQL cannot read private authentication tables, invoke
unsigned operations, replay another transaction's proof or use a server proof as
an actor. Internal scope evaluation also requires a signed request for the bound
actor's persisted grant or access-administrator authority.

The access and deployment services now use complete callbacks. Native mutation
contracts own their mandatory audit and integrity checks; no duplicate
application audit is appended. Every retry revalidates identity expiry and
authorization. Cookie/correlation generation stays outside callbacks. Native
definite-rollback tests verify one identity/session/audit after replay, bounded
retry exhaustion and no partial changes on failed login/logout audit.

Authlib now receives an explicitly injected async state store. Native HTTP tests
use real Authlib/JOSE, PostgreSQL state and access services; only the external
identity provider's HTTP transport is replaced. Tests cover PKCE, issuer,
audience, nonce, expiry, secure cookies, rejected claims, foreign/replayed
state, origin checks, activity versus authentication time and safe failure logs.
State tests verify exact opaque-string retention, hashed keys, ten-minute TTL,
single-use concurrent consumption and database work on worker threads. A retry
rechecks consumption expiry and retains the original storage deadline.

Validation used explicit test URLs from ignored `.local/postgresql.env` and
individually created/dropped `eppm_test_<UUID>` databases:

- Full PostgreSQL suite plus affected access, OIDC, session, launcher and layer
  regressions: **454 passed in 149.82 seconds**. Command: project Python with
  `-m dotenv -f .local/postgresql.env run --` followed by project Python
  `-m pytest -q -p no:cacheprovider tests/postgresql tests/test_access_security.py
  tests/test_access_operator.py tests/test_oidc_authentication.py
  tests/test_session_transport.py tests/test_application_authentication_entry.py
  tests/test_layer_boundaries.py`. Output: `.local/postgresql-auth-full.log`.
- Follow-up authentication run, including additional context-denial, native
  error translation, revocation and audit-failure cases: **238 passed in 47.41
  seconds**. PostgreSQL files: `test_access_service.py`, `test_oidc_state.py`,
  `test_oidc_http.py`, `test_server_proofs.py`; same affected top-level test files
  as above. Output: `.local/postgresql-auth-adapters.log`.
- Follow-up statement coverage for the access service, OIDC protocol adapter and
  new PostgreSQL access/state adapters: **455/457 statements (99.56%)**; both new
  PostgreSQL adapters have **100%**. Report:
  `.local/postgresql-auth-adapters-coverage.json`. This is subsystem evidence,
  not the pending full-codebase coverage gate.

The launcher uses the new access callback contract while explicitly composing
the existing SQLite stores. Remaining work includes PostgreSQL business
repositories, per-entity revisions/caches, operator and runtime composition,
seed/reset/backup tools, legacy archive and all final acceptance gates. The
Authlib HTTP checks are not the required 50-browser-user performance runs.

## Native organization subsystem

The organization store and service callback integration are implemented. Native
CRUD uses explicit SQL, native booleans/dates, generated identities and existing
DTOs. Team details/membership and employee/initial-calendar operations commit or
roll back together. Native race tests verify whole-operation replay for team
replacement and calendar overlap. `0009_organization_references.sql` preserves
the existing name-only employee reference boundary while the underlying employee
and calendar records remain private.

Validation: **197 existing organization, hierarchy, UI, authorization and layer
checks passed in 102.74 seconds**; **80 native organization, security and integrity
checks passed in 42.88 seconds**. The new organization, hierarchy and business
transaction modules have **168/168 statements covered**. Commands, C3 components,
contracts and test scope are recorded in
[PostgreSQL organization repository](postgresql-organization.md). Runtime
composition and the remaining core repositories are still pending.

The strengthened callback-race checks plus PostgreSQL foundation checks passed
**47 checks in 15.80 seconds**, including observed retries and service-level
calendar overlap revalidation. Output: `.local/postgresql-organization-replay.log`.

## Native project templates and property values

Project-type services now execute whole callbacks through their PostgreSQL
gateway. Native SQL preserves General-type guards, unique names, applicability,
nullable overrides, retained inactive defaults and atomic protected-change audit.
The shared property adapter loads parent values and list items with one scoped
join. Null, empty text, empty list and absent values remain distinct; numbers
round-trip as Decimal and dates keep their ISO-string boundary.

Validation: **82 existing checks passed in 13.99 seconds**, **139 native checks
passed in 40.10 seconds**, and **40 follow-up checks passed in 1.41 seconds**.
The two new PostgreSQL adapters have **110/110 statements covered**. Actual
serializable races verify combined rule/default updates and type deletion versus
exclusive property assignment; a forced rollback verifies retained command
inputs. Details, command, C3 components and log paths are in
[PostgreSQL project templates](postgresql-project-types.md).

`0010_finite_property_numbers.sql` adds the native finite-number check to project
values and template defaults without introducing rounding. Project budget and
finance Decimal contracts, the remaining repositories, runtime composition,
tools and final acceptance gates remain pending.

## Native schema administration

Schema settings now use complete callbacks and a native PostgreSQL adapter for
groups, definitions, choices, translations and project-type applicability.
Compound failures restore prior details, selections and protected-change audit;
project/default reference guards include explicit nulls. The existing native
scope triggers preserve option lifetimes and property tombstones.

Validation: **47 existing checks passed in 19.21 seconds** and **165 native schema,
template, scope, business-security and foundation checks passed in 64.47 seconds**.
The schema service and native adapter have **175/175 statements covered (100%)**.
Actual concurrent service calls verify fresh auto-allocated IDs/orders after
rollback and option deletion racing with default creation. Additional checks
cover consistent multi-query snapshots and unchanged original command inputs.

Commands, C3 components and test boundaries are documented in
[PostgreSQL schema settings](postgresql-schema-settings.md). Logs:
`.local/postgresql-schema-legacy.log`, `.local/postgresql-schema-native.log`;
coverage: `.local/postgresql-schema-coverage.json`. The remaining repositories,
Decimal budgets, cache revisions, runtime/tools cutover and full acceptance
gates are still pending.

## Native tag catalogs and assignments

Tag catalogs, project/task/pool assignments, batched links and task-tag paging now
use native PostgreSQL SQL and complete callbacks. RLS filters rows before label
joins, usage totals, filtering and paging; native guards protect both old and new
project owners. Dictionary deletion is atomic across its assignments, and pool
upserts return a single identity for concurrent duplicate requests.

Validation: **49 existing checks passed in 10.67 seconds** and **101 native tag,
business-security, authorization and layer checks passed in 30.51 seconds**.
The native tag adapter has **155/155 statements covered (100%)**; combined with
the tag service, this run covers **274/278 statements (98.56%)**. Existing tests
also exercise the service's invalid paging/filter input branches.

Native tests verify literal searches, numeric/text/null ordering, bounded
selectors, hidden-row exclusion from batches and counts, stable count/page
snapshots during deletion, old/new owner checks, safe failures, concurrent pool
upsert replay and copied command inputs. Commands and C3 components are in
[PostgreSQL tags](postgresql-tags.md). Logs:
`.local/postgresql-tags-legacy.log`, `.local/postgresql-tags-native.log`;
coverage: `.local/postgresql-tags-coverage.json`. Projects, collaboration,
planning/resource pools, Decimal budgets/finance, cache revisions, runtime/tools
cutover and full acceptance gates remain pending.

## Native project collaboration

Contacts, roles, event types, log events and useful links now use complete
callbacks and a native collaboration store. Migration
`0011_project_contacts.sql` exposes occupant phones only through assignments in
a requested actor-visible project. Its safe search path, explicit EXECUTE
privileges and current-actor scope filtering are verified with direct runtime
SQL. General selectors use only the minimal name directory; employee records
remain restricted to shared administration.

Validation: **95 existing collaboration/scoped UI/layer checks passed in 24.79
seconds**, **17 useful-link/project UI checks passed in 4.53 seconds**, and **177
native collaboration, business-security, integrity, authorization and foundation
checks passed in 50.17 seconds**. The service and native adapter have **136/136
statements covered (100%)**. Tests also cover atomic catalog translations,
current occupant resolution, project-qualified mutations, date/time formatting,
consistent snapshots and observed whole-callback retries for concurrent renames.

Commands, C3 components and privacy contracts are documented in
[PostgreSQL collaboration](postgresql-collaboration.md). Logs:
`.local/postgresql-collaboration-legacy.log`, `.local/postgresql-collaboration-links.log`,
`.local/postgresql-collaboration-native.log`; coverage:
`.local/postgresql-collaboration-coverage.json`. Projects, Decimal budgets/finance,
planning/resource pools, cache revisions, runtime/tools cutover and full
acceptance remain pending.

## Native projects, WBS and budget reports

Project and WBS services now use native complete callbacks. Project master data,
properties, links and WBS shares commit or roll back together; property writes
and planning catalog applicability are batched. Native NUMERIC amounts remain
Decimal through project records and the minimal scoped budget report reader.
Migration `0012_project_operations.sql` adds bounded WBS remainder and project
identity functions without exposing hidden project identities.

Validation: **177 existing project, WBS, budget, UI and layer checks passed in
33.98 seconds** and **177 native project, budget, template, schema, integrity,
security and foundation checks passed in 53.80 seconds**. The native project,
WBS, budget and property adapters have **195/195 statements covered (100%)**.
Observed retries cover competing WBS claims and preserved submitted values;
other checks cover exact money, identity races, rollback and protected audit.

Commands and C3 components are documented in
[PostgreSQL projects](postgresql-projects.md). Logs:
`.local/postgresql-projects-legacy.log`, `.local/postgresql-projects-native.log`;
coverage: `.local/postgresql-projects-coverage.json`. Browser money inputs,
planning/pools/capacity, portfolio/finance, cache revisions, runtime/tools cutover
and final regression, responsiveness and recovery acceptance remain pending.

## Native resource pools and assignments

Pool details/tags, recursive group details/membership, target mapping upserts and
project/task assignments now use complete native callbacks. Assignment queries
and batches filter hidden owners through RLS before joins and return native
dates through their existing ISO boundary. Compound failures restore prior
details and cascading records. Concurrent cycle, upsert and pool/tag edits
observe whole-operation retries; submitted models and lists remain unchanged
by caller mutation between attempts.

Validation: **75 existing checks passed in 13.72 seconds**. The broader native
run passed **153 checks in 47.42 seconds**, with one new resource test expecting
the wrong exception for a task-owner mismatch. The existing guard correctly
denies that mismatch even for administrators. After correcting the expectation,
the complete resource suite passed **17 checks in 7.53 seconds**. The service and
native adapter have **272/272 statements covered (100%)**.

Commands, C3 components and test scope are documented in
[PostgreSQL resource pools](postgresql-resource-pools.md). Logs:
`.local/postgresql-resource-pools-legacy.log`, `.local/postgresql-resource-pools-native.log`,
`.local/postgresql-resource-pools-followup.log`; coverage:
`.local/postgresql-resource-pools-coverage.json`. Capacity/cache revisions,
scheduling/dependencies, portfolio/finance, browser monetary inputs, runtime/tools
cutover and all final acceptance gates remain pending.

## Native finance and Decimal allocated budgets

Finance services now use native callbacks with active-account reads and global
finance writes independently of project scope. Plans, sparse amounts and
cancellation audit remain immutable. Decimal euros now flow through finance
parsing, services, NUMERIC storage, exports and allocated dashboard budgets.
Existing per-share half-up cent rounding and the amount limit remain unchanged;
migration `0013_finance_amount_limit.sql` also enforces that limit in PostgreSQL.

Validation: **79 existing checks passed in 8.46 seconds**, **20 initial native
checks passed in 7.46 seconds**, and **186 broader native/security/HTTP/domain
checks passed in 40.24 seconds**. The finance domain, service and native adapter
have **246/246 statements covered (100%)**. Concurrent saves receive consecutive
numbers after observed replay; concurrent cancellation commits one audit record.
Tests also cover low-precision Decimal contexts, exact maxima, late rollback,
unchanged submitted grids, revocation during retry and authenticated downloads.

Real finance/dashboard browser checks passed **8 tests in 31.61 seconds** with
directly captured pytest exit code **0**. Chart values retain the same rounded
project shares. Playwright shutdown warnings remain in the test log; direct exit
capture distinguishes those from test failures. Browser tests use staged SQLite
composition; native storage/authentication are covered by the integration suite.

Commands, C3 components and log paths are in
[PostgreSQL finance](postgresql-finance.md). Runtime cutover, scheduling/capacity,
portfolio/dashboard repositories, cache revisions, project monetary inputs,
operator tools and all final regression, responsiveness and recovery gates remain.

## Native scheduling and dependency graphs

Task services now use complete PostgreSQL callbacks for details, dependencies,
imports, deletes and schedule replacement. Read projections batch metadata and
filter hidden owners/endpoints before totals, labels, warning flags and recursive
closure. The permanent predecessor view masks hidden primary links; guarded
cleanup cannot detach hidden or uneditable references. Scoped summary SQL retains
all four dependency rules, task-endpoint precedence and empty-project behavior.
Migration `0014_dependency_lag_range.sql` preserves the existing template format's
signed 64-bit lag range without changing applied migrations.

Validation: **146 existing checks passed in 24.50 seconds**, **194 broader native
planning/resource/security/integrity/schema/foundation checks passed in 65.91
seconds**, and **45 final native scheduling checks passed in 18.83 seconds**.
The service and native adapters cover **305/309 statements (98.71%)**, including
all native adapter statements. Real concurrent replacements resolve fresh local
task IDs within each complete attempt; concurrent date/progress edits keep both
fields. Known-rollback replay retains copied nested inputs. Late failures restore
deleted tasks, dependencies, tags and allocations, and snapshot reads retain a
consistent bundle during a concurrent replacement.

Commands, C3 components and log paths are in
[PostgreSQL planning](postgresql-planning.md). This completes the scheduling
portion of milestone 5, not its cache/capacity/portfolio work. Native summary SQL
currently computes fresh data; the staged public summary call still requests a
writer for the legacy cache. Per-entity revisions, opaque tokens, separated and
guarded publication, runtime/operator cutover, project money forms and all final
application coverage, 50-user responsiveness and recovery gates remain pending.

## Native capacity inputs and private staffing aggregates

Capacity reads now collect requested pool definitions, aggregate staffing,
RLS-filtered demand and relevant project dates in one repeatable-read snapshot.
Migration `0015_pool_staffing.sql` adds a bounded actor-authorized aggregate API;
raw employee/calendar RLS remains unchanged and calculation helpers stay private.
Project readers receive availability without individual staffing records. Shared
administrators receive the established contribution details, with a permission
recheck before returning them.

The new domain aggregate boundary preserves zero-assigned-resource precedence,
deduplicated demand, daily overloads and date fallback rules. Native staffing
matches the existing team/direct-employee override, vacant-function and calendar
behavior. A private binary64 rounding helper retains exact historical rounding
order at half-millifte boundaries; euro arithmetic remains Decimal and separate.

Validation: **37 existing capacity/timeline/cache-race/layer checks passed in
4.38 seconds**. The broader native run passed **137 checks in 48.96 seconds**,
with one expected public-function allowlist update required for the new API.
After updating that explicit list, **40 native capacity/integrity checks passed
in 20.32 seconds**. The native reader and pure capacity/input modules have
**167/167 statements covered (100%)**. Tests cover 5,004 rounding values, 15
randomized staffing configurations, actor/helper privacy, scoped assignments,
25-year calendar bounds, permission revocation, concurrent snapshot reads and
safe outages.

Commands, C3 components and log paths are in
[PostgreSQL capacity](postgresql-capacity.md). Native cache storage, per-entity
revisions, opaque scope/revision tokens and guarded publication remain required.
Portfolio queries, runtime/operator cutover, project monetary inputs and all
final regression, 50-user responsiveness and recovery gates also remain pending.

## Native cache revision foundations

Migration `0016_cache_revisions.sql` adds private project/pool generations and
counters plus a shared-catalog revision. It covers all baseline display sources
while excluding session activity, audit and derived writes. Project/assignment
changes update their affected project revisions; they never write one global
business counter or a shared pool revision. Pool configuration and shared-catalog
changes retain separate ownership.

Authorized revision snapshots read effective scope, security state and batched
source metadata consistently. Project fingerprints include only visible
predecessor revisions; pool fingerprints include only visible consuming project
sources. Generations prevent reuse after numeric identity recreation, and the
database OID distinguishes a new database with a copied epoch. Opaque tokens
remain comparison values and do not bypass current authorization.

Validation: **196 broader native checks passed in 75.82 seconds**, with one
schema-inventory expectation requiring the three new revision tables. After that
explicit inventory update and batched metadata aggregation, **46 final native
revision/integrity checks passed in 15.23 seconds**. The revision adapter has
**51/51 statements covered (100%)**. Checks include independent writers under held
revision locks, hidden-demand isolation, cycles, rollback, missing metadata,
property-driven membership, unchanged-scope permission changes, session activity,
database recreation and consistent reads during concurrent edits.

The complete native PostgreSQL suite then passed **528 tests in 189.53 seconds**,
covering every current native business port, authentication, authorization,
migration and transaction tests with the new triggers installed. Log:
`.local/postgresql-revisions-all-native.log`. The additional last-assignment move
regression also passed, verifying both pool memberships and old/new project
revisions without a pool-counter write.

Commands and C3 components are in
[PostgreSQL cache revisions](postgresql-cache-revisions.md). This milestone is the
revision foundation; the native payload and publication work follows below.

## Native derived-cache storage and publication

Migration `0017_derived_caches.sql` adds private session/entity cache rows and
database-generated current keys. Cache reads reauthorize before using persisted
or memory results. Publication verifies a transaction-bound server proof and all
current source/security keys before an atomic insert/update. Frozen payload bytes
survive complete serializable retries and supply the same process-memory result.

Capacity and planning adapters calculate outside cache locks and publish
separately from repeatable-read input snapshots. Process memory has entry/byte
limits, retains details across summary reads and returns independent objects.
Current permission checks hide staffing details and scoped assignment/dependency
queries prevent hidden owners from entering results. Revoked sessions fail with
the existing access-denied contract, including warm memory hits.

Validation: the initial affected native/existing suite passed **184 tests in
61.15 seconds**. The expanded cache/planning/service/layer suite passed **164
tests in 53.75 seconds**, covering **456/458 statements (99.56%)** across the
planning service and native planning/cache adapters. All **308 native adapter
statements are covered (100%)**. Tests include both fingerprint implementations,
day/format misses, hidden source isolation, source/security changes during
calculation, forged proofs, large bodies, serialization retries, late rollback,
owner deletion, memory bounds and concurrent calculations without a cache lock.

The full native PostgreSQL suite passed **570 tests in 220.64 seconds**, covering
all current native ports, access/authentication, integrity and transaction tests
with the new cache migration installed. Log:
`.local/postgresql-derived-cache-all-native.log`.

Commands, C3 components and logs are in
[PostgreSQL derived caches](postgresql-derived-caches.md). Portfolio queries,
runtime/operator cutover, one process-state injection, project money forms and
all final application coverage, 50-user browser and recovery acceptance remain.

## Native portfolio pages and facets

The native portfolio reader applies current scope before counts, pages, facets,
metrics and details. ID-first pagination hydrates only the requested page. One
facet statement shares grouped values between exact statistics and bounded
choices. Dynamic properties respect applicability; manager labels use the
minimal directory and bounded, cycle-safe reporting ancestry. Decimal amounts
remain exact through services and become strings at the component JSON boundary,
so selected numeric facet values round-trip without binary floating-point loss.

Validation: **52 initial checks passed in 11.75 seconds**, followed by **187
broader native/service/security/cache checks in 74.83 seconds**. After query
improvements, **14 native checks passed in 8.00 seconds**, covering all **160
native statements (100%)**. **15 component tests** and **3 real-browser tests in
9.29 seconds** passed, including exact decimal facet selection. Browser pytest
exit code was captured as **0** despite existing Playwright shutdown warnings.

The final combined portfolio/service/transport/layer run passed **54 tests in
26.79 seconds**, covering **203/203 statements (100%)** across the portfolio
service and native reader/query modules.

A single-actor, 10,001-project query probe reduced two page reads plus a facet
from **2.8143 s to 0.2220 s** by avoiding repeated property work. Final observations
were **0.0597 s** for the first page, **0.0438 s** for the last page and **0.1184 s**
for the facet. This limited service probe is not the representative workload or
the 50-user browser acceptance measurement.

Commands, component relationships and evidence paths are in
[PostgreSQL portfolio](postgresql-portfolio.md). Dashboard storage and its
aggregate-only competing-demand behavior are now ported. Runtime/operator/seed
and benchmark cutover, exact project-money inputs, legacy archival, final
coverage, 50-user browser measurements and recovery acceptance remain pending.

## Native dashboard reports and private aggregates

The dashboard reader now reauthorizes scoped catalogs, requested finance statuses,
Decimal WBS allocations and active blockers in repeatable-read snapshots. Active
users with no business grants retain an empty dashboard. Explicit out-of-scope
requests, invalid signatures and deployment actors are denied.

Migration 0018 computes competing pool demand inside a narrowly granted SQL
function. Only quarterly totals and currently visible drill-through IDs reach
the application; hidden project/employee records remain private. Interval event
ordering and the native rounding helper retain the domain's FTE calculations,
date fallback, inclusive periods and 25-year cap. Quarterly peaks use concurrent
totals, including quarters fully covered by calendar overrides. Opaque revision
hashes invalidate relevant competing demand, source membership and finance status
changes while ignoring session activity and unrelated hidden project/pool edits.

The initial native dashboard/aggregate/integrity checks passed **54 tests in
31.26 seconds**, with **134/136 native adapter statements covered (98.53%)**.
Twenty randomized allocation workloads matched independent pure-domain results.
Concurrent changes retain a consistent read snapshot and missing revision rows
fail closed. The full native suite plus existing dashboard and layer regressions
passed **638 tests in 258.60 seconds**, exit code **0**. Dashboard
adapter/service/domain coverage is **275/277 statements (99.28%)**; native
dashboard adapter coverage is **135/136 statements (99.26%)**.

Commands, C3 components and detailed behavior are documented in
[PostgreSQL dashboard](postgresql-dashboard.md). Runtime/operator/seed/benchmark
cutover, exact project money inputs, legacy archival, full application coverage,
authenticated 50-user browser measurements and recovery acceptance remain.

## Process resource lifetime for runtime integration

`RuntimeResources` now groups the restricted pool, signing key and bounded cache
state for explicit composition. Its ASGI lifespan opens/checks and closes in
worker threads, without schema initialization or seeding. Failures and
cancellation retain shutdown cleanup; configuration has no operator-credential
fallback and representations omit secrets. This resource is staged for the
coordinated business/authentication launcher cutover.

Native lifecycle, pool/foundation and layer checks passed **58 tests in
10.66 seconds**, exit code **0**, with **31/31 resource-module statements covered
(100%)**. Log: `.local/postgresql-runtime-resources.log`; coverage:
`.local/postgresql-runtime-resources-coverage.json`.
