# Isolated PostgreSQL test databases

Test infrastructure uses explicit `POSTGRES_TEST_ADMIN_URL` and
`POSTGRES_TEST_RUNTIME_URL` values for the same isolated server, with different
operator and restricted runtime logins. Keep credentials in ignored local files.
Never point these settings at an application deployment.

## Template lifecycle

`tests/postgresql/template_database.py` provides `DatabaseTemplateFactory`.
The pytest fixtures use this owner for both preparation modes. The rollout
default remains `fresh`; template preparation is explicitly selectable:

```bash
python -m pytest --postgres-test-db-mode=fresh
python -m pytest --postgres-test-db-mode=template
```

Supply the same isolated test credentials and other prerequisites as for normal
PostgreSQL verification. `pg_database` yields a new migrated database in either
mode. `empty_database` always yields an independent unmigrated database, including
when a test explicitly requests both fixtures. Existing imports of
`PostgreSQLFixture` and `database_url` from the PostgreSQL conftest remain valid.
Template mode does not bypass historical upgrade or rollback migrations.

Each factory owns an invocation/worker-qualified namespace and records the exact
databases it successfully creates. Its first `clone()` builds a fresh database
through the real migration runner and checks every migration version, name and
checksum, including companion Python migration code. It closes all source
connections and disables new connections before using that database as a
template. The source contains migration state only; business data, actor keys,
sessions and role assignments are seeded separately for each test.

Every clone has a separate database and lifecycle UUID. PostgreSQL copies its
schema, data and sequences; the helper explicitly restores database ACLs, grant
options, connection limits, database settings and per-role database settings.
Those database settings are not generally copied by `CREATE DATABASE TEMPLATE`.
The helper verifies configuration parity before exposing the clone.

`empty()` yields a genuinely unmigrated database. `fresh()` creates a separate
database and runs migrations normally. Neither path shares a template or business
state. No template persists across factory sessions, so source changes cannot
reuse a template left by an earlier invocation.

Close pools and child processes before leaving their database context. Close the
factory after its contexts have exited; it removes owned clones before their
template. Failures during initialization register cleanup immediately after
successful database creation. A creation/configuration failure fails the test
explicitly rather than silently changing preparation mode.

Cleanup accepts exact registered names only. It never sweeps a prefix, deletes a
volume, changes shared passwords or terminates sessions in an unowned database.
Driver failures expose an error category without connection strings or SQL
payloads. Informational lifecycle logs contain only owned identifiers.

A killed process cannot guarantee its finalizers run. Preserve the owning run's
exact identifiers when diagnosing a worker crash and inspect ownership before
manual recovery. An unknown leftover is not permission to delete every matching
database. Worker-crash and parallel-run behavior is verified separately before
parallel CI is enabled.

## Isolation and process failures

`test_template_isolation.py` seeds two simultaneous clones through the same
`authorized_database()` context used by the ordinary `authorized` fixture. Each
seed creates its own signing key, sessions and grants after cloning. Native
authorization rejects a sibling's signing key, session revocation stays local,
business changes invalidate only their own cache snapshot, and generated project
IDs and revision generations remain independent. A subsequent pristine clone
proves that business and authentication seeds never reached the source.

Concurrent factories deliberately use the same worker label: their random
invocation identities remain distinct, and closing one leaves the other's live
clone and template intact. New factories revalidate source checksums rather than
finding a previously migrated template by name. An epoch initialization fault
must fail before yielding a clone and clean up its exact registered resource.

The process regression distinguishes normal pytest `-x` teardown from a hard
process exit. Normal failure runs finalizers; hard exit leaves two owned
resources. The test records only exact database names, OIDs and owner OIDs before
the controlled crash. Its parent recovers those exact resources only when all
three coordinates still match, and verifies that a foreign test database
survives. This is a bounded test recovery procedure, not a production controller
cleanup guarantee. After an uncontrolled worker kill, retain lifecycle logs,
verify that the owning process has stopped and check the exact database identity
and owner before targeted manual cleanup. Never sweep `eppm_test_%`, recreate
shared roles or delete an unknown database to recover a run.
