# File watching and first-load latency

Date: 2026-09-10. Application baseline: `05d2064`, with the accepted compact
authorization cache and the original all-page startup composition.

## Experiment

Compare `--server.fileWatcherType=auto` with `--server.fileWatcherType=none` in
alternating order: auto-1, none-1, auto-2, none-2. Each run recreates only the app
container and starts a fresh headless Chromium context. Keycloak and business
data are retained. Container entrypoint inspection verifies the actual CLI flag.
The image includes watchdog. No assumption is made that every watcher thread
uses the same backend.

The temporary `.local/watcher-benchmark.yml` overlay changes only that CLI flag.
Both variants use the same Python 3.14 / Streamlit 1.63 application, authorization,
cache settings, read-only code mounts, 1500-pixel browser viewport and local
administrator role. No profiling hooks or competing tests run during measurement.
Browser sessions log out afterward; no business records are edited.

`.local/compare_page_startup.py` measures the initial authenticated app document
request through visible Portfolio rows and script completion, then first and
repeat navigation through Planning, Settings, Application Access and Portfolio.
Initial loading includes browser assets but excludes identity-provider login time.
Gantt readiness additionally waits for the iframe and project summaries.

After each navigation run, `.local/measure_project_details.py` opens projects
1, 2, 5, 1 in a new browser session. Its first selection is the first project-detail
panel opened since container restart, although the application has already been
navigated. Details timing includes a 200 ms settling interval and browser polling.

## Results

Medians across the two runs per variant, seconds:

| Operation | Watching enabled (`auto`) | Watching disabled (`none`) |
|---|---:|---:|
| Initial Portfolio visible and ready | 7.324 | 4.504 |
| First Planning script complete/browser idle | 3.788 | 2.340 |
| First Gantt chart ready | 4.296 | 2.586 |
| First Settings visit | 0.571 | 0.577 |
| First Application Access visit | 0.539 | 0.462 |
| First project-detail selection | 3.206 | 1.402 |
| Warm project-detail selection (six samples) | 1.117 | 1.141 |
| Repeat Gantt chart ready | 1.412 | 1.421 |

Initial Portfolio improved by about 39%, first Gantt readiness by 40%, and first
project-detail selection by 56%. The substantial first-load improvement repeated
in both alternating pairs. Warm timings remain similar; their small differences
are within the variation of this browser benchmark. This is a local Docker/Windows
development measurement, not a production or multi-user load-test guarantee.

Raw samples, milliseconds, `auto` / `none`:

- Initial Portfolio ready: `[7591,7057]` / `[4512,4496]`.
- Initial script finished: `[7349,6888]` / `[4109,4043]`.
- First Planning ready: `[3754,3821]` / `[2164,2516]`.
- First Planning script finished: `[3727,3796]` / `[2132,2066]`.
- First Gantt ready: `[4315,4277]` / `[2619,2552]`.
- First Settings: `[504,638]` / `[572,581]`.
- First Access: `[505,573]` / `[476,448]`.
- First return to Portfolio: `[512,491]` / `[459,489]`.
- Repeat Planning ready: `[592,547]` / `[568,626]`.
- Repeat Gantt ready: `[1415,1408]` / `[1432,1409]`.
- Repeat Settings: `[658,576]` / `[589,598]`.
- Repeat Access: `[476,440]` / `[465,449]`.
- Repeat Portfolio: `[465,445]` / `[450,441]`.
- First detail selection: `[3211,3200]` / `[1662,1141]`.
- First detail UI message span: `[2301,2212]` / `[503,434]`.
- Warm detail selections: `[1119,1115,1129,1130,1114,1114]` /
  `[1126,1149,1136,1195,1145,1130]`.

Every startup rendered 35 UI deltas including 19 sidebar deltas. Subsequent page
navigation and project selection emitted zero sidebar deltas. Detail selections
retained the same 21/22-message structure. No Streamlit exceptions were reported.

Recommendation: use `APP_RUN_MODE=demo` for app evaluation/demo use and
`APP_RUN_MODE=auto` for development. See [runtime modes](runtime-modes.md).
The measurements below preceded the parameterized launcher implementation.

## Functional verification

After activating the reusable no-watch overlay, the existing read-only browser
probes verified master-list jumps to indices 5,000, 2,500 and 7,500, then rapid
scrolling to 9,000. Visible rows appeared in 278, 295 and 238 ms; rapid scrolling
retained the original scrollbar and selected project summary.

Gantt expansion at indices 5,000 and 7,500 completed in 494 and 478 ms. Enabling
external links showed visible tasks in 448 ms. Expansion with external links
retained the viewport, and task batches returned HTTP 200. These operations
generated no Streamlit UI deltas. Dependency filters produced the expected 9/2/1
project results, one chart update each, and zero sidebar deltas. No UI exceptions
occurred, and session-activity throttling remained intact.

The no-watch overlay was activated in the development container for this evaluation.
No Python/application logic, authorization rules, database schema or default
Compose settings were changed for this experiment. The temporary overlay was
later replaced by the runtime-mode parameter. The browser workflows above provide
validation for this configuration-only change.

## Using the optional faster mode

Use the [runtime mode parameter](runtime-modes.md) with the existing local OIDC
configuration. The redundant no-watch overlay has been removed.

```powershell
$env:APP_RUN_MODE='demo'
docker compose --env-file .local/oidc.env -f docker-compose.yml -f docker-compose.oidc.yml up -d --no-deps --force-recreate app
```

After editing Python/component source, restart the app to pick up changes:

```powershell
docker compose --env-file .local/oidc.env -f docker-compose.yml -f docker-compose.oidc.yml restart app
```

Restore normal development file watching by resetting the mode and recreating:

```powershell
$env:APP_RUN_MODE='auto'
docker compose --env-file .local/oidc.env -f docker-compose.yml -f docker-compose.oidc.yml up -d --no-deps --force-recreate app
```

Disabling source watching does not disable widget callbacks, page navigation,
database updates or application reruns. It removes automatic source-change
detection. All-page startup and current server-side authorization are unchanged.
