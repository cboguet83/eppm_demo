# Native strategic priority and derived project financial totals

## Decision

Project financial values are read from their authoritative sources:

- Planned: all `COMMITMENT` transactions, across all years.
- Actual: all `ACTUAL` transactions, across all years.
- Budget: the sum of the project's WBS allocation percentages applied to the
  latest sealed, non-cancelled Approved finance snapshot, across all years.
- Missing transactions or budget allocations contribute zero.

The project master table no longer stores `planned_budget` or `actual_budget`.
Reporting contracts retain those names for their derived values. Queries aggregate
transactions and budget shares separately before joining projects, avoiding
duplicate totals when a project has several WBS or transactions. Monetary reads
use PostgreSQL numeric values and Python Decimal; project access rules still apply.
Portfolio cache keys include financial transactions and finance revision changes.

Strategic priority is an optional native `project.strategic_priority_id` foreign
key to `strategic_priority`, with labels in `strategic_priority_translation`.
Stable codes are `strategic`, `high`, `medium`, and `low`. Project creation and
editing validate this reference in Python under the existing project permissions.

The dashboard filter sits between Project Status and Resource Pools and defaults
to all priorities. Reset retains the existing In Progress status default. Priority
also appears in the master grid and beside the project manager in project details.

## Migration

Migration 0063 creates reference tables and uses a checksummed Python hook to
preserve PRM_027 values, convert Critical to Strategic, and remove the parameter
and stored project money columns. Unknown nonempty priorities reject the atomic
migration. Existing transactions, finance snapshots, and WBS shares are retained.
Apply migrations before starting the updated application. No SQL calculation
functions are introduced.

Local migration on 19 September 2026 preserved 1,000 priorities: 257 Strategic,
240 High, 261 Medium, and 242 Low. The verified backup is
`data/backups/before-project-priority-20260919-201118.dump`.

## Validation limitation

The project details summary reports the server's current calendar year explicitly:
Approved budget (latest sealed, non-cancelled Approved revision, weighted by the
project's WBS shares), Actual and Commitment (transaction totals for that fiscal
year). Variance is Actual + Commitment - Approved budget; positive means over
budget. Its hover text explains the formula and sign. The master list continues
to report all-year totals. Annual detail reads share the authorized transaction
with the project read.

The broader suite still fails the five ten-editor concurrent title-save cases
with transaction retry exhaustion. The small stored-title case was reproduced
against unchanged main-branch code in a disposable database, confirming it
predates this change. Project authorization and transaction isolation are retained.
