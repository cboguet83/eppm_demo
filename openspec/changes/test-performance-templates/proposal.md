# Proposal

## Why

The passing setup baseline took 40m36s: approximately 95% of measured test time was in PostgreSQL tests, and 2,246 cases requested a database migrated independently through 68 migrations. A small local preparation benchmark measured 0.466s for create-and-migrate versus 0.055s for cloning; this motivates template reuse, without claiming an equivalent whole-suite speedup.

## What Changes

- Build an invocation-local, migration-only PostgreSQL template once per pytest worker, then give each ordinary database test its own disposable clone. Retain truly empty databases for clean-install, historical upgrade, rollback and migration concurrency tests.
- Prove independent business writes, sequences, signing keys, lifecycle/cache identities, connections and teardown across sibling clones and concurrent runs. Verify complete migration ledgers, including companion Python migration checksums.
- Introduce bounded pytest-xdist execution, starting at two workers with explicit grouping for shared observations and expensive browser/deployment work. Preserve a serial reference/fallback mode and prove scheduling safety before enabling parallel CI.
- Adapt the full-suite gate to controller/worker collection and outcomes; retain all tests, required PostgreSQL and real authenticated browser execution, no required skips, native subprocess coverage, the aggregate 95% coverage threshold and JavaScript checks on every PR.
- Measure unchanged serial, template serial and template/two-worker runs on comparable resources, including failures, resource use and cleanup. Enable optimizations only with correctness parity and demonstrated improvement.

## Capabilities

### New Capabilities

`completed-page-navigation`: record the existing immediate-blanking/completed-destination behavior restored by approved corrective task 3.9. The original performance work remains test infrastructure and developer tooling.

### Modified Capabilities

`independent-project-saves`: retain reliable independent saves after upgrading an already populated database, preserving records, constraints, permissions, serializable isolation and the existing retry bound. Business and authorization rules remain unchanged. Test safety and acceptance contracts are specified in design.md and tasks.md.

## Impact

Expected implementation areas: `tests/postgresql/conftest.py` and small test-only support modules, isolation regressions, `tests/conftest.py`, `tests/test_full_suite.py`, audited test scheduling markers, `pyproject.toml` development dependencies, `.github/workflows/tests.yml`, and `docs/development-workflow.md`. Add pytest-xdist as a development dependency only after Python 3.14 compatibility checks. No runtime dependency, applied migration rewrite, Docker security policy or business-rule change is planned. On 2026-10-18 the user approved task 3.10: a new forward migration setting project-table fillfactor to 70 and repacking existing rows, with regression tests and a separate commit. This physical storage correction requires additional disk space and an exclusive table lock; isolation, authorization and the three-attempt retry limit remain unchanged. The user approved task 3.9 on 2026-10-18 to restore navigation readiness in `app/presentation/components/page_transition.py` and its shell completion marker, with controlled regressions. This narrow UI correction supersedes the original tooling-only exemption; its actual capability is specified rather than skipping specs.

Branch: `codex/test-performance-templates`, created from setup PR #1 head `393f4f571c9140942dc89a1cec51e3a8abec1cec` with explicit user authorization to depart from the usual main-branch starting point. PR #1 was a prerequisite at planning time; after its approved corrections and passing full CI, the user approved its merge commit `0b6ebb0bb7524d340a11a7cfbae28ed33a8882e7`. Historical failed baselines remain evidence; current acceptance requires the corrected-source comparison. Preserve the existing unrelated local Compose port edit.

The user subsequently authorized implementation, the focused corrective extensions and separate task commits. Every numbered task has one dedicated commit; verify and archive before creating this change's PR, preserve full PR CI, and wait for explicit approval before a merge commit into main. No unresolved product or business decisions are introduced.
