# Verification: reusable-planning-component

Status: **passed; ready for rearchive after consumer completion correction**. The OpenSpec verify-change workflow
checked completeness, all requirement/scenario mappings, design adherence and
code-pattern consistency against the integrated implementation. No applicable
check was skipped or left unverified.

## Scorecard

| Dimension | Final finding |
| --- | --- |
| Completeness | 28/28 tasks complete; all 16 added requirements implemented. No removed/renamed requirements. |
| Correctness | All 35 scenarios mapped below. Complete PostgreSQL/authenticated-browser acceptance passed with zero skips and 97.71% application coverage. |
| Coherence | Explicit host dependencies, independent lifecycle/state, canonical assets and thin EPPM integration follow the design. Approved initial-render limits and every unchanged timing/hard gate pass. |

No implementation/spec divergence or outstanding critical issue was found.
Prior failed/interrupted attempts are recorded below rather than counted as
acceptance. Registry publication and a separate repository remain non-goals.

## Requirements and scenario mapping

Each row covers every scenario under that requirement, in delta order.
Browser module paths below are relative to `packages/planning-view/src/`;
other paths are repository-relative.

| Added requirement | Implementation | Scenario evidence |
| --- | --- | --- |
| Synchronized timeline/resource periods | `calendar/index.js`, `workspace/index.js`, `resources/render.js` | Mounted scroll/splitter, column resizing, all scales and optional-resource layout in `tests/test_planning_component_browser.py`; benchmark Year fit/alignment |
| Inclusive calendar meaning | `calendar/index.js`, `timeline/render.js` | `models.test.js` leap/year/UTC–Luxembourg/move/resize cases; mounted inclusive bars and native milestones |
| Daily resource semantics | `resources/summary.js`, `resources/rows.js` | `models.test.js` exact daily pairs, zero/gap/full overrides, cache identity; `resource-grid.test.js` total/selected/comparison; Python-derived fixtures |
| Relevant state preservation | `state/store.js`, generic editors | `state.test.js` atomic update/reset/removal/draft/record identity; mounted rejected drafts, same-scope creation viewport and capability revocation |
| Dependencies/comparison identities | `timeline/rows.js`, `timeline/dependencies.js`, inspection renderer | Stable current/renamed/added/removed pairing, bundled and explicit unavailable endpoints; mounted markers/individual inspection; native baseline/alternative workflows |
| Bounded rendering/loading | `state/loader.js`, timeline/resource windows | Visible-before-overscan 25/100 tests, single flight, stale abort, explicit retry, resource two-dimensional windows, DOM retention and hard benchmark row/alignment bounds |
| Owned instance lifecycle | `workspace/lifetime.js`, mount/update/destroy | `lifetime.test.js`; mounted two-instance isolation, overlapping IDs, disposal during drag/read/tooltip, idempotent destroy/remount |
| Labels/actions and safe text | Controls, actions, menu/editor/tooltip modules | Flat capability validation, stale action guards, translated names, scoped theme/styles, markup displayed as text; mounted keyboard menus, hover cancellation and disabled comparison actions |
| Versioned validated host contract | `contracts/index.js`, `contracts/owned.js` | Opaque IDs, invalid versions/ranges, duplicate/cyclic identities, atomic rejection, independent copying, frozen ownership, aliases/accessors/prototype-key tests |
| Explicit host dependencies | Public mount/loader/event seam | Plain-web installed example, injected mounted lazy provider, independent wrapper/example import checks; no EPPM network dependency in the core |
| User intentions remain requests | Action controller and correlated responses | Exactly one drag/edit/extension intention, accepted/rejected previews, pending revision capture; host owns persistence/navigation/dialogs |
| Standalone Streamlit semantics | Generic bridge and Python wrapper | Queued action/read delivery, acknowledgements, cancellation, two keys, height/reruns; native standalone and installed-wheel consumers |
| EPPM behavior preserved | EPPM mapping/transport/bootstrap/commands/project panel | Current/alternative/baseline edits, resource filters/drill-through, CSV/tags/pools/details, shared-filter reset, stale project dependency drafts and callback fallback |
| Authoritative authorization/bounds | Existing Python callbacks/services/HTTP; EPPM presentation guards | Native HTTP/RLS/source-token/revocation/hidden-endpoint tests, 403/409 refresh, requested-token subsets, 25/100 retention; unchanged backend authority |
| Usable installed artifacts | Deterministic asset assembly, root/wrapper package resources | Direct/rebuilt wheels, source distributions, browser archive, exact manifests; two-instance edits/resources/lazy/unmount from outside checkout |
| Upgrade/integration guidance | Package READMEs, packaging/integration/benchmark guides, ADR 0065 | Explicit contract/package versions, Python/Streamlit runtimes, installation/load/reset/disposal/error examples; incompatible versions reject safely |

