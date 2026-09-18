# Remove numeric function levels

## Decision

At the user's request, remove `hierarchy_level` from functions and remove the
associated level-based manager lookups rather than replacing them with implicit
tree-depth classifications. This supersedes the retention decision in ADR 0058.

Functions retain `manager_function_id` and `dual_manager_function_id`. The tree
uses primary parent links. Project managers retain their directly assigned
function/occupant labels. Service, division and team filters continue to use
explicit function-to-team membership and the classified team hierarchy.

## Implementation

- Migration 0060 drops the function column and explicitly rebuilds dependent
  active-record views with their existing security-invoker settings and grants.
  It invalidates catalog revisions. Previously applied migrations are unchanged.
- Models, references, validation, create/edit forms, SQL readers/writers and seed
  data omit the field. Function reference lists sort by name, then identity.
- Dashboard omits level-3/4 facets and the level-3 manager flexible field.
- Planning and Portfolio omit the level-3 managing-function field, including
  Portfolio details, columns and the recursive level-based database lookup.
- Function exports and templates use the updated model's headers. CSV import
  rejects unsupported headers, including `hierarchy_level`; there is no legacy
  compatibility path. Existing ID/update/delete-missing rules remain unchanged.
- The unused legacy function-table asset and level-specific translations are
  removed. Cached flexible-filter selections are restricted to current fields.

## Validation

Real PostgreSQL tests cover clean migration, upgrade, repeat migration, retained
function records and parent/membership links, function CRUD, CSV round trips,
current templates and rejection of obsolete headers. Browser coverage verifies
editing a function without the removed control. Page tests exercise direct
manager labels and the surviving dashboard organization filters.

Local rollout on 2026-09-18: backup
`data/backups/function-level-removal-20260918-114801.dump` was created before
applying migration 0060. Before/after hashes confirmed retained function,
employee, team, assignment and mapping data was unchanged. The application was
restarted and Dashboard, Portfolio and Planning navigation verified in Chromium.
The final focused function/CSV/migration/browser run passed all 18 tests. The
page regression batch passed after updating outdated status-filter and cumulative
revision assertions. Full-suite collection succeeded (3,005 tests); the full
suite was not executed for this change.
