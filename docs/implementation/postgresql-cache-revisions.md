# PostgreSQL cache revision foundations

Migration `0016_cache_revisions.sql` adds project and pool cache revisions plus a
separate shared-catalog revision. The existing security revision remains separate.
These are active derived-data invalidation records; they are not planning history,
task version columns or stale-form checks.

## Write ownership and transaction behavior

Project-owned changes update only their affected project revision rows, including
both owners of an assignment move. Pool definitions, mappings and tags update
pool configuration revisions. Organization, schema and shared reference catalogs
update the catalog revision. Source rows and revision increments commit or roll
back together. All existing display source tables have explicit trigger coverage;
session activity, authentication housekeeping, audit entries and derived-data
tables are excluded.

A project allocation does not update a shared pool counter. Instead, the pool's
fingerprint includes the revisions of its visible consuming projects. This avoids
serializing unrelated project editors on a popular pool or a global counter and
keeps hidden demand edits out of a restricted reader's fingerprint.

Revision tables and invalidation helpers are private to the database owner.
Ordinary runtime callers cannot read or overwrite counters or invoke the helpers.
Business guards and RLS remain authoritative for source mutations. Each project
and pool revision record has a UUID generation, so deleting and recreating an
entity with the same numeric ID cannot revive a previous cache key.

## Scope and source fingerprints

The `display_cache_revisions()` metadata read authorizes the
current signed actor, resolves effective project membership, and reads revisions
in the caller's snapshot. Its dependency and pool-source sets are aggregated in
batches. Missing lifecycle, catalog, security or required entity revision records
fail closed instead of yielding a potentially reusable default key.

`RevisionSnapshot` provides complete display, project and pool fingerprints:

- The access portion includes database epoch/OID, actor/session identity,
  effective membership, shared-catalog revision and security revision.
- Project fingerprints include their own source revision and the base revisions
  of visible predecessor projects. Endpoint filtering happens before references
  enter metadata; cycles require no recursive hashing or revision propagation.
- Pool fingerprints include configuration revisions and only visible projects
  currently consuming that pool. Demand references disappearing or moving pools
  change this membership even when the last assignment is removed.

The database OID distinguishes a new database even when a restored database epoch
was copied. Normal application reads expose only opaque SHA-256 tokens; raw actor,
session and database identifiers remain internal. Tokens are comparison values,
not authorization. Every lookup must still read current trusted authorization.
Scope changes driven by project properties are detected even without an access
grant mutation; permission changes with unchanged read membership change the
separate security revision.

## C3: components

```mermaid
flowchart LR
    Sources[(Project, pool and catalog source tables)] --> Triggers[Private transactional revision triggers]
    Triggers --> Revisions[(Project generations, pool generations and catalog revision)]
    Security[(Existing security state)] --> Read[display_cache_revisions]
    Revisions --> Read
    Actor[Signed current actor and effective scope] --> Read
    Read --> Snapshot[RevisionSnapshot]
    Snapshot --> Tokens[Opaque display, project and pool fingerprints]
```

## Verification and pending integration

Real PostgreSQL tests exercise scope/actor/session separation, private helper and
table privileges, transactional rollback, missing metadata, visible versus hidden
predecessors, cycles, generation reuse, copied epochs in a new database, property
membership changes and consistent reads during concurrent writes. A dedicated
lock test holds another project revision, a pool revision and the shared catalog
revision while an independent project edit succeeds with a 200 ms lock timeout.

The broader revision/planning/capacity/resource/integrity/security/foundation run
passed **196 checks in 75.82 seconds** and identified the schema inventory update
for the three new revision tables. After updating the explicit inventory and
batching metadata sources, the final revision/integrity suite passed **46 checks
in 15.23 seconds**. The native revision adapter has **51/51 statements covered
(100%)**. These checks establish the revision foundation; they do not yet prove
cache publication or final application performance.

The final cross-subsystem PostgreSQL suite passed **528 tests in 189.53 seconds**,
including all native business ports, authentication, authorization, migration and
transaction checks. Log: `.local/postgresql-revisions-all-native.log`. An additional
assignment-move regression verifies both pool memberships and old/new project
revisions without writing either pool counter.

```powershell
.venv/Scripts/python.exe -m dotenv -f .local/postgresql.env run -- .venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider tests/postgresql/test_revisions.py tests/postgresql/test_integrity.py --cov=app.infrastructure.postgresql.revisions --cov-report=term-missing --cov-report=json:.local/postgresql-revisions-coverage.json --cov-fail-under=95
```

Logs: `.local/postgresql-revisions-native.log`,
`.local/postgresql-revisions-native-expanded.log` and
`.local/postgresql-revisions-native-final.log`. Coverage:
`.local/postgresql-revisions-coverage.json`.

[Native capacity/planning caches](postgresql-derived-caches.md) now use these
fingerprints for current reads and guarded publication. The digest serialization
matches PostgreSQL JSONB array formatting, verified against both cache kinds and
multiple scopes. Runtime composition remains staged. Portfolio queries,
runtime/operator cutover, project monetary inputs and all final application
coverage, 50-user browser and recovery acceptance gates remain pending.
