# Final verification: test-performance-templates

Date: 2026-10-19. Dedicated branch: codex/test-performance-templates. Renewed task 4.4 acceptance uses clean committed source 9ee483625a316e481ccc506b435205690f302bd9. Later verification/archive changes are documentation/lifecycle only.

## Scorecard

| Dimension | Result |
| --- | --- |
| Completeness | 27/27 numbered tasks complete with this verification commit; each has a dedicated commit. All three capability requirements and seven scenarios are covered. |
| Correctness | Nine preparation cohorts and four full strict runs pass on identical app/test/script/config bytes and the same immutable application image. Coverage remains above 95% in every mode. |
| Coherence | Worker-owned migration templates, isolated clones, bounded loadgroup workers, strict completion and aggregate subprocess coverage follow the design. Approved navigation/storage changes are already on main through PR #2; this follow-up adds test readiness, bounded diagnostic browser shutdown, completed organization views and final evidence. |

No critical implementation/spec mismatch was found. Accepted limitation: the original hosted missing-row and Chrome startup causes remain unknown. The user explicitly approved bounded readiness hardening without a proven original root cause. This limitation is not hidden by passing repeats or described as a causal fix. Final archived-head hosted CI/Sonar and explicit approval of the follow-up PR remain delivery gates.

## Actual complete acceptance

| Mode | Canonical cases | Subtests | Statement coverage | Monitored wall seconds |
| --- | ---: | ---: | ---: | ---: |
| full-A | 3489 | 5 | 97.707200% | 2706.244404 |
| full-B | 3489 | 5 | 97.707200% | 2060.796884 |
| full-C-1 | 3489 | 5 | 97.707200% | 1135.924798 |
| full-C-2 | 3489 | 5 | 97.707200% | 1151.056192 |

Median preparation reduction is 66.86% (required ≥50%). Using the slower successful parallel run, full wall reduction is 57.47% (required ≥25%). No absolute seven-minute limit applies.
Every canonical case has exactly one successful setup, call and teardown; subtests pass. Both workers execute real cases. No required skips, deselection, missing reports, retries or worker restarts are accepted. All four runs pass all 338 Node cases (221 root and 117 package) with no fail/cancel/skip/TODO and generated-asset checks. Coverage source/statement/exclusion maps match; missing-line variation, if any, is retained in measurements.json. Every mode ends with zero owned databases and zero other clients on the dedicated service, within the conservative 40-client budget. See measurement.md and measurements.json for exact timings, versions, image/source hashes, resources, limitations and raw-log location.