The detailed original-characterization-to-current-assertion table is in
`baseline.md`. Original JavaScript entry points are retained and import their
extracted assertion owners. Unrelated CSV/tab-position/action-table assertions
are unchanged.

## Boundary and diff review

The core has no EPPM/network/service imports and no executable HTML insertion.
Labels and opaque identities use DOM text/dataset assignments; generated menu
and SVG identifiers are instance-owned. The Streamlit bridge pins the actual
parent source/origin after a valid render. Queued requests retain correlation,
revision and cancellation checks; UI capability hints do not confer permission.
EPPM keeps its same-origin provider, source tokens, server-side authorization
and 25-request/100-retention bounds. No database schema, financial calculation,
service authorization or business lifecycle was moved into the packages.

The diff replaces the 7,511-line component with a 14-line module bootstrap,
focused EPPM presentation adapters and the shared package. Prepared copies are
ignored build products checked by manifests. Root/wrapper artifacts include
nested assets, Docker prepares them at build time, and consumers require no
Node runtime. Existing native assertions were migrated to public DOM/roles;
characterization meanings and hard bounds remain in `baseline.md`.

## Final validation evidence

Application/browser runtime remains `098f9b8`, including current main `664f72a`,
with the matching Docker image. The task 8.1 build correction and task 9.1 test-consumer sequencing were frozen
during renewed full acceptance. Subsequent edits are documentation/evidence only.
Python 3.14.7, Node 26.11.1 and installed Playwright 1.62 Chromium were used.

| Check | Actual result |
| --- | --- |
| Complete strict integrated suite | **3,484 passed + 5 subtests, zero skips in 1,556.86 s (25:56)**. Exactly two loadgroup workers, template-backed isolated PostgreSQL, authenticated browser deployments, no worker restarts and complete worker/collection proof. |
| Application coverage | **17,097 statements, 392 missed, 97.71%**; unchanged `app` source/exclusion scope and >=95% gate. Native host subprocess coverage included; containerized OIDC remains a separate behavior gate. |
| JavaScript | **324 passed, zero failures/skips**, including all original entry points, extracted modules and current-main startup/completion checks. |
| Independent wrapper/example coverage | **46 passed, 275/275 statements, 100%** against unchanged >=95% gate. |
| Affected mounted/browser regressions | **38 passed in 57.12 s**, including retained static control nodes, actual label updates, resources, menu appearance after real transitions, keyboard/viewport and EPPM behavior. All also execute in the complete suite. |
| Installed consumers/distributions | 15 focused distribution/consumer checks passed in 20.03 s, including isolated get-requires/editable hooks for root and wrapper without source-path insertion; direct/source-rebuilt wheels, browser archive and two-instance web/Streamlit examples also passed in the complete suite. No editable EPPM imports or startup frontend build. |
| Pure models | 117 focused checks passed; contracts/owned messages/calendar/state/loading/resource/dependency models have 100% statement coverage. This is not claimed as complete DOM-renderer coverage. |
| Five-repeat benchmark | **25 passed in 107.13 s**. Initial-render medians 121.1/118.8/124.0 ms synthetic and 39.8 ms native, below explicitly approved 150/60 ms. Maximum scroll work 8.9/8.6/9.4 ms and p95 1.5/1.7/1.6 ms pass the unchanged 10%-AND-5-ms rule. Rows <=40, cells positive, alignment 0 px and geometry/loading bounds pass. |
| Assets/specs/diff | Prepared-asset manifest check, selected-change strict validation, **all nine main specs strict validation**, and `git diff --check` passed. |

The final capture is `candidate.json`, including its asset-manifest hash. Its
runtime source matches task 7.3; task 7.2 records the already-existing commit
identity. `reference.json` remains unchanged. The first integrated capture is
retained as rejected evidence in `scroll-regression.json`.

## Reproduction

Run from the isolated checkout with the project Python 3.14 environment. This
execution used `/home/cb2/Documents/work/eppm_demo/.venv/bin/python` and read the
ignored `/home/cb2/Documents/work/eppm_demo/.local/workflow-tests.env`. No
credentials are included here.

```bash
python -m scripts.build_planning_assets
docker build -t eppm-demo:local .
POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
EPPM_BENCHMARK_BROWSER=/home/cb2/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome \
EPPM_RUN_OIDC_E2E=1 python -m dotenv \
  -f /home/cb2/Documents/work/eppm_demo/.local/workflow-tests.env run -- \
  python -m pytest -q -x -p no:cacheprovider --require-full-suite \
    --cov=app --cov-fail-under=95 -n 2 --dist=loadgroup \
    --postgres-test-db-mode=template --max-worker-restart=0
node --test tests/test_*.cjs packages/planning-view/tests/*.test.js
COVERAGE_FILE=.local/planning-wrapper.coverage python -m pytest -q \
  tests/test_planning_streamlit_wrapper.py tests/test_planning_example_host.py \
  --cov=streamlit_planning_view --cov-fail-under=95
python -m scripts.build_planning_assets --check
openspec validate reusable-planning-component --strict
openspec validate --specs --strict
```

