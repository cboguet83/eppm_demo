# Dashboard

Dashboard chart tooltips and indicator help follow the selected application
language (English, French, German, Luxembourgish or Portuguese), including
Actual/Commitment labels, financial-ratio explanations, late-project definitions,
and resource quarter/FTE labels. Changing language refreshes these labels without
changing filters or financial values. User-entered project, pool and budget names
retain their original text.

After sign-in, Dashboard opens by default. It contains only projects you may read.
Use Advanced filters below Resource pools, the four manager/team filters, or the resource-pool filter; selections within a fixed
filter are alternatives, while different filters are combined. Clear all resets
the dashboard without changing Planning's filters.
Clear all filters and Advanced filters share the same horizontal action row.

The Project status multiselect defaults to In Progress. Select other statuses to include
completed or cancelled projects, or clear the selection to include all accessible
statuses. Multiple statuses are alternatives regardless of flexible Any/All matching.
Clear all filters restores the default In Progress status selection. The project table starts in project-ID order
and shows five rows at a time with continuous scrolling. Rows are loaded in batches
of 50; the browser retains at most six batches and renders only the visible rows
plus a small buffer. Collapse the table to keep its matching-project count visible.
Charts and issues include all matches, independently of scrolling. Mail code is PRM_001.
Click a project row (or press Enter/Space on it) to filter the dashboard to that
project. Click it again to restore the previous scope. Changing another filter or
using Clear all removes the row selection. Selection refreshes only Dashboard;
scrolling still updates only the table.

Each row activation has a distinct event identity. Selection uses the current
revision and active-filter token independently of the selected-row paging token,
so a second click remains valid while the browser is applying the first response.
Every callback still checks current project visibility and filters before changing
selection. Paging responses continue to use their own snapshot token.

Finance overview plots the most recent Approved and Proposed Finance versions using each project's
current WBS allocation percentages. Hover to see annual euro values. Both source
versions are shown, and codes without amounts are identified. Canceled
Finance versions are excluded. Project details provide the same calculation in
the Budget tab, beneath WBS assignment. Approved, Proposed, and Draft sections
each use the latest uncanceled Finance version with that status and include annual
totals. Allocation percentages appear only in Draft; WBS codes and percentages use
the same gray text.

Two quarterly resource charts show allocation with capacity, and overallocation.
Bars stack the contributions of individual pools, including competing
demand from other projects. Each quarter uses its peak total day; all segments
come from that same day and therefore add exactly to the displayed total.
Overallocation adds positive excess only, without offsetting spare capacity in
other pools. Overallocation tooltips show four lines: period, Overallocation,
Total with its value, and the selected pool contribution. Allocation tooltips show
five lines: period, total capacity, total allocation, pool allocation, and pool available
capacity. Pool rows have a square matching their bar color. Available capacity is signed
effective capacity minus demand on the allocation peak day, including calendar reductions;
negative values indicate a shortfall. Peak dates are omitted. Finance tooltips show the
year and both Approved and Proposed values, using a dash for a missing value.
A dashed hover line tracks the same time position across Finance and both resource charts and
clears from all three when the pointer leaves a chart. All three share the same full-width
plot geometry and calendar-date positions, including year ticks and the current-date guide.
Capacity uses maximum daily total effective capacity in the quarter, on the same
axis as allocation, including employee calendars and pool reduction exceptions.
The dashboard uses the supplied 15-color palette: Approved is black, Proposed is blue,
and capacity is a dashed red line (#f10d0d). Pools retain consistent palette colors across resource charts.
Right-click a pool segment to open Planning filtered to accessible projects
consuming that particular pool in the selected quarter. This can include accessible
consumers outside the dashboard selection; hidden projects remain undisclosed.
The same context menu on both resource charts includes **Pool details**, which
opens Settings → Resource Pools with that pool selected. Access is rechecked
before navigation and the destination retains its normal permissions.
Both resource charts mark today and display the current year, two previous years,
and nine future years. Per-pool colors are consistent across both charts.
The Finance legend is below its x-axis. Resource charts have no legend.
All three charts occupy a shared left column whose right edge aligns with the
left edge of the warning frames. Active Issues occupies the top of the right
column. A matching Overassigned Pools frame sits below it, showing the number of
pools with excess demand in the dashboard's filtered scope and displayed years.
Hover or focus that frame to see only their names. A pool is included if it has
excess on any day, even when it contributes nothing on the total quarterly peak
day. Zero overassigned pools shows a green warning indicator without a list.
Resource axes show whole numbers, and resource tooltips show one decimal place.
The large warning icon in the framed Active Issues card beside Finance overview
opens the read-only active-issues table, ordered by decreasing event ID across projects.
Both warning cards use singular labels for zero or one item.
The icon is centered above the count and label. With no issues, the icon is green,
the text is black, and the popup is disabled. Otherwise the icon, number, and text
are orange. The resource chart's vertical titles sit beside their respective axes.

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

## Finance navigation and chart controls verification

The Finance save freeze was reproduced in an isolated browser: a previous grid
invocation retained its unsaved-change sidebar listener after the saved snapshot
replaced its model. Explicit component cleanup now releases those listeners and
closes the old dialog before rendering new data. A browser regression saves a
plan, navigates away and back, then verifies both Cancel and Discard on a new edit.

The affected suites passed 90 Python tests and all 71 JavaScript tests. Browser
checks cover row click/keyboard selection, unchanged sidebar execution count,
the 48-quarter chart range, unique integer axis ticks, one-decimal tooltips,
legend position, and the enlarged Active Issues card. The final screenshot was
reviewed. The restarted development app is healthy and responds with HTTP 200.

The selected-project Finance curve regression now compares actual browser values
for two projects sharing a WBS at 50% and 25%. The server calculated the right
shares, but the layered chart retained the previous dataset. A compact budget
fingerprint in the chart specification now refreshes it when values change;
lazy table scrolling still leaves the chart mounted. All 24 Dashboard tests pass,
including chart-value updates, centered icon geometry, colors, disabled zero-issue
popup, and vertical axis titles.

The matching-project details frame starts collapsed; expand it to inspect or select projects.

Migration 0034 computes selected-project coverage as disjoint date windows before comparing daily demand. This preserves the existing scope and totals while avoiding repeated scans of monthly assignment segments in large seeded portfolios.

The Resources allocation section contains two charts separated by 4px. The upper chart shows only stacked overallocation. The lower chart shares one vertical scale between stacked allocation and the capacity line, including both series when calculating the axis maximum. Neither chart has a separate visible heading; their accessible labels and synchronized dark-grey, 3px dashed hover guides remain available.
