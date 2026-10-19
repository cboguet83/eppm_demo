# Design

## Context

See [proposal.md](proposal.md) for outcomes and [baseline.md](baseline.md) for
measurements and current defects. This cross-cutting tooling change needs a
design because test selection, GitHub check identity, readiness transitions,
and database startup must agree.

Existing seams are `scripts/` command modules, `tests/conftest.py`'s strict
completion gate, `tests/test_full_suite*.py` and `test_test_scheduling.py`'s
pytester/collection regressions, and the single GitHub workflow. Real database
tests already use per-worker migrated templates and disposable per-test clones;
unmigrated upgrade tests deliberately use empty databases. Keep those seams.

The source of truth for full execution remains pytest's repository discovery,
not a frozen list of the 3,489 currently measured cases. Only partial suites
need a maintained selection inventory. Main currently has no effective merge
protection; local policy alone cannot enforce the requested gate.

## Goals / Non-Goals

**Goals:**

- Make routine feedback cheap without making incomplete runs appear complete.
- Share one local/CI command contract and explicitly identify its scope.
- Make readiness and changed files select work deterministically; fail safely
  when classification, prerequisites, collection, or execution are incomplete.
- Enforce full acceptance on the current code PR revision before a merge.
- Make optional pgAdmin independent of database-only startup.

**Non-Goals:**

- No seven-minute full-suite limit, test deletion, migration replacement, or
  weaker security, concurrency, workload-size, or assertion coverage.
- No new test framework/dependency, speculative import-based impact engine,
  expanded worker policy, fixture redesign, or application behavior change.
- No nightly-only replacement for tests currently in full acceptance. No use
  of a developer's application database, credentials, or mutable shared state.

## Decisions

### 1. Explicit local commands and a maintained fast inventory

Add `python -m scripts.run_tests` with explicit `fast`, `targeted`, and `full`
subcommands. No subcommand should silently run the expensive suite. `targeted`
accepts explicit repository test paths/node IDs; it does not infer dependency
coverage. Use parsed subprocess argument lists, the active Python executable,
and the repository root. Propagate failures and interrupts. Provide a dry-run
or listing mode that exposes the actual commands/selection without secrets.

Maintain a versioned fast-module inventory, initially audited from the 70-module
candidate. Validate normalized repository-relative paths, duplicates, existence,
and safe fixture/resource dependencies. Root-level or `browser`/`performance`
filenames alone are not classification rules. A checked-in inventory audit
must detect new/unclassified modules and fast modules acquiring real database,
browser, Docker, deployment, or other service requirements. An unknown module
is never silently added to fast or omitted from full discovery. New tests in a
classified module are discovered normally. Full runs still include every module.

Fast runs use serial pytest without coverage by default and require no database,
Docker, Keycloak, or installed Chromium. They may use ordinary lightweight
temporary filesystem work and isolated mocks. Targeted integration/browser
runs explicitly need their normal isolated prerequisites. Clear summaries label
both modes as partial; even optional partial coverage is informational and
cannot satisfy `--cov-fail-under=95` acceptance or overwrite full evidence.

Keep both cheap JavaScript suites and generated-asset consistency in draft code
feedback. They are about one second in the measured hosted run, so building a
fine-grained JavaScript impact map adds little value. Avoid installing browser
tooling or building/starting containers in this lane. The ordinary Python dev
installation remains supported; optimize dependency setup only where supported
by current package boundaries, without adding a separate dependency system.

Alternative: a global `-m unit` default would require inventing and maintaining
a taxonomy that does not currently exist and could silently deselect new tests.
An explicit audited fast inventory is smaller and reviewable.

### 2. A canonical full entry point with unchanged acceptance

The `full` command runs the existing strict pytest command from the repository
root with complete `tests` discovery, followed by both JavaScript suites and
the generated-asset check. It requires the isolated environment provisioned by
the existing credential/operator commands and an up-to-date disposable test
image. Document preparation separately; never discover/load the application's
`.env` automatically or silently provision/reset a user's application database.

Keep Python 3.14, real PostgreSQL and authenticated browser deployment checks,
`--require-full-suite`, `--cov=app --cov-fail-under=95`, coverage subprocess
collection, `-n 2 --dist=loadgroup`, template mode, no worker restarts, and the
existing required-skip/completion checks. Preserve all source/exclusion settings.
Run the current root/package JavaScript commands and asset check on success;
any failure leaves acceptance failed. A failed/interrupted run is never proof.

Full mode must reject selection arguments, `-k`/`-m`, last-failed/deselection or
collection-only modes, and selection hidden in `PYTEST_ADDOPTS`; avoid arbitrary
pytest option forwarding. Validate the controlled configuration and reconcile
the unfiltered canonical collection with full serial/worker collection evidence,
normalizing only the audited xdist suffix. Keep meaningful regressions for
selection attempts that still include both required groups: the current strict
flag's group-presence check alone would accept those as a collection. Full
discovery must include newly added tests without updating a frozen case count.

