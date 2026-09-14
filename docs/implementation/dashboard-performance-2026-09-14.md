# Dashboard allocation loading investigation — 14 September 2026

The main delay is the PostgreSQL resource aggregate, not SVG rendering. No
application code, persistent database settings, migrations, or business records
were changed during this investigation.

## Measurements

The live workload contained 1,000 projects, 780 In Progress projects, 7,424 tasks,
33 pools and approximately 1,350 assignments. Assignment counts changed during
the investigation; final query comparisons used one repeatable-read snapshot.
The default In Progress selection and the signed-in user's current authorization
were used. Session references and credentials were kept private in-process.

| Stage | Measured time |
| --- | ---: |
| Authorized resource service call | 2,187 ms |
| Project/filter catalog | 115 ms |
| Approved budget report | 9.45 ms |
| Proposed budget report | 9.18 ms |
| Revision/authorization lookup | 9.7–16.9 ms per call |
| In Progress filtering in Python | 0.5 ms |
| JSON encoding of aggregate result, approximately 126 KB | 0.9–1.9 ms |
| Both resource charts: JavaScript plus layout in Chromium | 19–54 ms |
| Both charts through two animation frames | 33–90 ms |

Browser measurements used the unchanged chart code and captured aggregate data
in a disposable headless Chromium page: 1,465 bars and 1,516 SVG child nodes.
They exclude Streamlit transport and page startup. Database timings varied with
local load; uncached authorized function measurements ranged roughly 2.2–4.4 s.

## Causes

1. `dashboard_resource_breakdown` expands intervals into roughly 111,782 daily
   comparison rows. One join replays roughly 8.5 million intermediate rows.
2. Quarterly results repeatedly scan intermediate daily datasets. Allocation and
   available-capacity projections separately scan comparisons for each of 33 pools.
   The measured plan recorded 38,458 temporary read blocks, approximately 300 MiB
   of repeated temporary-buffer reads; this is not a measurement of physical disk traffic.
3. PostgreSQL JIT compilation is enabled and adds startup work for this query.
4. The function calculates 80 quarters although the charts display 48. The Python
   component trims top-level rows after SQL, while pool maps still carry the larger range.
5. The chart cache has a five-minute TTL and uses the broad dashboard revision,
   including Finance and project changes. Unrelated changes can invalidate resource
   results. Every lookup also reauthorizes; that check should remain authoritative.

Finance is rendered before the resource query runs, explaining why its chart can
appear while the resource charts are still pending.

## Read-only experiments

Within one consistent snapshot, the actual authorized function with JIT enabled
took 4,376 ms. Setting `jit=off` **only for the diagnostic transaction** produced
2,408 and 2,439 ms with identical JSON output.

With JIT disabled, an extracted aggregate body took 2,229 ms. Combining merged
coverage intervals with a single grouped pool projection took 2,126 and 1,936 ms.
Adding a transaction-local 64 MB `work_mem` setting took 1,775 ms. The experiments
matched the complete baseline aggregate JSON in that snapshot. Merging coverage
intervals alone was slower (2,731–3,446 ms), so it is not recommended on its own.

These are local microbenchmarks, not end-to-end guarantees or multi-user results.
Production changes would need permission-scope, overlapping assignment, capacity
exception, peak-day, missing-period and concurrent-load regression checks.

## Recommended order

1. Benchmark a function-scoped JIT override, avoiding a global database change.
2. Compute pool allocation and availability together, group quarterly peaks once,
   and eliminate repeated scans. Tune memory for this operation only if it helps
   under concurrent load; do not raise global per-operation memory indiscriminately.
3. Bound calculation and serialized pool maps to the displayed 48-quarter range.
4. Give resource results a narrower revision key covering schedules, assignments,
   relevant capacity/calendars, selected project scope and access changes. Preserve
   authorization checks and immediate invalidation for relevant edits.
5. If further reduction is required, calculate at demand/capacity change boundaries
   rather than every day. Preserve exact daily peak semantics and earliest-day ties.
   This larger algorithm change has not yet been benchmarked.

Frontend rewrites, Canvas conversion, and extra base-table indexes are lower
priority: the measured base assignment scan is small and browser drawing is fast.
