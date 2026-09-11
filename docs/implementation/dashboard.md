# Dashboard

After sign-in, Dashboard opens by default. It contains only projects you may read.
Use the flexible filter, the four manager/team filters, or the resource-pool filter; selections within a fixed
filter are alternatives, while different filters are combined. Clear all resets
the dashboard without changing Planning's filters.

Completed and cancelled projects are excluded. The project table starts in project-ID order
and shows five rows at a time with continuous scrolling. Rows are loaded in batches
of 50; the browser retains at most six batches and renders only the visible rows
plus a small buffer. Collapse the table to keep its matching-project count visible.
Charts and issues include all matches, independently of scrolling. Mail code is PRM_001.

Finance overview uses the most recent approved Finance version and each project's
current WBS allocation percentages. Hover to see annual euro values. The source
version is shown, and codes without approved amounts are identified. Canceled
Finance versions are excluded. Project details provide the same calculation in
the Budget tab, beneath WBS assignment. Approved, Proposed, and Draft sections
each use the latest uncanceled Finance version with that status and include annual
totals. Allocation percentages appear only in Draft; WBS codes and percentages use
the same gray text.

The quarterly resource chart shows peak simultaneous excess FTE across relevant
pools, including competing demand from other projects. For shortages of 1 FTE and
2 FTE on the same day, it shows 3 FTE even if another pool has spare capacity.
Capacity and Overallocation also shows the maximum daily total effective pool
capacity per quarter on a separate right-hand axis. This includes staffing and
calendar overrides. Both graphs mark the current date with a dashed green line.
Right-click a quarter to open Planning filtered to accessible projects consuming
the pools responsible for that quarter’s overallocation. This includes accessible
consumers outside the original dashboard selection, but never reveals hidden projects.
The warning icon beside Finance overview opens the read-only active-issues table.

Mouse movement, clicks, typing, touch, and scrolling reset the session's idle
deadline. Activity in another tab also counts. The default is 15 minutes of
inactivity, configurable with SESSION_IDLE_SECONDS; active use has no fixed
eight-hour limit. Changing application access may still require fresh authentication.
The upgrade requires one new sign-in for existing users.

Back up the database before applying the normal operator migration command. The
upgrade retains project, WBS, budget, event, and access-grant data. It adds stable
issue classification and revokes existing sessions once; it does not reseed data.

## Initial rollout verification (2026-09-11)

The final affected Python suites passed 222 tests, covering dashboard calculations,
authorization, OIDC, navigation, project details, dialogs, capacity, display caches,
and Gantt step updates. All 71 custom-component JavaScript tests passed. Additional
shared-cookie testing verifies that activity extends both tabs atomically and an
expired session cannot be revived.

The isolated 1,000-project browser fixture rendered both charts and verified the
euro hover tooltip, five-row paging, filters, and read-only issue popup. Initial
display took 1.61 s, paging 0.15 s, and filtering 0.23 s, with one shell execution
throughout. These local timings are observations, not performance guarantees.
The final screenshot was inspected.

On the existing 10,002-project development database, uncached service projections
took 2.38 s for the filter/project catalog, 0.05 s for approved budget calculation,
and 0.32 s for quarterly shortfalls. The catalog is cached between interactions.

The development backup is `data/backups/ppm_mock-before-dashboard-20260911T081448Z.db`.
Migration preserved 10,002 projects, 73,955 tasks, six Finance snapshots and their
96 amounts, WBS allocations, events, identities, and role assignments. SQLite
integrity and foreign-key checks passed. Two existing sessions were retired. The
restarted Docker app is healthy and responds with HTTP 200.

## Dashboard refinement

Project and task pool-assignment values are batched in native forms. Selecting a
pool or changing FTE sends no rerun until submission. The project dialog caches
authorized reference data by business/security revision and batches details only
for assigned pools; unrelated pools use their defined capacity directly.

On the same 103-pool isolated fixture, project popup opening improved from 2.98 s
and 103 detail reads to 0.37 s and no unrelated detail reads. A forced FTE rerun
improved from 0.22 s / 103 reads to 0.02 s / zero reads. A project with assigned
pools makes one batch read initially and reuses it on subsequent interaction.

Verification passed 90 targeted Python checks, followed by 29 final browser/UI
checks (including overlapping regression suites), and all 71 JavaScript tests.
A further Dashboard browser check passed three consecutive runs after correcting
queued lazy refreshes to read current filter state. Closing the flexible-filter menu
preserves the selected project and its visible row. Both project and task allocation browser tests
verify that changing the pool and FTE sends no rerun request before submission.
Planning drill-through replaces stale filters; the three budget sections select
their latest status version and fall back after cancellation.

A measured 1,000-project browser run took 1.18 s for initial display, 0.12 s for a
lazy scroll fetch, and 0.23 s for filtering. Charts remain mounted during scrolling
and the application shell runs once. These are isolated local observations, not
production guarantees. The final screenshot was reviewed. The development app
was restarted and verified healthy with HTTP 200; this refinement needs no new
database migration.
