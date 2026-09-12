# PostgreSQL resource pools and assignments

`ResourcePoolService` now executes complete authorized callbacks through
`PostgresResourcePoolGateway`. Native operations cover pool and group catalogs,
optional hierarchy classifications, recursive membership, target mappings,
dictionary tags and project/task assignments. Normalization copies submitted
models; collection arguments are copied before replayable work. Each retry
rechecks current references, graph edges and authorization in its new snapshot.

## Atomicity and data contracts

Pool details and selected tags save together. Group details and all selected
pool/child edges also save together. Invalid references or late native failures
restore the prior details and associations. Existing native cascade rules apply
to pool/group deletion; rollback restores all affected records. Shared child
groups and their pools survive deletion of their parent group.

Group traversal terminates deliberately and deduplicates pools reached through
multiple paths. The existing native hierarchy guard and serializable callback
runner protect concurrent edge insertion; a rejected retry revalidates the
updated graph instead of repeating a partially executed statement.

Mapping upserts preserve their identity for the same pool/type/target tuple,
including concurrent submissions. Nonmonetary FTE and allocation percentages
retain their double-precision domain contract. Assignment dates are bound as
native dates and returned as ISO strings; a missing custom endpoint independently
falls back to the task endpoint. Timestamps return the existing UTC text format,
independent of session time zone and DateStyle. Nullable descriptions and notes
remain editable through their empty-string form boundary.

Assignment filters, task/project batches and task/date joins operate after RLS.
Hidden projects contribute no assignment rows or map keys. Task allocations do
not appear in the project-level map. Shared configuration mutations require
shared administration; allocation changes require edit permission on both the
old and new project owners. A task/project owner mismatch remains an access
denial, including for administrators, as required by the existing native guard.
Pool/group selectors retain their narrow application reference models.

## C3: components

```mermaid
flowchart LR
    Service[ResourcePoolService] --> Port[ResourcePoolGateway / ResourcePoolStore]
    Gateway[PostgresResourcePoolGateway] -. implements .-> Port
    Gateway --> Runner[run_business / Database]
    Runner --> Actor[ActorBinding / authorization policy]
    Gateway --> Store[PostgresResourcePoolStore]
    Service --> Rules[Normalization and cycle-safe group traversal]
    Store --> Hierarchy[Shared hierarchy catalog projection]
    Store --> Tables[(Pools, groups, mappings, tags and assignments)]
    Tables --> Guards[RLS, owner guards, cycle checks and cascading constraints]
```

## Validation

Existing resource, hierarchy, scoped settings UI and layer tests passed **75
checks in 13.72 seconds**. Log: `.local/postgresql-resource-pools-legacy.log`.
Native resource checks use restricted runtime connections and isolated databases;
they cover complete saves, failed cascades, hidden assignments, native dates,
nullable inputs, snapshot consistency, retained inputs and observed retries.
The service and native adapter cover **272/272 statements (100%)**.

```powershell
.venv/Scripts/python.exe -m dotenv -f .local/postgresql.env run -- .venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider tests/postgresql/test_resource_pools.py --cov=app.infrastructure.postgresql.resource_pools --cov=app.application.services.resource_pools --cov-report=term-missing --cov-report=json:.local/postgresql-resource-pools-coverage.json
```

The broader native run also exercised business security, integrity, organization,
tags and foundation tests. It passed 153 checks; one resource test incorrectly
expected a constraint error for a task-owner mismatch. That expectation was
corrected to the existing access-denial contract, and the resource suite then
passed **17 checks in 7.53 seconds**. Logs: `.local/postgresql-resource-pools-native.log` and
`.local/postgresql-resource-pools-followup.log`. Coverage:
`.local/postgresql-resource-pools-coverage.json`.

The runtime remains staged on SQLite. Capacity calculations/cache revisions,
scheduling, portfolio/finance, browser monetary inputs, runtime/tools cutover and
full regression, browser responsiveness and recovery acceptance remain pending.
