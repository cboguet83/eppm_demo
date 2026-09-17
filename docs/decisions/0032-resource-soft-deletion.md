# 0032 — Soft deletion of organization resources

## Status

Accepted, 2026-09-17.

## Decision

Teams, functions, employees, resource pools, function types and hierarchy types
have `deleted_flag boolean NOT NULL DEFAULT false`. Deleting these records through
the application sets the flag. It preserves the row identity, relationships,
calendar exceptions, translations and historical project assignments.

Live catalogs, selectors, staffing, demand, dashboard totals and planning resource
projections exclude deleted records. A deleted employee no longer contributes
through a function/team mapping. A deleted function breaks that team membership
path; a deleted team contributes no employees. A still-active team with no active
employees contributes zero, without falling back to a pool's nominal capacity.
Direct employee mappings remain independent of function/team membership.
The existing theoretical-capacity rule for a directly mapped vacant function is
unchanged: it represents the active function, not a deleted employee.

Function and hierarchy types cannot be deleted while referenced, including by
retained deleted records. This is enforced in the Python application service.
The existing restriction on deleting parents with active children is retained:
move or delete the children first. Child deletion retains its historical parent
link but no longer prevents deletion of that parent.

Ordinary edits do not restore deleted records, and stale selections cannot create
new mappings to deleted resources. Existing unique names, codes and emails remain
reserved. Restoration and identifier reuse are outside this change.

## Implementation

Migration `0053_resource_soft_deletion.sql` adds the flags and filtered read views.
These use `security_invoker` to preserve existing row security. Minimal employee
name directories retain their existing authorization contract. Existing private
staffing and dashboard queries consume the filtered sources; no new PostgreSQL
business function is introduced. Python services own deletion decisions and
Python domain calculations also ignore flags in explicit input snapshots.

Existing cache revision triggers invalidate changes to the flags. The migration
also advances the catalog revision to invalidate projections from older releases.
Plan reads omit deleted pool allocations, while later edits retain those hidden
allocation rows. Operator-only maintenance/reset commands remain explicit
destructive tools; application delete menus use soft deletion.

## Validation

Regression tests cover existing-row migration, non-null enforcement, retained
relationships, capacity-chain exclusion, pool-demand exclusion, type deletion
restrictions and repeat deletion. Existing organization, capacity, dashboard and
planning tests protect their authorization and calculation contracts.
