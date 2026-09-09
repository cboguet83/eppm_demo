# ADR 0017: Project links and contextual workflows

- Status: Accepted for the requested UI increment
- Date: 2026-09-09

## Decision

Keep Streamlit, the existing component transports, and the layered SQLite
architecture. Add `project-links-v1` after the existing migrations. The indexed
`project_link` collection stores a URL and display alias per project, with no
fixed number of slots. Existing template URL properties remain intact.

`CollaborationService` validates HTTP(S) URLs and nonempty aliases before writing
through its existing transaction port. Updates and deletes are project-scoped;
foreign keys enforce ownership references and cascade project deletion. Database
flush also removes links. Startup's schema version changes so cached initialization
cannot skip the additive migration.

## User workflows

- Useful Links includes a reusable add/edit form and clickable display aliases.
  New links can be added after a project has been created, independently of its
  template. The existing template fields are still editable in the project editor.
- Project log entries appear in a table that fills the available width. All cells
  wrap, and descriptions/comments preserve newlines. Add event opens a dialog;
  right-click, keyboard context menu, and the row's Edit entry button open editing.
  The existing 50-entry pagination and application validation remain in effect.
- Portfolio detail tabs rerun their own fragment. A small v2 component reserves
  the detail panel's current height before tab changes, preventing page-scroll
  clamping when the next tab is shorter. Property labels and values occupy separate
  columns with a two-rem gap.
- Gantt project context menus include Add step, Export CSV template, and Import
  CSV template. CSV operations use the clicked project and open a dialog. Export
  also retains the actual schedule download. The old bottom CSV section is removed.
- Resource grids hide unused pools by default. Both capacity and allocation cells
  expose pool context actions. Show active allocations opens the same assignment
  projection used by Settings with a Go to action for its project/task. Settings
  retains the separate confirmed unassignment workflow.
- Capacity cells and rows no longer use orange for underassignment. A neutral badge
  in the left pane marks capacity below the defined amount during the displayed
  period, including collapsed pools. The capacity badge reads “Capacité” in French.

## Shared context-menu appearance

`context_menu.py` owns the visual standard derived from the Gantt menu: eight-pixel
corners, a light border, shadow, padded rows, hover/focus highlighting, and red
destructive actions. V2 tables import the style. Existing iframe assets embed the
same CSS because each component serves its own directory; a regression test checks
that every embedded copy matches. Menu labels are inserted as text in v2 tables.

## Validation

Real SQLite regressions cover unlimited link creation, validation, ownership,
foreign keys, cascade deletion, flush, repeat migration, and migration rollback.
AppTest covers link forms, log creation/editing, CSV dialog routing, and pool popup
data. JavaScript tests cover menu identity, keyboard editing, viewport boundaries,
tab height retention, capacity-row actions, and selected-pool filtering defaults.

The full suite passed with 544 Python tests and 30 JavaScript tests. The final
URL-rendering adjustment also passed all 21 affected Python tests. Live browser
checks confirmed retained tab position, link controls, the log creation dialog,
project CSV menu/dialog, the default unused-pool filter, and the pool allocation
popup with Go to actions. The development database was backed up before migration;
existing project, task, pool, assignment, log, and contact counts were preserved,
and the foreign-key check returned no violations.
