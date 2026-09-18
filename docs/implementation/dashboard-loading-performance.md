# Dashboard load measurements and navigation feedback

Measured on the local application on 2026-09-18, with the default In Progress
filter: 780 projects and 33 relevant pools. These are observed timings, not
performance guarantees; database load and browser startup affect them.

## Findings and changes

The minimum-capacity aggregation rescanned every calendar for each of 80
quarters. Profiling recorded about 4.1 million date-format calls. Calendars now
pass through one quarter-bucketing calculation. Inclusive dates, explicit zero
capacity, baseline days and complete-quarter overrides retain their previous
meaning. Overallocation continues to use capacity on each actual demand date.

| Measurement | Before | After |
| --- | ---: | ---: |
| Uncached resource service, ordinary runs | 5.27–5.30 s | 4.64–4.85 s |
| Calendar minima + individual peaks, profiled runs | 1.53 s | 0.20 s |
| Clicked-pool consumer lookup, live browser | 4.77 s / 33 pools | 0.042 s / 1 pool |
| Chart-to-planning navigation, live browser | 9.73 s | 5.17 s |

Cached dashboard navigation took 0.89–1.39 seconds. The final first browser load
after an application restart took 12.19 seconds, including application/browser
startup. The chart stage accounted for 5.02 seconds in that run. The remaining
all-pool database aggregate query still takes approximately 4.3–5.0 seconds;
the optimization does not remove that bottleneck.

The chart context menu previously bypassed the loading overlay, which listened
only for sidebar navigation. Planning and pool-details actions now dispatch the
same navigation-start signal before submitting their Streamlit event. The
overlay appeared within 33–34 ms in the measured browser runs. Local pool-filter
actions do not start a page transition. Browser tests cover sidebar navigation,
chart navigation, completion, and a request that stays on the original page.

The selected-pool consumer lookup now passes a bound pool filter into the
existing authorized reader. It avoids computing unrelated pools while retaining
project-status filtering and visibility checks. No SQL calculation functions or
database migrations were introduced.

## Ongoing tracking

Application INFO logs expose:

- `dashboard.load`: stage and `elapsed_ms`, including cache authorization and
  lookup time. Stages include revision, catalog, filters, matching projects,
  project list, reports, resource charts and total dashboard rendering.
- `dashboard.resources`: aggregate project/pool counts and `staffing_ms`,
  `query_ms`, `minimum_ms`, `total_ms` for uncached resource reads.

These events omit credentials, session identifiers, project IDs, names and
business values. A warm resource-chart lookup was 21–57 ms in the browser runs;
it has no accompanying `dashboard.resources` event when the cache is used.
The existing five-minute display-cache TTL and current authorization checks
remain in effect. New sessions, relevant revisions or cache expiry can require
the more expensive uncached query.

## All-pool query diagnosis

A follow-up read-only `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` inspected the
body of `dashboard_resource_breakdown_with_capacity` with the same default
780-project / 33-pool workload. The extracted query's complete JSON result
matched the existing authorized function's result. No database functions,
persistent settings or stored data were changed by these experiments.

The expensive step is the `comparisons` join, not reading the base tables:

- Assignment events produce 2,005 demand intervals and 1,320 change dates.
- The join produces 40,807 pool/date comparison rows, but rejects about
  2.38 million interval/date combinations along the way.
- The planner brings each pool's JSON capacity calendar into this join before
  resolving the interval/date matches. The repeated large calendars make its
  sort spill approximately 546 MiB to temporary storage. The merge join rereads
  sorted rows repeatedly; its 2.42 million returned sort tuples are not that
  many distinct business records.
- The planner estimates only 7 rows for the sort input, versus 40,807 actual
  rows. In the instrumented baseline, comparisons took 8.47 seconds out of
  8.96 seconds overall. These node times include their children and must not
  be added together. Base-table buffers were already cached (zero shared
  block reads); temporary-file work remained substantial.

### Read-only experiments

| Query body variant | Ordinary execution, including fetching result | EXPLAIN execution |
| --- | ---: | ---: |
| Existing structure, 4 MB work memory | 6.79 s | 8.96 s |
| Existing structure, transaction-local 64 MB work memory | 5.04 s | 6.03 s |
| Materialize narrow `days` rows before joining staffing, 4 MB | 0.49 s | 0.63 s |

All three returned identical complete JSON results for this dataset. The
materialized-days variant had no temporary reads or writes. It stores the
intermediate pool/date/demand rows once before attaching staffing calendars,
so large calendars no longer pass through the interval-matching sort. This
does not create a persistent materialized view or require a refresh job.

The existing stored function itself took 4.47 seconds in a separate check.
Literal diagnostic queries and stored functions can have different plans;
EXPLAIN instrumentation also adds overhead. These are individual local
measurements, not an established production speedup or a concurrency test.

### Follow-up options

1. The narrow intermediate result proves expensive calendar copying is
   avoidable. This improvement was subsequently implemented and validated
   as described below, preserving the Python capacity boundary.
2. Users can select fewer pools for immediate relief. Selecting fewer projects
   helps only insofar as it narrows relevant pools and dates: total demand must
   still include other eligible projects sharing those pools.
3. Consider loading only the requested date window rather than all 80 quarters
   after preserving full-horizon warning behavior. This requires an application
   change; chart zoom alone does not narrow the database query today.
4. Do not prioritize new indexes, larger global memory settings or a larger
   database instance based on this evidence. The bottleneck is an intermediate
   join/sort, and 64 MB query memory still spilled. No persistent database
   configuration changes were made.

The late-project card now centers its label, percentage and count caption.

## Implemented join improvement

Migration `0059_dashboard_narrow_date_join.sql` adds `MATERIALIZED` to the
existing reader's narrow `days` CTE. It changes execution order only: no new
SQL calculation functions, business rules, permission grants or table changes.
It retains the function's identity, owner, security-definer setting, volatility,
search path and execute permissions. Earlier migration files are unchanged.

The local database was backed up to
`data/backups/dashboard-narrow-join-20260918-111701.dump`, the archive directory
was validated with `pg_restore --list`, and the migration was applied. Schema
compatibility passed; rerunning migrations applied nothing further.

Post-migration measurements for the same 780 projects and 33 pools:

| Measurement | Before | Migrated |
| --- | ---: | ---: |
| Authorized database function | 4.47 s | 0.51 s |
| Uncached resource service | 4.64–4.85 s | 0.68–0.70 s |

The migrated function's full JSON result matched the pre-migration result hash.
The follow-up execution plan had zero temporary reads/writes. Timings are local
observations; database load and different project distributions may affect them.

Validation: 48 checks passed across the focused dashboard/migration suites,
including 10 new checks covering clean upgrades, repeat migration, retained
permissions, rejected unauthenticated calls, full result parity, status/pool
filters, empty selection, private competing demand, leap-day exceptions and
earliest tied peak dates. Existing active-plan and minimum-capacity tests pass.

Five broader tests still fail. Each was independently reproduced with the
original non-materialized query, so they predate this optimization:

- `test_dashboard_aggregates.py::test_calendar_peaks_are_concurrent_and_full_quarter_overrides_replace_baselines`
- `test_dashboard_aggregates.py::test_change_points_preserve_concurrent_pools_quarter_ties_and_leap_day`
- `test_dashboard_aggregates.py::test_warning_lists_all_overallocated_pools_not_just_the_total_peak`
- `test_dashboard.py::test_private_competing_demand_and_calendars_match_the_existing_domain_aggregates`
- `test_dashboard.py::test_catalog_hierarchy_and_duplicate_labels_keep_only_current_project_facets`