The passing local full run additionally loaded a temporary diagnostic-only
`planning_failure_probe` through `-p`, with its ignored directory on PYTHONPATH.
It only prints already-received failed worker reports immediately; it does not
alter reports, collection, scheduling or gates. The observer and profiling
prototype were removed after success. CI uses the normal command above.
Run the explicit five-repeat collector separately from full-suite/database-copy
checks, with a new ignored basetemp, as documented in the benchmark procedure.

Portable results are recorded here; local logs are
`/tmp/planning-consumer-final-pytest.log`, `/tmp/planning-81-node.log`,
`/tmp/planning-81-wrapper.log`, `/tmp/planning-73-browser.log`, and
`/tmp/planning-candidate-scroll-fixed.log`.

## Earlier attempts and corrections

- Pre-integration acceptance passed 3,334 tests + 5 subtests, zero skips, 97.69%
  coverage in 2,738.66 s on `ad15b55`; it is historical evidence, not the final
  integrated result. Earlier runs stopped on legacy selectors (231 passed) and
  inline menu CSS (1,932 passed), corrected with retained mounted assertions.
  A 1,316-pass run was interrupted when callback code changed, and an overlapping
  17-capture diagnostic was excluded from timing evidence.
- An unchanged dashboard selection-clear assertion stopped a pre-integration
  run after 685 passes. It passed isolation and three independent repeats;
  current main subsequently supplied its event-acknowledgement timing fix.
- Current main advanced to `664f72a`, causing PR conflicts in dev dependencies
  and the benchmark driver. Task 7.1 merged it without rewriting task history,
  retained xdist plus standalone-build dependencies, ported bounded/sanitized
  browser startup to Playwright and classified new native modules in the
  existing heavy-worker group. Seven native integration checks and eight
  startup/scheduling checks passed. The planning ADR was renumbered to 0065,
  preserving main's already accepted 0064 dictionary decision.
- The first integrated 25-capture run passed hard assertions and initial render
  limits but failed collapsed maximum work (12.5 ms versus reference 6.9 ms).
  Task 7.3 removes static control/layout mutations on scrolling. Its mounted
  regression fails on the previous implementation and passes with the fix.
  Fresh final captures compare every timing metric, including maximum work;
  none was waived or selected from the rejected capture.
- The first integrated two-worker run reported an unchanged capacity-cache
  buffer failure (3,243 after unrelated tasks versus 3,038 before; +64 limit).
  It was gracefully interrupted after failure to surface a delayed report:
  1 failed, 659 passed in 549.74 s; not acceptance. Both cache kinds passed
  unchanged in template (23.64 s), fresh (23.39 s) and two-worker template mode
  (15.15 s). Isolated parallel buffers were planning 793 -> 793 and capacity
  3,038 -> 3,035. The full repeated command then passed. The cause was not
  established; no SQL, plan setting, assertion or tolerance was changed.

## Task commits and delivery

The focused ledger below is from `git log main..HEAD --oneline` filtered by the
change label, with `git log origin/main..HEAD --oneline` confirming the actual
PR base. Current main is an ancestor of the verified source. Task 9.1 contains the final consumer correction and renewed acceptance; its
own hash is recorded only by the subsequent archive follow-up.

