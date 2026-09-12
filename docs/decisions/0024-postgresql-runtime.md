# ADR 0024: PostgreSQL runtime and replayable transactions

- Status: Accepted; implementation in progress
- Date: 2026-09-12
- Starting commit: `f564a5b4b49c237902415754c61fe9e77f07f7bc`
- Branch: `codex/postgresql-migration`

## Decision

Implement the agreed [PostgreSQL migration plan](../implementation/postgresql-migration-plan.md).
PostgreSQL 18 replaces SQLite in the final runtime. Start with a fresh database,
reference/demo seeds, and fresh application access. Retain the SQLite databases
and a consistent backup; do not import their records. Preserve the existing
Keycloak realm, identities, and volume.

This supersedes the SQLite-specific persistence, transaction, startup, and backup
choices in ADRs 0001–0023. Their business rules, interfaces between layers,
authorization semantics, audit obligations, and UI behavior remain in force.
Temporary additive PostgreSQL modules support implementation and comparison;
they are not a permanent dual-database architecture.

Use explicit SQL, Psycopg, and one injected thread-safe connection pool per
application process. Runtime credentials cannot own protected tables, bypass
row security, or perform DDL. Operators receive separate credentials. Apply
ordered, checksum-verified SQL migrations explicitly under an advisory lock.
Startup only checks compatibility. PostgreSQL data uses a Docker named volume
at `/var/lib/postgresql`; application connections stay on the Compose network.

Use permanent row-security policies, validation, and audit triggers. Bind trusted
actor/session context transaction-locally. Multi-query reads use repeatable-read;
business mutations use serializable transactions. Replay a complete callback,
including authorization and validation, at most three times for a serialization
failure or deadlock. Never retry an uncertain commit or external side effect.
Use narrow locks for hierarchy, bootstrap, and last-administrator invariants.

Actor binding uses an HMAC-SHA256 proof over the server-resolved session, injected
policy inputs, backend PID and transaction start. A custom PostgreSQL setting
alone is not a trusted identity: an ordinary SQL caller can change it. Python
signs with an explicit deployment key; a private PostgreSQL `pgcrypto` helper
verifies it using the separately provisioned key. This extension has the concrete
purpose of preventing SQL callers from forging actor or operator context.
Permission helpers still resolve persisted sessions, account status and grants
in the current transaction snapshot; the proof is not a cached authorization.
Write binding locks the current session, account and assignments so earlier
revocation causes replay and reauthorization, while later revocation waits.

The key and fixed role mapping have no runtime data privileges and default-deny
row security. Only the bounded actor/permission helper interface is executable.
Privileged helpers place `pg_temp` explicitly last in their search path, including
previously installed helpers hardened by a new migration. Startup also rejects
elevated roles reachable through `SET ROLE`, including non-inherited membership.
These choices follow PostgreSQL's
[security-definer guidance](https://www.postgresql.org/docs/18/sql-createfunction.html),
[role privilege checks](https://www.postgresql.org/docs/18/functions-info.html), and
[HMAC support](https://www.postgresql.org/docs/18/pgcrypto.html).

Store euro amounts as NUMERIC and use Decimal through authoritative calculations.
Use native dates, booleans, JSONB, and identity BIGINT keys with DTO adapters.
Replace the global display revision with per-project/per-pool revisions plus
shared-catalog and security revisions. Read scope and revisions in one snapshot;
publish derived caches separately with source-revision validation.

Planning revisions, preparatory version columns, and stale-form protection are
outside this decision. Cache invalidation counters are not planning history.

## Delivery and verification

The [implementation evidence](../implementation/postgresql-migration-evidence.md)
tracks actual components, checks, intermediate commits, and remaining work.
Final acceptance requires the complete regression suite and 95% statement
coverage, real restricted-role PostgreSQL integrity and concurrency tests,
authenticated browser checks, backup/restore, and the plan's three measured
50-session runs against 10,001 deterministic projects. Each routine scenario
must meet p95 <= 1 second. A database-only microbenchmark does not prove that gate.

Publish a C4 map of implemented components as they become operational. Do not
merge or publish this migration until separately requested and acceptance passes.

## Versions verified at implementation start

- [PostgreSQL 18.6](https://www.postgresql.org/docs/release/18.6/), released 2026-08-13.
- [Psycopg 3.3.5](https://www.psycopg.org/psycopg3/docs/news.html).
- [psycopg_pool 3.3.1](https://www.psycopg.org/psycopg3/docs/news_pool.html).

These are pinned rather than using development releases or floating images.
