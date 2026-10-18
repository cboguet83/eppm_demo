# Verification: reusable-planning-component

Status: **passed; archived on 2026-10-18**. The OpenSpec verify-change workflow
checked the proposal, design, both deltas, all tracked tasks and implementation
evidence. All applicable checks passed; none were skipped or left unverified.

## Scorecard

| Dimension | Current finding |
| --- | --- |
| Completeness | 23/23 tasks complete. All 16 added requirements have implementation and test mappings below. |
| Correctness | All 35 scenarios map to module, mounted, installed or native regressions. The complete strict suite passed with real PostgreSQL and authenticated browsers, no skips, and 97.69% application coverage. |
| Coherence | Native modules, explicit host dependencies, instance ownership, portable packaging and thin EPPM integration follow the design. The user explicitly approved 150 ms synthetic / 60 ms native initial rendering on 2026-10-18; all other gates remain unchanged. |

There are no removed or renamed requirements in these deltas. Registry
publication and moving source to another repository are explicit non-goals.

## Findings

No critical issues, warnings or suggestions remain. No applicable check was
skipped. All 16 requirements and 35 scenarios have implementation/test mappings.

No separate code-pattern or requirement-implementation divergence was found in
the reviewed boundaries. Callback loading omitted during integration was found
by design comparison and corrected in task 5.7 rather than silently dropped.

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
| Upgrade/integration guidance | Package READMEs, packaging/integration/benchmark guides, ADR 0064 | Explicit contract/package versions, Python/Streamlit runtimes, installation/load/reset/disposal/error examples; incompatible versions reject safely |

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

## Current validation evidence

| Check | Actual result / limitation |
| --- | --- |
| All JavaScript entry checks and extracted modules | `node --test tests/test_*.cjs packages/planning-view/tests/*.test.js`: 307 passed, zero failures/skips |
| Pure module coverage | 117 checks passed. Contracts/owned messages/calendar/state/loading/resource models/dependency models have 100% statement coverage. Node aggregate includes unexecuted DOM renderers and is not claimed as browser coverage. |
| Mounted component/adapter/tooltip/header/accessibility | 44 passed in 58.71 s before callback correction; focused final EPPM group 11 passed in 14.51 s, including callback hydration/stale rejection |
| Standalone wrapper coverage | Wrapper + example/CLI: 46 passed, 275/275 statements, 100%, against an unchanged >=95% gate |
| Distribution and installed examples | 13 passed in 18.80 s after final callback/ownership changes; direct/rebuilt Python artifacts and plain browser archive |
| Native migrated baseline/filter/portfolio | Six passed in 52.41 s; exact baseline dimensions/color and business-history assertions retained |
| Native alternative resources/shared panels/diagnostic | Three passed in 38.61 s, including task edit and disposable source/copy cleanup |
| Final callback/bounded hydration/reruns | Seven passed in 18.33 s using real PostgreSQL; native driver now uses the actual queued callback fallback |
| Repeated benchmark | 25 final captures passed in 115.30 s on d3cfd24. Synthetic render medians 120.9/115.7/116.5 ms <=150 ms; native 42.7 ms <=60 ms. Other timing gates and all hard bounds passed. |
| Menu visual standard | Four focused checks passed in 5.38 s; computed panel/item/focus appearance matches the actual host CSS, with nested keyboard/viewport behavior retained |
| Assets/OpenSpec/diff | Canonical assembly `--check`, strict OpenSpec validation and `git diff --check` passed |
| Complete strict application suite | **3,334 passed, 5 subtests passed, zero skips in 2,738.66 s** on frozen source `ad15b55` and a matching Docker image. Real PostgreSQL + `EPPM_RUN_OIDC_E2E=1` + `--require-full-suite`; **16,944 app statements, 392 missed, 97.69% coverage** against unchanged >=95% gate |