```text
fc2db4a chore(reusable-planning-component): archive verified packaging correction
4abe570 fix(reusable-planning-component): complete task 8.1 isolated packaging hooks
3eab64d chore(reusable-planning-component): rearchive integrated verified change
ac8e6e2 test(reusable-planning-component): complete task 7.2 integrated acceptance
098f9b8 perf(reusable-planning-component): complete task 7.3 scroll DOM correction
05f87fe merge(reusable-planning-component): complete task 7.1 current main integration
ed80720 chore(reusable-planning-component): archive verified change and sync specs
46a2d3e test(reusable-planning-component): complete task 6.1 full acceptance
ad15b55 perf(reusable-planning-component): complete task 5.5 approved render budget
d3cfd24 fix(reusable-planning-component): complete task 5.8 shared menu visual parity
8e065c4 fix(reusable-planning-component): complete task 5.7 callback loading fallback
1102b34 test(reusable-planning-component): complete task 5.2 consumer migration
15ee772 fix(reusable-planning-component): complete task 5.6 validated ownership and parity
dc289f9 fix(reusable-planning-component): complete task 5.4 presentation parity
17f7fdd fix(reusable-planning-component): complete task 5.3 renderer retention and clipping
61d6c52 refactor(reusable-planning-component): complete task 5.1 EPPM integration
6fa2a98 docs(reusable-planning-component): complete task 4.3 installed consumer examples
663ffde build(reusable-planning-component): complete task 4.2 portable distributions
634df19 feat(reusable-planning-component): complete task 4.1 Streamlit adapter
cfaef61 fix(reusable-planning-component): complete task 2.4 calendar boundary parity
8d9a642 feat(reusable-planning-component): complete task 3.5 virtual resource grid
6630fee feat(reusable-planning-component): complete task 3.4 host interactions
7e9f082 feat(reusable-planning-component): complete task 3.3 dependency rendering
f8d620e feat(reusable-planning-component): complete task 3.2 virtual timeline
7995a61 feat(reusable-planning-component): complete task 3.1 workspace lifecycle
2c9a022 feat(reusable-planning-component): complete task 2.3 instance state loading
842c89a feat(reusable-planning-component): complete task 2.2 calendar resource models
e68f994 feat(reusable-planning-component): complete task 2.1 host contracts
3bfd15b test(reusable-planning-component): complete task 1.2 behavior reference
48386c9 docs(reusable-planning-component): complete task 1.1 extraction plan
```

PR: https://github.com/cboguet83/eppm_demo/pull/4. All 28 tasks are complete;
final acceptance is complete and the change is rearchived at
`openspec/changes/archive/2026-10-18-reusable-planning-component/`. Both capability
specs remain synced. Full CI on the final PR revision is an additional gate
before requesting merge approval. Registry publication and merge have not
occurred. The unrelated primary checkout was not edited.

Repository settings were inspected read-only: main was unprotected, and merge,
squash and rebase methods enabled. No administrative settings were changed. This
workflow still requires explicit approval of the concrete PR and a merge commit
preserving task history.

## Final assessment

All applicable implementation and packaging checks passed. Ready for rearchive; final PR CI must pass before merge approval is requested.

## Hosted packaging correction

Final-head CI run 39147420394 stopped in installation before tests:
setuptools' isolated get-requires-for-editable hook could not import `scripts`
from root setup.py. The standalone setup similarly imports `build_frontend`
through the source-root path. Local distribution helper `_backend` inserted
that path, masking the real hook environment. Task 8.1 removes the shortcut,
loads both trusted build validators by file path and verifies real metadata/
editable hooks plus complete acceptance before rearchive. Prior runtime/full
acceptance is retained as historical evidence; renewed acceptance below covers
the correction.

The two new isolated metadata regressions both failed before the fix (missing
`scripts` / `build_frontend`). Root and standalone setup now load their trusted
validators by file path with typed callable boundaries; no source import path
is added. All 15 distribution/installed-consumer checks pass in 20.03 seconds,
including get-requires/build-editable hooks without the old path insertion.
Prepared-asset validation is unchanged. Actual pip editable-install smoke tests
also passed for root and wrapper in disposable targets with --no-deps,
--no-index and existing local build tools (--no-build-isolation); no dependency
was downloaded or changed. The isolated Python -I hook tests separately prove
source-root imports are unnecessary. Complete renewed strict acceptance passed
3,483 tests + 5 subtests, zero skips, 97.71% app coverage in 1,248.42 seconds;
324 JavaScript checks and all 46 wrapper/example checks (100% coverage) pass.

## Hosted full-shell consumer completion

CI run 39149646724 on fc2db4a passed corrected installation, database setup and
image build, then stopped with 1 failed / 555 passed in 214.46 seconds. The
unchanged `test_dashboard_filter_spacing_in_full_shell` clicked Service A twice
while checking only Reset-filter color between clicks. The second toggle was
not reflected (Reset stayed red). Its sibling organization test already waits
for native completion and published service aria-pressed state; task 9.1 applies
that sequencing to the remaining full-shell consumer with delayed redraw
coverage, retaining all existing assertions. No dashboard business code changes.

Task 9.1 uses the existing ScriptCompletion protocol observer around state-changing
actions and checks Service A aria-pressed true/false before the next action.
All geometry/filter/color assertions and existing deadlines remain. Eight
organization/completion checks pass in 35.43 seconds, including immediate and
delayed full-shell redraws. Local delayed-only and pending-rerun probes did not
reproduce the original hosted failure; the CI trace is the observed red case.
No claim of a deterministic local reproduction or dashboard production fix is
made. Full renewed acceptance passed 3,484 tests + 5 subtests with zero skips and
97.71% application coverage in 1,556.86 seconds. All original full-shell
assertions remain, with stronger published-selection checks; no dashboard
production code, tolerance or timeout was changed.
