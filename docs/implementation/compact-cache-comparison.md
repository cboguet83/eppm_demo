# Compact authorization cache key comparison

Date: 2026-09-10. Scope: the Streamlit `authorized_cache` wrapper only.

## Implementation

The wrapper still obtains the current trusted revision before **every** lookup,
including cache hits. It retains the caller revision and current revision in a
private tuple subclass and registers a type-specific SHA-256 fingerprint using
the existing `portfolio_revision_token` function. Cached functions still receive
the complete revision tuple. Database, epoch, business revision, security revision,
actor/session and the entire sorted project scope remain part of the fingerprint.
Other arguments, including template, language, query and pagination, retain their
existing hashing. Caller-supplied hash functions are preserved.

No session, permissions or access-scope results are cached by this change. The
repository revision contract, HTTP context tokens, TTLs, cache sizes and `.clear()`
behavior are unchanged. Existing entries are populated again under the new key.
Page initialization and lazy imports are outside this change.

## Reproducible cache benchmark

Run `python -m scripts.benchmark_authorized_cache`, or run that module inside the
development container. It compares the frozen original wrapper with the current
wrapper in the same process, using synthetic scopes and 31 warm calls after one
miss. It includes fingerprint construction, Streamlit lookup and deserialization.
It does not measure database authorization latency or browser rendering.

Container medians, Python 3.14 / Streamlit 1.63, milliseconds:

| Accessible projects | Cache configuration | Original | Compact |
|---:|---|---:|---:|
| 100 | Details/default hashing | 0.352 | 0.082 |
| 5,000 | Details/default hashing | 12.892 | 0.184 |
| 10,000 | Details/default hashing | 25.867 | 0.281 |
| 100 | Existing planning tuple hasher | 0.077 | 0.078 |
| 5,000 | Existing planning tuple hasher | 0.307 | 0.258 |
| 10,000 | Existing planning tuple hasher | 0.560 | 0.455 |

Each case performed 32 authorization checks and exactly one data calculation.
The earlier approximately 140 ms profile value included profiler overhead; it is
not an appropriate expected browser saving. The isolated improvement at 10,000
projects is about 26 ms per ordinary cached lookup.

## Browser comparison method

Use the existing local project-details, portfolio-paging, Gantt-loading and
Gantt-filter probes through `.local/compare_cache_browser.py`. The runner omits
historical CPU/SQL profilers and waits for the initial portfolio render to finish
before clicking navigation. An initial run without that wait failed to navigate
to Gantt and is excluded from timing comparisons. Existing probe sources remain
unchanged. Logins are temporary; probes log out and do not edit business records.

Both variants use the same development data, account role and 1500-pixel viewport.
Original and compact wrappers are tested in restarted application containers.
Repeated passes assess warm interactions. Details timing includes the existing
200 ms settling interval and Playwright polling, so it is a coarse measure.

Interactions: select projects 1, 2, 5, 1; jump the master list to indices 5,000,
2,500 and 7,500, then rapidly scroll to 9,000; expand Gantt rows around indices
5,000 and 7,500; enable external links around 2,500; expand with external links
around 9,000 and 1,000; filter Renovation Pilot #5 using all dependencies,
predecessors and this project.

## Browser results

Two successful passes per variant; medians in milliseconds. Warm details exclude
the first selection in each pass. Sample counts are per variant, not per project.

| Interaction | Samples | Original | Compact |
|---|---:|---:|---:|
| Warm project selection, including settling/polling | 6 | 1120.5 | 1118 |
| Warm details first-to-last UI message span | 6 | 459 | 415.5 |
| Master-list jump: visible rows ready | 6 | 287.5 | 266 |
| Rapid master scroll: ready after stopping | 2 | 643 | 548 |
| Gantt project expansion | 4 | 485.5 | 469 |
| Gantt expansion with external links | 4 | 443.5 | 442.5 |
| Enable external links: visible tasks ready | 2 | 453.5 | 423 |
| Filter project and all dependencies | 2 | 1483.5 | 1445.5 |
| Filter project and predecessors | 2 | 1701.5 | 1527 |
| Filter this project | 2 | 1809 | 1601.5 |

Individual original/compact samples, in pass order:

- Warm details: `[1112,1100,1113,1160,1156,1128]` /
  `[1132,1143,1111,1125,1100,1097]`.
- Master rows: `[275,276,254,322,344,299]` /
  `[306,283,300,243,242,249]`.
- Rapid scroll: `[605,681]` / `[693,403]`.
- Gantt expansion: `[798,432,488,483]` / `[436,445,515,493]`.
- Expansion with external links: `[445,441,482,442]` / `[410,462,461,424]`.
- Enable external links: `[462,445]` / `[413,433]`.
- Filter all: `[1419,1548]` / `[1480,1411]`.
- Filter predecessors: `[1618,1785]` / `[1531,1523]`.
- Filter this project: `[1601,2017]` / `[1460,1743]`.

The first selected project after app restart took 3215 ms with the original
wrapper; compact runs took 2669 and 3199 ms. This small sample does not establish
a cold-start improvement. In particular, the latest restart pair is essentially
unchanged. Do not attribute the browser differences entirely to cache hashing:
HTTP scheduling, browser polling and other live workload introduce variability.

Both variants preserved the master scrollbar and selected summary during rapid
scrolling. Gantt expansion/external loading generated zero Streamlit UI deltas
and retained the viewport. Each dependency filter emitted one chart update and
zero sidebar deltas. There were two script-finished cycles, the first with zero
deltas and the second with 16; this behavior is unchanged. Filter results remained
9 projects for all dependencies, 2 for predecessors, and 1 for this project.

## Validation and recommendation

- 35 cache/display/detail tests passed; the modified wrapper has 100% statement
  coverage in that targeted run.
- 294 additional Python tests passed for business transaction security, portfolio
  and planning HTTP, lazy planning, dependency filters and scoped UI workflows.
- 33 JavaScript tests passed for Gantt scrolling/permissions and the portfolio grid.
- Real database regression tests cover logout, expiry, disabled accounts,
  revocation, stable activity, scope expansion, business and template changes,
  isolation between actors, and current authorization on cache hits.
- Additional cases cover database/epoch/session/security revision separation,
  a change at the end of a 10,000-project scope, caller hash options and cache clear.

Recommendation: retain the small wrapper change for its measurable reduction in
server cache overhead. There is no reproducible scrolling regression in these
samples, but no large whole-screen improvement either. Address first-load
initialization separately. The compact version is left active in development;
no commit or business-data modification is part of this comparison.
