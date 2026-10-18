> Historical verification of the original 18 tasks. The plan is reopened: main PR #3 integration (task 3.14) and renewed acceptance (task 4.4) are pending. This report does not establish current archive readiness.

# Verification: test-performance-templates

Date: 2026-10-18. Branch: `codex/test-performance-templates`.

## Scorecard

| Dimension | Result |
| --- | --- |
| Completeness | All 18 numbered tasks complete with this verification task; 3/3 added or modified requirements implemented. |
| Correctness | All 7 delta scenarios mapped to implementation and regression evidence below; complete four-mode acceptance passes. |
| Coherence | Worker-owned migration-only templates, bounded scheduling, strict completion and aggregate coverage follow the design; approved UI/storage extensions are documented. |

No critical issues, warnings or suggestions from this verification. All applicable local verification checks passed. Ready for archive. Full final-revision PR CI and explicit merge approval remain delivery gates, not completed local checks. No local Sonar analysis is claimed; remote quality checks will be inspected on the concrete PR.

## Requirement and scenario mapping

- **Navigation blanks unfinished destinations / Slow destination:** `app/presentation/components/page_transition.py` begins blanking synchronously; `tests/test_page_transition_browser.py::test_navigation_blanks_old_page_until_destination_ready` samples unfinished frames and verifies ordinary/coalesced modes.
- **Completed destinations become visible / Coalesced running state:** `mark_page_rendered()` and `app/presentation/shell.py::_render_application_page` acknowledge completed rendering, retaining idle/skeleton/two-frame readiness. The same browser regression and `tests/test_page_transition.cjs` cover completed rendering without observed running and old-content rejection. Task 3.9 evidence records the failing old implementation.
- **New navigation supersedes a pending reveal:** navigation generation invalidates stale animation callbacks; Node regressions retain hidden state until the later destination completes.
- **Existing fragment navigation responses:** `test_chart_navigation_shows_loading_and_clears_it_after_completion` covers both full rerun and inaccessible fragment destinations, retaining observed-run fallback.
- **Unchanged WBS shares do not add global save contention / Ten independent title saves:** original `tests/postgresql/test_project_save_concurrency.py` remains byte-for-byte unchanged from main and passes all full modes. Migration 0069 reserves physical update headroom without altering business logic or retry policy.
- **Clear or retain authorized shares:** existing independent-save, WBS, security and allocation-integrity regressions remain unchanged; all pass in complete runs. No global capacity validation or authorization is bypassed.
- **Upgrade a populated project portfolio:** `tests/postgresql/test_project_update_headroom.py` covers clean HOT updates and populated upgrade/reentry/atomic rollback. Records, WBS, cache revisions, constraints, RLS/policies, privileges and prior ledger timestamps/checksums are preserved. The transaction-local HOT assertion fails without the storage repair. Upgrade and rollback fixtures remain genuinely unmigrated before setup.

## Complete acceptance and final-source reconciliation

See [measurement.md](measurement.md), [measurements.json](measurements.json) and [evidence.md](evidence.md) for exact commands, fixed inputs, versions, raw sanitized summaries, diagnostic failures and causal limits.

All nine interleaved cohorts pass identical 54-case manifests. Median migrated preparation improves from 21.619483s to 6.977939s: **67.72% lower**, passing the 50% target.

| Full mode | Monitored wall | Outcomes | Coverage |
| --- | ---: | --- | ---: |
| Fresh / serial | 2537.813874s (42m18s) | 3304 + 5 subtests | 97.684720% |
| Template / serial | 2123.056248s (35m23s) | 3304 + 5 subtests | 97.684720% |
| Template / two workers, first | 1277.208545s (21m17s) | 3304 + 5 subtests | 97.684720% |
| Template / two workers, repeat | 1243.467171s (20m43s) | 3304 + 5 subtests | 97.684720% |

Use the slower optimized run: **49.67% lower** full wall time, passing the 25% target. No absolute seven-minute target applies. All four runs execute 112 Node cases successfully, no skips/retries/restarts, exactly one setup/call/teardown per canonical case, 2261 migrated preparations, and zero remaining test databases/other clients. Coverage matches per file: 16539/16931 statements, 283 files, 499 excluded lines. Both workers execute real work; sampled client peaks 23/24 remain within the 40-client budget.

