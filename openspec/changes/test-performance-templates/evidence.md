# Implementation evidence

## Task 2.1 — owned migrated template lifecycle

The real PostgreSQL lifecycle module verifies lazy one-time migration, a closed
template, distinct empty/fresh/clone paths, exact ledger checksums, migration and
metadata initialization failures, clone creation/initialization failures,
database ACL/grant-option/connection-limit/role-setting parity, exact-name
cleanup, closed-factory rejection and secret-safe driver/migration errors.
Generated-name and query-override validation run before database I/O.

```bash
POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
.venv/bin/python -m dotenv -f .local/workflow-tests.env run -- \
  .venv/bin/python -m pytest -q -x tests/postgresql/test_template_database.py
```

Final result: **17 passed in 11.33s**, no failures or skips. New support/test
modules also pass syntax, explicit signature-annotation and 79-column checks. Application and
applied migrations are unchanged. Fixture integration follows in task 2.2.

## Task 2.2 — selectable fixture preparation

`pg_database` uses the worker-local owner in explicit fresh/template modes;
the default remains fresh. `empty_database` remains unmigrated and independent.
The legacy fixture value and URL helper imports are preserved. New regressions
verify combined fixture requests and absence of business/security seeds.

All 30 modules containing actual empty-database migration/fixture paths pass in
both modes: **273 passed in fresh mode (194.80s)** and **273 passed in template
mode (125.93s)**, with no failures/skips. This includes clean install, historical
upgrades, rollback, competing migration runners and schema compatibility. These
focused timings are not the final controlled whole-suite speedup comparison.
The unchanged strict-suite gate checks also pass: **24 passed in 3.14s**.

Fresh/template collection manifests are identical: **3,241 canonical test IDs**.
