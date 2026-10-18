# Planning component benchmark

Prepare canonical assets with `python -m scripts.build_planning_assets`.
Use Python 3.14 with the project's browser-tests extra and Playwright Chromium
installed. The Node driver discovers that Python environment's bundled
Playwright JavaScript driver; it installs no Node dependencies. Set
`EPPM_BENCHMARK_PYTHON` when the environment is not activated and
`EPPM_BENCHMARK_BROWSER` to select an absolute Chromium executable.

```bash
node scripts/benchmark_gantt.cjs
node scripts/benchmark_gantt.cjs --expanded
node scripts/benchmark_gantt.cjs --expanded --external-links
node scripts/benchmark_gantt.cjs --database --all-projects --expanded --move-task +  --env-file=.local/postgresql.env --client-container=eppm-workflow-tests-postgres-1
```

The optional first positional argument also selects Chromium. Every invocation
opens an isolated sandboxed headless browser at 1500 × 1100 and a temporary
loopback HTTP server serving only assembled component assets. It closes the
browser/server in its cleanup path. It uses the actual EPPM bootstrap and
Streamlit message boundary; no renderer globals or sliced implementation
functions are exposed.

The synthetic fixture retains 100 projects, 1,000 tasks, 127 pools and 730 dated
capacity/demand entries per pool, with five distant dependencies per task plus
adjacent task links. Required versioned-contract identities and project summaries
describe that same data. External links start disabled. Expansion, link toggles,
dependency inspection, scroll and Year fit checks use public controls and DOM.
The native configuration uses the real application on a disposable PostgreSQL
restore and the existing authorized callback fallback when no HTTP task endpoint
is supplied. It does not intercept or replace browser transport methods.
`--move-task` waits for predecessor choices and submits a real task editor;
receipt acknowledgements let the actual bridge queue progress.

JSON output includes initial render time around synchronous render-message
delivery, scroll-frame p95, scroll-work p95/max, live rows/cells and dependency
path counts, bundle inspection, pane alignment and fit geometry. Styles are
loaded before timing, as in the original inline-style component. Scroll work
times callbacks at the browser's public animation-frame boundary, including all
workspace renderers; the reference instrumented its timeline callback alone.
Frame intervals and work durations are distinct metrics. `tasks` records initial
payload tasks; `visibleTasks` records mounted task rows.

Hard checks require positive resource rows/cells, at most 40 resource rows,
pane alignment within one pixel, inspectable bundle members and equal timeline/
resource viewport widths with a filled calendar. Scrolling the resource pane
dispatches its ordinary DOM scroll event before awaiting frame reconciliation.
Snapshots, identity provisioning and database restoration are outside render
timing; host timings and JSON payload sizes are reported separately.

Run `tests/postgresql/capture_gantt_reference.py` explicitly to collect five
repeats of collapsed, expanded, external-link, native render and native host-edit
configurations. Use a new ignored `--basetemp` directory. Run this collector
sequentially with other database benchmark tests: their global disposable-copy
cleanup assertions must not overlap, and timing captures need an idle host.
An interrupted run or a run concurrent with the full suite is diagnostic
evidence only. For this extraction the user explicitly approved initial-render
median limits of 150 ms synthetic / 60 ms native on 2026-10-18. Retain the
design's 10% **and** 5 ms median-regression gate for other applicable timings,
and keep all row, alignment, loading and geometry hard bounds unchanged.

The mounted driver retains current main's bounded startup diagnostics through
Playwright: launch is limited to 20 seconds, early exit rejects promptly, and
only allowlisted exit/signal/spawn metadata and reason categories are reported.
Raw child output, paths and launch arguments are withheld; sandbox settings are
unchanged. Native installed-consumer modules share the audited heavy-worker
group under the two-worker full-suite configuration.
