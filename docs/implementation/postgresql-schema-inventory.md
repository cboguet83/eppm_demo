# Schema inventory at the PostgreSQL migration baseline

Source: the final SQLite schema produced by accepted commit `f564a5b`, captured
from the isolated 10,001-project fixture. The complete generated `sqlite_schema`
inventory is retained locally at `.local/migration-baseline/sqlite-schema.json`.
Applied SQLite migration sources remain unchanged until archival outside runtime.

## Existing invariants to preserve

| Source / subsystem | Tables and invariants | PostgreSQL treatment |
| --- | --- | --- |
| `schema_init`, `project_type_migration` | Groups, parameters, options, translations; project types and applicability; typed scalar/list values and defaults; one General type; case-insensitive catalog names; owner/reference deletes | Native keys/types/checks/FKs, expression indexes for case-insensitive names, protected-property guards and native queries |
| `schema_init`, organization services | Functions and two managers; employees, teams, membership; unique identities; occupation percentages and calendar intervals | Native dates and booleans; permanent hierarchy/calendar validation with narrow locks and serializable mutations |
| `schema_init`, resource services | Pools, polymorphic mappings, recursive groups, assignments and tags; exclusive group member kind; recursive cycle prevention; task/project owner matching | Native constraints plus permanent cross-table validation; preserve nullable hierarchy classification |
| `hierarchy_migration` | Seven initial stable hierarchy codes; five locales; optional team/pool/group assignments; referenced type deletion restricted; immutable code | Explicit reference seed, translation table, nullable indexed FKs, stable-code trigger |
| `project_collaboration_migration`, experience/links/dashboard migrations | Role/event-type catalogs and translations, contacts, logs and links; valid scope/status; blocking-point classification; safe references | Native date/timestamp fields, catalog indexes, equivalent classifier and authorization guards |
| `wbs_migration` | Stable WBS codes; project share is integer 0–100; sum across projects <= 100; referenced WBS deletion restricted | Native checks, locked aggregate validation, atomic authorization/audit |
| `finance_migration`, `finance_versions_migration` | Numbered immutable snapshots; sealed row/amount sets; immutable cancellation record; unique positions and WBS/year amounts; nonnegative integer cents | Euro NUMERIC without rounding, preserve cent precision, append/seal/cancel triggers, existing version semantics only |
| `access_migration`, finance role extension | OIDC identity uniqueness, user status, fixed positive grants/scopes, session activity/authentication distinction, single-use state, immutable audit, scope tombstones | JSONB, restricted permanent security functions/policies, transaction-local trusted binding and separate operator role |
| `business_security` | Connection-local scoped views; old/new owner checks; distinct read/edit scopes; protected properties; indirect and cascading writes; required audit | Replace with permanent RLS and triggers; no ordinary request creates schema objects |
| Planning repositories/services | Tasks, dependencies, dates, progress, tags, external endpoints and owner matching; explicit deletion semantics; signed 64-bit template lags | Native dates/FKs and permanent guards; BIGINT lags restored by migration 0014; retain current planning behavior, no planning-version columns |
| `display_revision`, capacity and planning caches | Business-only invalidation; scope isolation; stale publication prevention; cached employee memberships | Replace global revision rows with project/pool revisions, shared/security revisions and database epoch; separate cache publication |

Migration `0015_pool_staffing.sql` supplies bounded pool availability without
expanding employee/calendar RLS. Private contribution and binary64 rounding
helpers have no runtime execution privilege; only the actor-authorized aggregate
API is exposed. Native capacity revisions and cache storage remain pending.

The source has 59 application tables (including its migration ledger and global
revision/cache tables). Native migration metadata and the database epoch replace
SQLite lifecycle storage. Cache storage is redesigned as required by the plan,
so table-count equality is not an acceptance criterion.

## Constraints and query differences requiring explicit review

- PostgreSQL identifiers use BIGINT identities. Stable parameter codes remain text.
- SQLite `COLLATE NOCASE` catalog uniqueness uses an explicit lowercase expression
  index. Query sorting/null handling must be checked independently.
- SQLite JSON text becomes JSONB; scoped grant conditions continue to refer to
  stable option and scope-property IDs, with tombstones after deletion/retyping.
- Dates must pass native date validation; existing external ISO strings stay DTOs.
- Financial `cents` storage becomes euro NUMERIC with the same exact cent grid;
  project budgets use NUMERIC without adding a rounding or scale rule.
- `RESTRICT` versus `CASCADE` retains each existing relationship's behavior.
- Trigger aggregates and hierarchy traversal require concurrent tests; merely
  translating an SQLite trigger would not make its checks safe at READ COMMITTED.
- Runtime grants are introduced only with enforcement. Creating the baseline
  tables does not by itself expose business or access data to the runtime role.

## Progress

The native business baseline and permanent integrity triggers are implemented in
`0002_business_schema.sql` and `0003_integrity.sql`. Native type round trips and
concurrent pool-group, calendar and WBS integrity checks pass against PostgreSQL.
Business ownership/RLS and protected-property audit are implemented in
`0006_business_security.sql`. Security transitions, cache redesign and repository
adapters remain required before runtime cutover.

Private scope helpers and categorical-reference lifetime triggers are implemented
in `0004_scope_resolution.sql`. Structure validation is checked against the domain
normalizer. Arbitrary scope-resolution functions have no runtime execution grant.

`0005_actor_authorization.sql` adds signed context and fixed permission mappings.
`0006_business_security.sql` installs RLS and old/new-owner guards for all 45
existing business tables. `0007_access_administration.sql` adds self/admin read
policies and bounded, audited administration operations; identity/session/state
storage remains private pending the authenticated server interface. Employee contact and
staffing rows require organization administration; a permanent manager-label
projection preserves the portfolio catalog. A permanent task projection masks
hidden predecessor IDs, and the base predecessor column has no runtime SELECT
privilege. Application-wide finance scope does not enumerate portfolio IDs.
Dependent task tags and assignments are authorized before their parent deletion;
native constraints and cascades remain installed.

Finance amounts use euro NUMERIC with exact cent-grid validation. Project budgets
accept finite NUMERIC values without a new scale or sign restriction. Capacity
percentages remain nonmonetary floating-point quantities as in the existing domain.
Dependency cycles remain warnings rather than acquiring a new prohibition.
Reporting-function traversal retains its existing termination guards; the current
domain does not impose a new cycle prohibition on that reporting graph.