Alternative: lower the coverage threshold or restrict its source to the fast
subset. Rejected because it changes the user's merge guarantee.

### 3. Conservative PR policy with no workflow-level path exclusion

Use a small tested policy helper, separate from test execution, to classify the
complete PR diff and event state. Record PR number, head SHA, base SHA, tested
merge SHA, selected lane, and reason. Read the actual Git diff using pinned
event revisions and sufficient history, including both old/new paths for
renames and deletions. Never rely on a truncated changed-files response or
commit-message/label conventions. Missing history, malformed data, conflicting
revisions, or an unavailable diff cannot select the documentation exemption.

Initially allow prose-only changes in `README.md`, Markdown under `docs/`, and
OpenSpec Markdown/change metadata. Explicitly exclude `AGENTS.md`, workflow and
test policy documentation such as `docs/development-workflow.md`, any document
consumed by generation/execution, scripts, templates, assets, and executable or
test configuration. Read existing consumers before finalizing the exact
allowlist. Only the exact `.openspec.yaml` metadata location may be considered;
never exempt arbitrary YAML, `openspec/config.yaml`, or generated skills. If a
prose path becomes an executable input, remove it from the exemption. Unknown
and mixed changes are code. A missing diff or invalid policy requires full
checks or a failing gate, never a successful shortcut.

| Change/event | Work | Required `tests` result |
| --- | --- | --- |
| Validated prose-only PR | Policy/inventory/document checks | Pass only when its expected checks pass |
| Draft code PR/update | Fast Python, both JavaScript suites, asset consistency | Explicitly blocked: full acceptance deferred |
| Ready code PR opened/reopened/marked ready/updated | Complete full acceptance | Pass only after all full gates pass |
| Test-selection, full-gate, or workflow-policy changes, even in a draft | Full acceptance plus policy regressions | Pass only after full gates pass |
| Missing/invalid diff or policy | Full acceptance if prerequisites can be established | Otherwise fail |
| Manual dispatch | Full diagnostic run for the selected revision | Separate check context; does not overwrite PR acceptance |

This is selective feedback by readiness and a narrow prose exemption, not a
claim that source-path heuristics prove all impacted integration behavior. Any
SQL, finance, authorization, application, dependency, test, or Compose change
requires full acceptance before it can merge. There is no label-based bypass.

Trigger PR checks for `main` on `opened`, `reopened`, `synchronize`,
`ready_for_review`, and `converted_to_draft`. Handle base retargeting through
the `edited` event as well: a changed base invalidates classification and full
acceptance. A title/body-only edit must neither launch another expensive run
nor publish a passing `tests` check. Use a separate explicitly named metadata
check context for such no-op events, including skipped-job cases; do not rely
on a skipped required job being a merge blocker. Validate this naming in the
workflow/policy regression matrix. Manual dispatch likewise uses its own
diagnostic context. Unexpected event shapes fail safely.

Use workflow-level concurrency keyed by repository/PR number, cancelling
obsolete PR runs including draft-to-ready transitions. Give manual diagnostics
a distinct key so they cannot cancel a PR acceptance run; metadata-only events
also need a distinct key and must not cancel an active full run. Keep read-only
test permissions and normal `pull_request` execution; do not introduce privileged
`pull_request_target` execution of PR code or expose administrative credentials.
Cleanup disposable resources on failure/cancellation.

### 4. Stable merge gate, revision identity, and remote enforcement

Preserve the required check name `tests`; move expensive execution into a
separate full job and give feedback its own clear name. An always-evaluated PR
gate must check the policy result and every job expected for that lane. Only
explicit success is acceptable for required jobs. Failed, cancelled, missing,
or unexpectedly skipped jobs block acceptance. Allow skips only for jobs the
validated policy says are not required. Policy failure cannot be hidden by
downstream conditional skips or a vacuous all-skipped workflow.

For a draft code PR, selective feedback can be green but `tests` must remain
unsuccessful with a clear "full acceptance deferred until ready" explanation.
This prevents a green draft result on the same SHA being reused while the
readiness-triggered full run is pending. Converting to draft must not publish
a new selective green merge gate. Preserve the identity of the revision/base
tested by each full run; do not accept stale-head, stale-base, manual-diagnostic,
or local-only reports. Test the readiness-without-code-change race explicitly.

Configure main protections during apply only after local gate regressions pass
and the existing `tests` context is confirmed. It is already the old workflow's
full job name, so requiring it does not depend on first merging a renamed
context. Preview the exact settings diff, preserve unrelated settings, then:

- Require PR-based changes and the GitHub Actions `tests` check, with the branch
  up to date before merging. Apply to administrators/avoid an ordinary direct
  push bypass, as supported by the repository's protection API.
- Keep merge commits enabled; disable squash/rebase merging and automatic
  merging. Avoid a linear-history requirement that conflicts with merge commits.
