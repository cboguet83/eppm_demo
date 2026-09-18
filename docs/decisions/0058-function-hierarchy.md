# Function hierarchy and dashboard lateness

Functions use `manager_function_id` as their primary reporting parent. The
Functions page uses the same filtered hierarchy and context menus as pools.
Primary Manager, ID, Hierarchy Level and Has Reports are omitted from displayed
columns. The tree shows Function Title, Function Type, Dual Manager and FTE %.
Its expand/collapse behavior derives directly from child links. Removed-column
filters and sorting are ignored when restoring component state.

`has_reports` remains derived from non-deleted direct children in the shared
organization dataframe; migration 0058 removes the stored flag. The hierarchy
component no longer sends that field. The unused legacy `function_table` asset
has been removed; no current business calculation depends on the flag.

The original decision to retain `hierarchy_level` is superseded by
[0060 — Remove numeric function levels](0060-remove-function-levels.md).
Dashboard, Planning and Portfolio now use direct project-manager labels without
level-based ancestor lookups. Function parent links remain authoritative.

Function CSV exports include `deleted_flag` and exclude deleted functions unless
Show deleted functions is checked. Templates contain the same headers. Imports
update known IDs and generate IDs for unknown or omitted IDs. Primary and dual
manager IDs can reference other rows in the import. Missing functions are kept
unless deletion is explicitly selected. Imports are atomic; invalid ancestry,
cycles and active children pointing to deleted managers are rejected. Employee
and team mappings are retained by soft deletion and restoration.

The dashboard's late-project percentage uses **all projects within its current
filters**. A project is late when at least one non-deleted active-plan task ends
before today with progress below 100%. Each project counts once. Baseline and
alternative plans do not affect this indicator. The calculation runs in Python
after the existing authorized, filtered database read.
