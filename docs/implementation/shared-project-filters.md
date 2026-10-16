# Shared project filters and annual financial indicators

Dashboard, Portfolio Overview and Planning use the same organization, project
status, strategic priority, pool and advanced filter panel. Selections persist
within the browser session when navigating between pages, including an interim
page without the panel. Reset restores In Progress and clears the other filters.
Only selections are persisted; transient button events are not restored.
Each page reauthorizes its matching projects. Portfolio keeps server-side paging
and column filters; Planning retains its project/dependency focus controls.
The panel uses the same compact spacing on all three pages. Its filter controls
match the height of the collapsed manager frame. Planning's project selector is
the first dropdown in the filter row; Portfolio's create action aligns with the
right edge of Reset filters.

The dashboard Actual / Approved and (Actual + Commitment) / Approved indicators
use only the current calendar year, shown in each title. The financial chart keeps
its multi-year timeline. Project detail variance remains Actual + Commitment minus
Approved and also shows (Actual + Commitment) / Approved as a percentage. A zero
budget displays N/A for the percentage.

Project tag fields use dropdown multiselects in both project editors. The custom
project popup shows checkboxes inside the dropdown and retains selected tags
when it closes or a save needs correction. WBS choices with no
remaining allocation are hidden from new selections; existing assignments remain
visible so the editor can resolve conflicts.

## Compact spacing and Gantt tooltips

The shared organization frames use 2 px inner padding. Planning and Dashboard
share the compact page-top spacing. Gantt hover details wait one second and
cancel when the pointer leaves; native timeline titles are suppressed while rich
tooltips are enabled. Dragging retains immediate date feedback.

Resource hierarchies start fully expanded. Double-clicking a pool or container
toggles its expansion; a single click shows the existing allocation breakdown
below the grid, scoped to the clicked period and assignment row. Project rows
continue to expand or collapse on a single click.

## Cancelled projects and WBS

Migration 0064 replaces the old availability calculation function with an
authorized anonymous-facts projection. Python calculates the remaining share,
excluding cancelled projects and the edited project's own assignment. It validates
reactivation against the complete proposed allocations in the same serializable
transaction. A conflict rolls back the status and all other edits, naming the WBS
and its available percentage and requiring resolution before reactivation.

Cancelled assignments are retained. Reactivation may reduce or remove them in
the same save. The existing database WBS write constraint still protects the 100%
limit for direct allocation writes, now excluding cancelled owners. No applied
migrations are rewritten.

Before the local migration, a verified backup was saved as
`data/backups/before-shared-filters-wbs-20260920-084320.dump`.

Division, team, and project manager frames preserve their expanded state across
page navigation, including intervening pages without the filter panel. Collapsed
frames with selected filters use a red header. Resource chart tooltips and Gantt
resource overlays display FTE to one decimal place without rounding calculations.

## Privileged helper hardening

Migration 0065 restores the explicit `pg_catalog, eppm, pg_temp` search path on
the WBS allocation guard and the team/pool-type cycle guards. It changes only
function configuration: executable bodies, existing allocation and hierarchy
rules, stored business records, and prior migration checksums are preserved.
Apply it through the explicit operator migration command before starting this
application revision; normal startup does not migrate the database.
