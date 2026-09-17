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
reserved. Identifier reuse is outside this change.

## Pool restoration and administration

The resource-pools page hides deleted pools by default. An adjacent checkbox to
the demand-status filter includes deleted pools in the hierarchy with a visible
Deleted badge. Active rows offer Delete; deleted rows offer Undelete, with other
editing actions unavailable. Deletion uses the existing confirmation dialog.

Undelete restores one pool in a Python application transaction, retaining its
identity, assignments, resource mappings and exceptions. Deleted parents must be
restored first. Restoring a child reuses the existing container-conversion rules:
its parent cannot have assignments, resource mappings or capacity exceptions, and
the parent's defined capacity is zeroed. Deleted mapped employees or teams remain
excluded after restoring a pool.

This page requests calculations only for active leaf pools and displays no
capacity or demand numbers for containers or deleted rows. Selecting an active
container still displays its individual leaf pools' allocations and overassigned
periods. A deleted child does not make its active parent a capacity container;
the historical child can still be expanded when deleted rows are visible.

The summary shows Total Pools, Pools with no assignment, Overassigned Pools,
and Pools with future capacity exceptions, in that order. All counts include active leaves only, excluding containers
and deleted pools. A pool has no assignment for this
summary when no active employee or team is mapped, regardless of project demand.
Showing deleted rows does not change these active summary counts.

The status selector is hidden; demand remains restricted to In Progress projects,
as explained by the Future Peak Demand header tooltip. The exception indicator
counts each pool once when an applicable exception ends today or later, including
ongoing exceptions and single-day exceptions today. The hierarchy exposes the
same flag. Selecting a pool or container displays all applicable exception periods,
including historical ones, with Pool or Employee source and the mapping path.

Unmapped pools use pool capacity exceptions. Mapped-resource capacity ignores
pool-level exceptions and uses employee availability exceptions instead, including
employees occupying functions explicitly assigned to mapped teams. The existing
staffing resolution supplies deduplicated employees and mapping precedence.
Retained pool exceptions are hidden in the mapped pool editor and resume applying
if all resource mappings are removed. Derived cache format version 2 invalidates
capacity results computed with the former combined-exception rule.

## Resource-pool CSV transfer

The resource-pool page exports its catalog to UTF-8 CSV. Deleted pools are
included only when **Show deleted pools** is checked. Containers remain in the
file so parent relationships can be round-tripped, although they are excluded
from the Total Pools metric. The import dialog provides an empty CSV template
and previews records before submission.

Downloads use authenticated `/downloads/resource-pools/` routes, rechecking the
current session and shared-management permission on each request. Responses are
uncached UTF-8 CSV attachments with a BOM. The upload reuses the bounded CSV
component over the authenticated WebSocket. Native Streamlit media and upload
endpoints remain blocked by application security middleware. Browser regression
tests run with this middleware enabled.

Columns are `pool_id`, `name`, `description`, `capacity_fte`, `parent_pool_id`,
`pool_type_id`, `hierarchy_type_id`, and `deleted_flag`. Only `name` is required.
Blank optional fields clear their values; a blank capacity is unspecified,
pool type defaults to 1, and the deleted flag defaults to false. Booleans accept
`true`/`false` and `1`/`0`. Comma and semicolon delimiters are accepted.
Mappings, tags, creation timestamps and capacity exceptions are not transferred
or modified by CSV import.

Imports synchronize the active catalog: active pools omitted from the file are
marked deleted in the same transaction, retaining mappings and history. The dialog
warns before submission and reports the number marked deleted. Include all active
parent containers in the file; retaining an active child while omitting its parent
fails validation and rolls back the entire import. An empty file is rejected.

An ID matching an existing record (including a deleted record) updates that
record. Missing or unknown IDs create new records using the database identity
sequence, never the supplied ID. Unknown source IDs serve only as aliases for
parent references within the same file; parent/child row order is immaterial.
Duplicate source IDs, unknown parents and circular hierarchies are rejected.

The Python application service validates and writes the whole import in one
authorized transaction. Any invalid row or persistence failure rolls back the
entire batch. Setting `deleted_flag` changes visibility without deleting
history. Active children require active parents; a complete deleted hierarchy
can be restored or deleted in one file. Live containers have zero defined
capacity and cannot hold direct assignments, mappings or capacity exceptions.
An unchanged export can be imported without creating duplicate records.

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