- Keep the user's explicit approval of the concrete PR as a separate delivery
  requirement. Do not equate a passing status or readiness with that approval,
  and do not introduce a review-count requirement that prevents a sole owner
  from following the agreed workflow.

Read back effective branch protection/rules and merge-method settings. Record
sanitized before/after evidence and required context identity. If administrative
permissions or platform constraints prevent enforcement, leave that task and
final acceptance incomplete; documentation is not a substitute. Existing
SonarCloud analysis remains intact; do not change its quality gate or secretly
remove an existing required check. No administrative token enters Actions jobs.

### 5. Isolate optional pgAdmin in a development overlay

Remove the pgAdmin service from `docker-compose.postgresql.yml` and place it in
an explicitly selected `docker-compose.pgadmin.yml` overlay, retaining an
explicit tools profile. Its credentials remain required only when that file
is selected. Declare the existing `pgadmin_data` logical named volume there;
retain `postgresql-data`, PostgreSQL 18.6, and loopback ports 5434/5050. Avoid a
fixed global container name so separate Compose projects can coexist. Use a
stable explicit project name in documented development commands to preserve
the intended volume identity.

Keep the isolated PostgreSQL test overlay and generated test environment free
of any pgAdmin requirement. Its current port list merges with the development
binding, leaving both 5434 and 15432 exposed. Make the test overlay explicitly
replace that list with its isolated 15432 binding, matching generated test
URLs; never take the development database's port or volume. Add config-only
regressions using dummy values and temporary ignored files, not real
credentials: database/test configuration
without pgAdmin variables succeeds, tools opt-in without credentials fails,
tools opt-in with dummy credentials succeeds and includes the declared volume,
and independent project names do not collide. Validate service/volume/port
contracts without printing rendered secret-bearing environments. Check the
full application overlay combination as well as standalone PostgreSQL; assert
the isolated test configuration exposes 15432 only, while application startup
retains 5434. Existing OIDC fixtures that reset database host ports stay isolated.

Update optional-tools startup instructions and safe variable placeholders. Do
not reset/recreate the existing application database, rewrite migrations, move
data volumes, or add pgAdmin credentials to CI just to satisfy interpolation.
Pin a compatible pgAdmin release/digest during apply after checking its official
image documentation; this does not add another application dependency.

Alternative: add dummy defaults or real pgAdmin credentials to every CI run.
Rejected because optional tools would still affect unrelated database startup.

## Risks / Trade-offs

- Fast feedback has incomplete coverage → label it partial, audit membership,
  and preserve the full ready-PR gate; the measured 7.5s is not an SLA.
- Ready code updates still cost a full run → keep work in draft while iterating,
  run targeted tests locally, and cancel superseded work. This plan reduces
  run frequency; it does not promise a faster complete integration suite.
- Draft merge gate appears unsuccessful → give feedback a separate green check
  and explain the intentionally deferred full acceptance in the summary/docs.
- Selection-policy regressions could create false green checks → force full
  validation of policy changes and test lane/job/result/revision combinations.
- Required-check changes can block other branches → preserve `tests`, record
  the settings diff, and verify read-back before claiming protection.
- Moving pgAdmin changes its launch command/container name → document the
  explicit overlay/project/profile and retain named volume/port contracts.
- A new required test module may slow fast checks → inventory review is explicit;
  full inclusion remains automatic and expensive cases need not enter fast.

## Migration Plan

Implement each numbered task on the existing feature branch with its own
commit, tests, documentation, and completion marker. First repair Compose
startup, then add local commands and full-mode protection, then selective CI
and remote enforcement. Update guides/timing evidence and complete strict full
acceptance on the final implementation before archive. Do not start a broad
serial/fresh/template comparison campaign; this change does not alter those
algorithms. Reuse diagnostic evidence only with its revision limitations.

Verify at least a docs-only decision, a normal draft code decision, a
draft-to-ready transition without a new commit, a subsequent ready revision,
a policy-change forced-full decision, failure/cancellation, base change, and
manual-dispatch isolation. Use deterministic subprocess/policy regressions and
the final real full suite; do not depend solely on reviewing YAML or wait to
discover the gate contract after archive. After archive and PR creation,
confirm the real hosted full check on the final PR revision before requesting
merge approval. Avoid temporary public PRs or pushing test commits solely to
simulate states unless the user specifically requests them.

If CI rollout fails, restore full-on-every-PR behavior and retain the required
`tests` check and 95% gate. Revert optional pgAdmin changes without touching
data volumes if necessary. Do not roll back by removing required protection,
lowering coverage, accepting stale proof, or bypassing user approval.

## References

- [GitHub PR event semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
  document the default PR event types and merge-ref execution; readiness needs
  an explicit trigger.
- [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
  documents concurrency and the pending-required-check problem with workflow
  path exclusions. Use job policy rather than excluding the required workflow.
- [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging)
  describe required checks and the strict up-to-date policy. Remote read-back
  is required evidence for enforcement.
