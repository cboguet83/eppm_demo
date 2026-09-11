# Dashboard

After sign-in, Dashboard opens by default. It contains only projects you may read.
Use the flexible filter or the four manager/team filters; selections within a fixed
filter are alternatives, while different filters are combined. Clear all resets
the dashboard without changing Planning's filters.

The project table displays five rows per page. Its charts and issue count always
include every matching project, not just those five rows. Mail code is PRM_001.

The Budget line uses the most recent approved Finance version and each project's
current WBS allocation percentages. Hover to see annual euro values. The source
version is shown, and codes without approved amounts are identified. Canceled
Finance versions are excluded. Project details provide the same calculation in
the WBS tab, below the allocation list, including annual totals.

The quarterly resource chart shows peak simultaneous excess FTE across relevant
pools, including competing demand from other projects. For shortages of 1 FTE and
2 FTE on the same day, it shows 3 FTE even if another pool has spare capacity.
Click the active-blocking-issues count to inspect a read-only multiline log table.

Mouse movement, clicks, typing, touch, and scrolling reset the session's idle
deadline. Activity in another tab also counts. The default is 15 minutes of
inactivity, configurable with SESSION_IDLE_SECONDS; active use has no fixed
eight-hour limit. Changing application access may still require fresh authentication.
The upgrade requires one new sign-in for existing users.

Back up the database before applying the normal operator migration command. The
upgrade retains project, WBS, budget, event, and access-grant data. It adds stable
issue classification and revokes existing sessions once; it does not reseed data.

## Verification (2026-09-11)

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