The previous strict run used frozen source `8e065c4` and its matching Docker
image. It stopped with **1 failed, 1,932 passed and 5 subtests passed in 1,768.07
seconds** on an assertion requiring the obsolete inline Gantt menu stylesheet.
Task 5.8 restores matching scoped panel/item/focus styling and migrates that
consumer to a mounted computed-style comparison with the actual host standard;
its four focused checks passed in 5.38 seconds. That failed attempt is superseded by the complete passing run above.
The preceding run was cleanly interrupted after 1,316 passing tests in 1,107.76
seconds because the callback fix landed during execution; it cannot establish
coverage for a single final source revision.

The next strict attempt on `ad15b55` stopped after 685 passing tests in 521.62
seconds on the unchanged dashboard test's selection-clear assertion (expected
1,000 matching projects after deselection, still observed one). Both dashboard
browser tests then passed in isolation in 14.60 seconds. No dashboard code or
assertions were changed; the exact test passed three independent repeats (4.20, 4.17 and 4.26 seconds).
The subsequent complete strict run passed with the same dashboard code and assertions. The failed attempt is not counted as acceptance.

The earlier strict run stopped after 231 passing tests on a legacy native
resource selector. That consumer and the shared scenario consumer were migrated
with their assertions retained, then the strict run restarted. The earlier
17-capture interrupted/overlapping diagnostic is excluded from timing evidence.

The wrapper-only unit invocation initially reported 64% because it omitted the
shipped example/CLI tests; the complete wrapper/example gate above measures all
four shipped modules and passes at 100%, with no coverage-scope exclusion.

## Reproducible acceptance commands

Use the activated project Python 3.14 environment and ignored workflow test
configuration; no credentials belong in this record. This run used
`/home/cb2/Documents/work/eppm_demo/.venv/bin/python` from the isolated worktree
and read `/home/cb2/Documents/work/eppm_demo/.local/workflow-tests.env`. The
explicit local logs are `/tmp/planning-final-pytest-5.log`,
`/tmp/planning-final-node-4.log`, `/tmp/planning-final-wrapper-4.log`, and
`/tmp/planning-candidate-final.log`; the portable results are recorded here.

```bash
python -m scripts.build_planning_assets
docker build -t eppm-demo:local .
POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
EPPM_RUN_OIDC_E2E=1 python -m dotenv -f /home/cb2/Documents/work/eppm_demo/.local/workflow-tests.env run -- \
  python -m pytest -q --require-full-suite --cov=app --cov-fail-under=95
node --test tests/test_*.cjs packages/planning-view/tests/*.test.js
COVERAGE_FILE=.local/planning-wrapper.coverage python -m pytest -q \
  tests/test_planning_streamlit_wrapper.py tests/test_planning_example_host.py \
  --cov=streamlit_planning_view --cov-fail-under=95
python -m scripts.build_planning_assets --check
openspec validate reusable-planning-component --strict
```

Run the explicit five-repeat collector separately from the full suite and
database-copy checks, using a new ignored basetemp, as documented in the
benchmark procedure. Containerized OIDC behavior is a separate required gate;
it is not represented as host-process coverage.

## Delivery status

The feature branch and unrelated primary checkout remain separate. Verification
is complete; both capability deltas were synced with authored purposes and all
requirement/scenario blocks intact. The change is archived at
`openspec/changes/archive/2026-10-18-reusable-planning-component/`. All seven main
specs passed strict validation. PR delivery follows under the standing workflow. Registry
publication has not occurred. Merge requires the user's explicit approval of the
concrete PR and successful full CI on the final revision. Repository settings were inspected read-only: `main` is unprotected; merge,
squash and rebase methods are enabled. No settings were changed. This workflow
still requires explicit PR approval and a merge commit preserving task history.

## Task commits

The following evidence is from `git log main..HEAD --oneline` through acceptance.
The task 6.1 hash was added in this archive follow-up, after its commit existed.

```text
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


## Final assessment

All checks passed before archive. Specs are synced and the change is archived.
Full PR CI is an additional gate before requesting merge approval.