Full command: python -m pytest -q -x -p no:cacheprovider -p tests.performance.template_metrics --max-worker-restart=0 MODE --require-full-suite --cov=app --cov-config=pyproject.toml --cov-report=json:RUN/coverage.json --cov-fail-under=95, with fresh per-run COVERAGE_FILE and metrics directory, real isolated PostgreSQL and EPPM_RUN_OIDC_E2E=1. MODE is serial/fresh, serial/template or two-worker/template/loadgroup. The harness runs each mode sequentially with frozen versions/source/image and checks all phase outcomes. JavaScript: node --test tests/test_*.cjs and node --test packages/planning-view/tests/*.test.js; generated assets: python -m scripts.build_planning_assets --check. The opt-in sampler records overhead separately from build/provisioning; hosted timings are not substituted for local comparisons.

## Requirement and scenario mapping

- Navigation blanks unfinished destinations / Slow destination: page_transition.py begins blanking synchronously; test_page_transition_browser.py checks slow destination blanking in ordinary/coalesced-running modes.
- Completed destinations become visible / Coalesced running state: mark_page_rendered and shell destination acknowledgement retain idle/skeleton/two-frame readiness; controlled real-browser and Node tests verify reveal without transient running and reject old content.
- New navigation supersedes a pending reveal: navigation generations invalidate earlier animation callbacks; Node regressions retain blanking for the later destination.
- Existing fragment navigation responses: ordinary full-rerun and inaccessible-destination fragment cases retain all navigation assertions.
- Unchanged WBS shares do not add global save contention / Ten independent title saves: the original small and 10,001-project concurrent-save workloads retain all assertions and pass in all four complete runs. Forward migration 0071 reserves physical headroom without changing isolation/retry/business rules.
- Clear or retain authorized shares: existing WBS, security, authorization and allocation-integrity tests pass in every complete mode; no global capacity or access checks are bypassed.
- Upgrade a populated project portfolio: headroom clean-install/HOT, populated 70-to-71 upgrade/reentry and atomic rollback tests preserve records, WBS, caches, constraints, RLS/policies, privileges and prior ledger checksums/timestamps. Important migration tests still use genuinely empty databases.

Inherited reusable-planning-component ADR 0065/package/host boundaries from main PR #4 and shared-business-dictionary requirements/decisions from PR #3 remain unchanged; the full suite includes their schema, locale, RLS, repository, browser and upgrade tests. No new architecture/business decision is introduced by this follow-up.

## Readiness evidence and causal uncertainty

Task 3.15 retains every original restoration assertion and uses the existing unchanged 10-second completion bound before initial-tree interaction and around the visibility-toggle rerun. Its two-second delayed-initial-completion case observes the actual outbound checkbox request. Before the guard it fails in 5.22s at completion count zero, while the original popup/deleted-record assertions still pass. After the guard: fresh focused 15/13.78s, parallel/template with real peers 31/14.10s, diagnostic/completion unit checks 9/0.29s, final serial/template 16/15.08s. A separate privacy regression retains only the first matching request state, never raw widget data. Existing missing/error/early-rerun acknowledgement tests preserve bounded failure.
This proves a readiness precondition gap, not the original hosted missing-Alpha symptom. Thirty pristine and 100 instrumented repetitions plus later green hosted runs did not establish the original cause. Failure notes remain credential-free and preserve originating exceptions. The startup helper separately proves early-child-exit detection with the same timeout/sandbox policy; it does not identify the original hosted Chrome failure cause.

## Diagnostic shutdown regression

Task 3.16 reproduces the post-report 120-second timeout by suppressing only Browser.close acknowledgement while the real browser exits. The repaired helper requires actual clean process exit within the existing 1,000ms grace period and removes its listeners/timer; an acknowledgement alone cannot accept a live browser. The real ignored-close case still fails and removes only its own database copy, retaining original source snapshots. Focused fresh 16/37.06s, parallel/template with ordinary peers 32/30.89s and all 134 Node checks pass. The original natural missing acknowledgement was not captured, so the controlled defect is distinguished from unproven original event ordering.

## Organization view completion regression

Task 3.17 reproduces the exact duplicate-manager-summary CSS failure by delaying the test-owned page tail after its caption (RED 9.09s). The helper now requires actual successful script completion and advancing unique captions; explicit exact-one frame/detail/summary readiness precedes unchanged strict assertions. A persistent extra manager still fails after 30 seconds (negative probe passes 37.57s). Shared-filter serial/template four cases pass 36.87s; fresh plus completion regressions eight/36.24s; both affected browser modules with peers 23 parallel/template cases/60.06s; nine repeated ordinary/frame/page-tail cases pass in 89.10s; adapted dashboard fresh three/25.38s. All original assertions in both modules are retained. No application change or last-element fallback is used.

## Main PR #4 integration

Task 3.18 integrates 47897b7 with a dedicated merge commit. Keep all upstream package assets, --move-task, DTO editing and expanded CI assertions. Public BrowserServer process ownership preserves bounded actual shutdown and loopback binding; nested finally closes native stdin even when browser cleanup fails. A controlled old-finally mutation reproduces the native-session leak; the fixed version fails promptly and preserves source snapshots/copy cleanup. Fresh isolated artifact interpreters repair reproduced local editable-finder leakage without removing original assertions. Focused verification: 221 root + 117 package JS, asset assembly/checks, 82 packaging/model/scheduling checks in 28.17s and 48 affected parallel native/browser cases in 110.79s. Full acceptance uses rebuilt image and canonical package/build input fingerprints. The prior fca42c8 series passed 3,373 + five subtests and 97.70% coverage with 58.17% wall / 67.50% preparation reduction; it is historical because main advanced during it.

## Preservation and final review

All migration/companion bytes and application/CI files match main 47897b7 in this follow-up. Three diagnostic scripts adapt the owned-browser lifecycle to the mounted public planning renderer; installed-wheel test interpreters exclude editable hooks while preserving every import-path assertion. The original 70 released migrations were preserved during main integration, and unpublished headroom SQL moved to 0071 without a byte change. No applied migration is rewritten. The new diff changes only browser tests, diagnostic shutdown tooling, privacy/regression tests, OpenSpec evidence and archive lifecycle. User .env.example and docker-compose.postgresql.yml edits are excluded/preserved. No credentials, logs with raw protocol data, generated database files or dependencies are committed.
Strict change validation, strict validation of all main specs, task/source/diff review and task-specific regression checks passed before archive. Full PR workflow retains unfiltered pull_request triggers, Python 3.14, fail-fast, real PostgreSQL/OIDC, exactly two loadgroup workers, no restarts, all JavaScript checks and the same 95% aggregate gate. No local Sonar analysis is claimed; inspect the actual remote SonarCloud check on the follow-up PR.

## Commit discipline

| Task | Dedicated commit |
| --- | --- |
| 1.1 | 8ed38ab |
| 1.2 | 078647e |
| 2.1 | 959714c |
| 2.2 | 46bcae6 |
| 2.3 | db1ff84 |
| 3.1 | 9c05ad2 |
| 3.2 | d0139a7 |
| 3.3 | 980180f |
| 3.4 | c052f7c |
| 3.5 | 779f0b2 |
| 3.6 | 55a517f |
| 3.7 | bc1f4ba |
| 3.8 | ba24367 |
| 3.9 | f8d7c0e |
| 3.10 | 09b57a6 |
| 3.11 | 34b0fb1 |
| 3.12 | 207f65b |
| 3.13 | 98f1f6d |
| 3.14 | 1ec6560 |
| 3.15 | 557983f |
| 3.16 | 20b0fff |
| 3.17 | fca42c8 |
| 3.18 | 9ee4836 |
| 4.1 | 7cd8aef |
| 4.2 | 2ce4bd3 |
| 4.3 | 00b9ce4 |
| 4.4 | This verification commit |

Archive/spec synchronization is a separate lifecycle commit. Earlier archive b05b861 and reopening 5e73174 remain historical; task commits and main reconciliation merges are not rewritten.

## Delivery state

PR #1 was merged with explicit approval. GitHub reports cboguet83 merged PR #2 on 2026-10-18 at 11:04:58 UTC with merge commit 664f72a, containing 1ec6560. Its full CI/Sonar passed 3,368 tests + five subtests, 97.70% coverage and 124 Node cases (pytest 18m58s / whole job 20m53s). This merge was discovered after task 3.15; earlier statements that PR #2 remained draft reflected stale information and are superseded here. The new readiness commit was not in that merge.

Re-archive this completed change and create a follow-up PR targeting main. Require full automatic CI and SonarCloud on the final archived head; failed/missing gates block merge. Wait for explicit approval of that concrete follow-up PR, then use a merge commit preserving each task commit. No merge is authorized by this report.
