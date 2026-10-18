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

No existing capability delta is modified. Business, authorization and architecture requirements remain unchanged. Test safety and acceptance contracts are specified in design.md and tasks.md.

## Impact

Expected implementation areas: `tests/postgresql/conftest.py` and small test-only support modules, isolation regressions, `tests/conftest.py`, `tests/test_full_suite.py`, audited test scheduling markers, `pyproject.toml` development dependencies, `.github/workflows/tests.yml`, and `docs/development-workflow.md`. Add pytest-xdist as a development dependency only after Python 3.14 compatibility checks. No runtime dependency, applied migration, production schema, Docker security policy or business behavior change is planned. The user approved task 3.9 on 2026-10-18 to restore navigation readiness in `app/presentation/components/page_transition.py` and its shell completion marker, with controlled regressions. This narrow UI correction supersedes the original tooling-only exemption; its actual capability is specified rather than skipping specs.

Branch: `codex/test-performance-templates`, created from setup PR #1 head `393f4f571c9140942dc89a1cec51e3a8abec1cec` with explicit user authorization to depart from the usual main-branch starting point. PR #1 is a prerequisite and remains unmerged; its latest full CI failed, so this plan does not claim a green remote baseline. Implementation must first establish a clean baseline after upstream corrections. Preserve the existing unrelated local Compose port edit.

The current request authorizes this plan only. Applying requires a subsequent user request. Every numbered task has one dedicated commit; verify and archive before creating this change's PR, preserve full PR CI, and wait for explicit approval before a merge commit into main. No unresolved product or business decisions are introduced.
