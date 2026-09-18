# Function hierarchy and dashboard lateness

Functions use `manager_function_id` as their primary reporting parent. The
Functions page uses the same filtered hierarchy and context menus as pools.
Primary Manager and ID are omitted from displayed columns. `has_reports` is
derived from non-deleted direct children; migration 0058 removes the stored flag.

`hierarchy_level` remains editable because dashboard and portfolio management
reporting use it to identify organizational levels, including level-3 managers.
It is a business classification and is not replaced by visual tree depth.

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