Measured source is revision `09b57a6` plus three explicitly fixed task-4.1 measurement inputs subsequently committed in `7cd8aef`; this is not described as a pristine revision. Task 4.2 changes only selection defaults, workflow flags and documentation. Its template/two-worker flags exactly match measured C; no application/test assertions or coverage scope changed after acceptance. Parsed workflow invariants pass, 57 selection/gate/controller/real-fixture checks pass (17.31s), the implicit template default passes two real fixture cases (1.37s), and post-promotion collection matches all 3304 ordered IDs. Collection-only evidence is not treated as a full execution.

Local walls exclude provisioning/browser installation/image build and include resource sampling overhead. Docker samples can conservatively include another invocation; peaks are observations, not hard maxima. Hosted CI timing must be reported separately. Earlier failed/partial comparisons are diagnostic only and never count toward acceptance.

## Final inspection and checks

- `openspec validate test-performance-templates --strict`: passed.
- `git diff --check origin/main...HEAD`: passed.
- Reviewed proposal, design, both delta specs, task list, measurement/evidence and final application/workflow diff.
- All 68 historical migration files are unchanged from main; only migration 0069 is added. Transaction engine and original concurrency test are unchanged. No retry-limit, isolation, authorization or business-rule changes.
- Migration 0069 requires an operator maintenance window, exclusive table lock, temporary rebuild disk and increased steady project-table space. Applied ledger 69 requires fix-forward release recovery; older 68-migration binaries are not a supported downgrade.
- Template cleanup is exact ownership-based; migration-only sources are sealed, identities/security are initialized per clone, and isolation/fault/worker-crash regressions pass. Strict completion and combined worker/native-child coverage remain mandatory. Containerized OIDC remains a separate complete behavior gate.
- Full workflow retains unfiltered PR triggers, Python 3.14, fail-fast, real PostgreSQL/OIDC, all JavaScript checks and 95% aggregate coverage. Exactly two workers/loadgroup, no restart masking; serial/fresh diagnostics remain available.
- Unrelated user `.env.example` and `docker-compose.postgresql.yml` changes are excluded from commits.

## One focused commit per task

- `8ed38ab docs(test-performance-templates): complete task 1.1 performance plan`
- `078647e test(test-performance-templates): record complete serial fresh-database reference (task 1.2)`
- `959714c test(test-performance-templates): own migrated templates and disposable clone lifecycles (task 2.1)`
- `46bcae6 test(test-performance-templates): select fresh or cloned PostgreSQL fixture preparation (task 2.2)`
- `db1ff84 test(test-performance-templates): prove clone security cache and process cleanup isolation (task 2.3)`
- `9c05ad2 test(test-performance-templates): aggregate strict collection and outcomes across bounded workers (task 3.1)`
- `d0139a7 test(test-performance-templates): bound scheduling and serialize shared benchmark observations (task 3.2)`
- `980180f test(test-performance-templates): prove combined worker and native subprocess application coverage (task 3.3)`
- `c052f7c test(test-performance-templates): observe backend shutdown within a bounded deadline (task 3.4)`
- `779f0b2 test(test-performance-templates): wait for dashboard table selection acknowledgement (task 3.5)`
- `55a517f test(test-performance-templates): acknowledge organization filter completion and rendered selections (task 3.6)`
- `bc1f4ba test(test-performance-templates): await native completion before finance selections (task 3.7)`
- `ba24367 test(test-performance-templates): await published project form events before assertions (task 3.8)`
- `f8d7c0e test(test-performance-templates): restore completed navigation visibility (task 3.9)`
- `09b57a6 test(test-performance-templates): reserve project title update headroom (task 3.10)`
- `7cd8aef test(test-performance-templates): verify complete performance acceptance (task 4.1)`
- `2ce4bd3 test(test-performance-templates): enable verified template and two-worker CI (task 4.2)`
- Task 4.3: this verification commit (its own hash is intentionally not embedded).

Historical reconciliation merge commits preserve prerequisite setup history. Archive/spec synchronization is a separate lifecycle commit, outside numbered tasks. Setup PR #1 was approved and merged separately; this PR requires its own approval.

## Remaining delivery

Sync the two approved capability deltas, archive all completed artifacts, create and attach the PR to main, and require full automatic CI on its final archived revision. Do not merge before the user approves that concrete PR; use a merge commit preserving all task commits.
