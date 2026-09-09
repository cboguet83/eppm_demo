# ADR 0018: Editable project templates and contextual inspection

- Status: Accepted for the requested UI revision
- Date: 2026-09-09
- Supersedes the CSV popup, neutral badge, and creation-link limitations in ADR 0017

## Decision

Keep the existing layered SQLite application and component transports. Export CSV
template downloads the selected project's current tasks directly through a small
Streamlit v2 component. Import opens a warning and preview dialog. Uploading alone
does not modify data; Replace project schedule validates the complete input again
inside the write transaction before clearing the existing schedule.

Replacement removes the project's old tasks, incoming/outgoing task dependencies,
whole-project predecessor links, and both project-level and task-level resource
allocations. Project metadata, contacts, logs, and useful web links are retained.
New tasks and their declared predecessors are created in that same transaction.
Any failure rolls back both deletion and insertion. External references are checked
in batches before deletion, within the reserved write transaction.

## CSV contract

Columns are `step_number,task_name,phase,start_date,end_date,progress_pct,description,preceding_step,dependency_type,dependency_lag`.
Step numbers are unique positive integers and need not be consecutive. Dates are
ISO dates on export; progress is an integer from 0 to 100. The import panel defaults
to DD/MM/YYYY, with YYYY-MM-DD and MM/DD/YYYY available as explicit choices,
allowing spreadsheet date reformatting with a defined day/month order. ISO cells remain
accepted in either mode. Preview and replacement use the same selected format,
and the preview shows normalized ISO dates. Invalid dates identify the row, date
column, submitted value, and expected format before any deletion. CSV quoting preserves commas,
quotes, and multiline descriptions. Empty templates, duplicate/unknown columns,
invalid row widths, invalid values, missing predecessor references, duplicate links,
and self-links produce explanatory errors without changing existing data.

The three optional dependency columns use aligned semicolon-separated values:

- `1`, `FS`, `0` refers to step 1 in the same file.
- `task:123`, `SS`, `2` refers to external task 123 with two days of lag.
- `project:4`, `FF`, `-1` refers to the whole predecessor project 4.
- `1;task:123`, `FS;SS`, `0;2` declares two predecessors in the same row.

Each nonempty dependency list must have the same length, with no empty members.
Export and import preview use these same columns. The old combined `dependencies`
column is superseded by this contract. The import warning has an orange background
and a warning icon; validation still precedes any deletion.

Types are FS, SS, FF, or SF. Signed integer lags are supported. External identities
are specific to this application's database. Multi-task cycles remain diagnostic
warnings under the existing scheduling rules; template import does not introduce
a new business prohibition. Legacy append-import APIs remain available to their
existing callers; the Gantt replacement workflow uses the new explicit use case.

## Presentation

The Gantt project menu groups filters into This project, This project and all
dependencies, and This project and predecessors. Filters traverse stored project
dependencies transitively, including projects whose task rows have not been
loaded by the chart. UNION terminates traversal through cycles. Bulk actions
contains CSV import and export. Submenus open to the left near the viewport edge.

View project details opens disabled fields by default. The right-aligned Edit project button unlocks the
fields and custom-link editor. Explicit edit entry points elsewhere remain editable.
Create and edit dialogs save custom links atomically with project fields. Custom
link inspection uses the same alias/URL property rows as template-defined links,
with a horizontal separator. Link management is confined to create/edit dialogs.
Default action buttons use the application accent background `#C41039`.
Gantt scale buttons use that red background only for the selected scale; the
other scales have gray backgrounds.

Portfolio column-header filters close on an outside pointer press or Escape,
including clicks elsewhere on the page. Dismissal discards unapplied choices and
cancels pending search timers; late facet responses do not reopen the popup.
Document listeners use the composed event path across the component shadow root
and are removed when the component updates or unmounts.

Task and resource-pool filters use nested submenus like the project filter. Resource
filters can expand consuming projects to all dependencies or predecessors in a
single cycle-safe database traversal. Clear all filters resets project selection,
flexible filters, and contextual pool/project filters. The standalone tag selector
is removed; tags remain available through Flexible filters. Clearing filters restores
the resource grid defaults, including hiding unused pools.

Pool-group labels and timeline cells expose consuming-project filtering and active
allocations for all descendant pools. Group label filters cover all periods; cell
filters use the clicked period. The allocations popup groups the existing Settings
projection by pool and retains Go to actions. Underassignment is an orange badge;
overassignment is a purple badge. Assigned capacity rows and cells retain neutral
backgrounds. Pool tooltips show only the full name when assigned at defined capacity.
For mismatches they add defined capacity and minimum assigned capacity for
underassignment or maximum assigned capacity for overassignment (both when needed).
No dates, periods, demand details, or excess amounts are displayed. Group tooltips
show the group name and concise summaries of only the pools with mismatches.

## Validation

Real SQLite tests verify round-trip dependency mapping, invalid-input preservation,
rollback after partial insertion failure, project-link save atomicity, cycle-safe
project filters, and descendant allocation popups. AppTest checks disabled project
fields and explicit editing, import warnings, and direct export routing. JavaScript
tests cover submenu scopes, group identities, and single-download nonce handling.

Final validation: 571 Python tests, 14 subtests, and 34 JavaScript tests passed.
Live browser checks confirmed the nested menus, disabled project fields followed
by explicit editing, descendant-pool allocation tables, the pre-upload warning,
and the CSV download component executing without opening a popup. Replacement
tests used temporary databases; live project schedules were not replaced.
