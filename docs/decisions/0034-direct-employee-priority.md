# Global direct employee priority and safe pool restoration

Status: accepted by the implementation plan. Supersedes the same-pool direct
override and restored-pool behavior described in decision 0033.

## Allocation rule

Direct employee percentages across all active pools consume capacity first.
Each indirect function/team contribution uses the remaining percentage:

`employee availability × max(0, 1 − global direct share) × function share × team mapping share`

An employee available at 1 FTE with 80% direct allocation and function shares of
25%/75% contributes 0.05/0.15 FTE through fully mapped respective teams. Direct
and indirect contributions to the same pool add into one employee row. Repeated
paths to the same function remain deduplicated; an explicit function mapping
still overrides team paths for that function. Vacant function behavior is unchanged.
Employee exceptions replace normal availability before percentages are applied.
Pool exceptions remain ignored for mapped pools. Teams-page capacity remains gross.

A fully directly mapped member contributes zero through teams; the team can
still be mapped. Validation evaluates the complete proposed catalog. Direct
changes can reduce capacity in other pools without changing project demand;
existing demand warnings expose any resulting shortage. Team percentages and
employee effective allocation may not newly exceed 100%. Existing excess can be
repaired without increasing it. Removing direct mappings can increase indirect
contributions and is validated too.

## UI and restoration

The mapping dialog starts in team mode. Direct employee mode is an explicit
checkbox. Both existing resource types remain visible; only the selected mode's
rows can be changed. Saving preserves the other type, including pending edits
made before switching modes. Closing the dialog resets mode on the next opening.

Undelete restores provisionally inside the serializable transaction, evaluates
all resource percentages, and rolls back if it creates or worsens overallocation.
The explanatory popup identifies resources, totals and contributing pools.
Project-demand shortages alone do not prevent restoration.

CSV imports apply requested deletions before evaluating restoration. Collectively
conflicting restorations are kept deleted, without choosing winners by file order.
Dependent children are also kept deleted. Other valid catalog updates commit.
Structured warnings report each blocked pool and reason. Deletions can themselves
increase indirect allocations: these deletions are retained with detailed warnings.
Malformed CSV and invalid hierarchy changes still roll back the transaction.

## Python calculation and cache consistency

`MappingCatalog.capacity_inputs` supplies a common global direct-allocation
context for Python calculations. Staffing publication, validation and operator
previews use it. Operator simulations rebuild the context after staged changes.
Calculations remain in Python and private staffing details retain their existing
authorization boundary.

Migration 0056 attaches the existing cache-revision trigger to the staffing
projection and rebuilds it through a Python hook. Only changed projection rows
are written. This invalidates affected pools even when their mappings were not
edited directly; a catalog revision also invalidates earlier cached results.
Source tables and applied migrations are preserved.

## C4 level 3 — changed data flow

```mermaid
flowchart LR
    UI[Mapping and import dialogs] --> Services[Mapping and restoration services]
    Services --> Catalog[Global allocation snapshot]
    Catalog --> Python[Python residual capacity calculation]
    Python --> Projection[(Private staffing projection)]
    Projection --> Cache[Existing pool cache revisions]
    Cache --> Readers[Dashboard and planning readers]
```

Tests cover formula examples, availability exceptions, same-pool deduplication,
gross team capacity, cross-pool cache invalidation, restored mapping conflicts,
concurrent writes, CSV collective conflicts and deletions, migration upgrades,
and mapping-mode lifecycle and warning presentation in the browser.
