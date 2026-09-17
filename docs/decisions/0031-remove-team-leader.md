# Remove the optional team leader

## Decision

Remove `team.leader_function_id` and its team editor/grid controls. Keep
`team.manager_function_id`. Migration 0051 drops existing leader values without
copying them into managers or explicit memberships. It does not delete functions.

Team hierarchy continues to use `parent_team_id`. Membership remains a
many-to-many function/team relationship through `team_function`; employees refer
to functions through `employee.function_id`. No `employee.team_id` is introduced.

Capacity membership now uses explicit `team_function` rows only. Neither the team
manager nor functions reporting to that manager are automatically included. The
former sparse-team fallback is removed. A manager contributes through the same
explicit membership route as any other function. `parent_team_id` remains a
hierarchy link and does not implicitly add members from child teams.
The existing theoretical-FTE fallback for explicitly assigned vacant functions
is retained; this decision removes inferred membership, not vacant-position capacity.

The migration updates the existing private PostgreSQL staffing reader to stop
referencing the dropped column and advances the catalog revision to invalidate
cached capacity results. The Python reference calculation follows the same rule.
Moving the private staffing calculation into Python is outside this change.

## Verification

An upgrade test covers leader-only and distinct manager/leader teams, preserved
explicit membership and function records, removed leader-only capacity, cache
invalidation, and repeatable migrations. Organization CRUD/dialog tests, capacity
parity tests, and the team-table browser test cover the affected application paths.
