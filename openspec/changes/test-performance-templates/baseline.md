# Initial serial fresh-database baseline

## Completed reference gate

The initial reference is full GitHub CI run [38927759504](https://github.com/cboguet83/eppm_demo/actions/runs/38927759504), setup revision `4b0d43e625b8b0cbe28188ed19efa11dfcf38232`. It executed every required group with the original migration-per-test fixture: **3,221 passed, five subtests passed, no failures/errors/skips, 2,329.46s (38m49s), 97.68% application statement coverage** (16,926 statements, 393 missing). All **108 JavaScript cases passed**, zero failures/skips. This is a completed serial/fresh baseline, not a partial run.

The runner used Ubuntu 24.04, Python 3.14.8, PostgreSQL 18.6, pytest 9.1.1, pytest-cov 7.1.0, coverage 7.16.2 and Playwright 1.62.0. It ran the unchanged full strict/95% CI command with real PostgreSQL and authenticated OIDC; no xdist was installed. Hosted VM CPU/memory measurements were not emitted by that workflow, so its timing must not be compared quantitatively against this developer machine.

Later CSV and chart browser synchronizations are test-only corrections, focused-verified in their own setup task commits. The application, migration bytes and coverage configuration at the completed reference equal the reconciled implementation base (`git diff 4b0d43e..HEAD -- app pyproject.toml` was empty before performance changes). The initial fixture inventory/migration fingerprint below therefore describes the same application baseline. The chart-delay regression adds one later test; final comparisons must regenerate the complete canonical manifest and run fresh/template/parallel modes against identical final test sources.

Task 1.2 uses this completed upstream reference. It does not claim that the final corrected setup revision has passed CI, nor that this hosted timing demonstrates a local optimization. That final setup CI and all final performance comparisons remain required. The isolated local reference continues as additional diagnostic verification. A short focused chart reproduction shared its host during that run, so its timing is not the controlled final speedup comparator; task 4.1 must use uncontended measurements.

## Additional local diagnostic reference

## Status

The first reference attempt failed after 858 passes in 812.43s at the employee CSV checkbox acknowledgment. Task 1.2 remains incomplete until a new full reference verification passes.
No partial or failed run is acceptance.

## Revision and environment

- First failed reference revision: `538f51daf765fef050444a74937d58f42e08294a`.
- Restarted reference revision: `a2c77dd08bb771cb71dfab2df08230c842a79efb`; includes the separately committed causal CSV test correction (`07d8513`, verification `1cce50d`).
- Explicit non-rewriting merge of setup corrections: setup head `4b0d43e625b8b0cbe28188ed19efa11dfcf38232`; task commits `eb28666` and `56f39a9`.
- Setup PR #1 remains unmerged. Its new full CI run is 38927759504; its result is not assumed.
- Python 3.14.7; pytest 9.1.1; pytest-cov 7.1.0; coverage 7.16.2; Playwright 1.62.0; pytest-xdist is not installed at reference start.
- Verification checkout: `/home/cb2/.codex/worktrees/performance-verification/eppm_demo`, detached at the exact reference revision. Source imports were checked against that root. Full comparisons will use committed snapshots so unrelated local Compose changes cannot alter a running measurement.
- Host: Linux 7.2.9-2-cachyos, x86_64; process CPU affinity count 8; physical memory 33162502144 bytes. Docker client 29.7.1, server 29.8.2, Compose 5.6.0; Docker VM eight CPUs and 8,026,890,240 bytes memory.
- Isolated server image PostgreSQL 18.6; `max_connections=100`; dedicated operator/runtime credentials and test-owned random databases. Native clients use only `eppm-workflow-tests-postgres-1`.
- Migration count: 68. Complete version/name/checksum ledger SHA-256: `b4930f80a2c4ce2e09c8735fe8cc06f0a3784b124047e03786595cee2ef488b0`.
- Canonical collected-node SHA-256: `da9a14665d355a91282b6283d6d991c3cdbe54bace732d746d231ccc1b87de18`.
- Read-only fixture-closure inventory: 3,221 collected tests, 2,248 requesting migrated databases and 46 requesting only empty databases. The two extra cases are the allocation form moving-option regressions. Inventory collection took 1.09s.
- The unrelated local Compose host-port edit is preserved and excluded. The existing isolated test service is reused on its established test port, without recreating user services or volumes.

## Command

```bash
cd /home/cb2/.codex/worktrees/performance-verification/eppm_demo
EPPM_RUN_OIDC_E2E=1 \
EPPM_BENCHMARK_BROWSER=<absolute-local-Chromium-executable> \
POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
COVERAGE_FILE=/home/cb2/Documents/work/eppm_demo/.local/performance-reference-v3.coverage \
/home/cb2/Documents/work/eppm_demo/.venv/bin/python -m dotenv \
  -f /home/cb2/Documents/work/eppm_demo/.local/workflow-tests.env run -- \
  /home/cb2/Documents/work/eppm_demo/.venv/bin/python /tmp/eppm-time-command.py \
  /home/cb2/Documents/work/eppm_demo/.venv/bin/python -m pytest -q -x \
  -p no:cacheprovider --require-full-suite --cov=app --cov-report=term \
  --cov-fail-under=95 --durations=30 \
  --junitxml=/home/cb2/Documents/work/eppm_demo/.local/performance-reference-v3.xml \
  -o junit_family=xunit1
node --test tests/test_*.cjs
```

The temporary standard-library timing wrapper runs the argument list with
`subprocess.run`, records monotonic wall time and child resource usage, and
preserves the test exit code. It does not modify sources or print credentials.
Native browser subprocesses remain included in host coverage. Containerized OIDC
is a required behavior gate, not a host coverage claim.

## Results

The second reference stopped after 758 passes and a recovery setup error in 561.20s. Compose rejected newly added unrelated local pgAdmin variable requirements before starting its isolated services; no source fix is needed. This attempt is not acceptance. Verification is moving to a clean committed checkout, preserving the user configuration. The clean-checkout recovery preflight passed in 159.76s. The third local diagnostic finished with 2,378 passes, five passing subtests and one organization-frame navigation failure in 2,360.80s (39m20s). It is not acceptance. It ran the frozen pre-optimization fixture code, and the prerequisite acknowledgment failure is being repaired separately. Node checks: ten passed, no failures/skips.
Sanitized setup/call/teardown timing and actual coverage will be recorded after
completion. Historical setup measurements are motivation only, not this run.
