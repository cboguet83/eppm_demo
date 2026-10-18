## MODIFIED Requirements

### Requirement: Unchanged WBS shares do not add global save contention
Project saves SHALL avoid global WBS capacity reads and share rewrites when the submitted shares are unchanged. Empty replacements SHALL clear existing authorized shares without reading unrelated capacity facts. Serializable isolation and authoritative project edit checks SHALL remain enabled.

#### Scenario: Ten independent title saves
- **WHEN** ten distinct authorized editors concurrently save separate project titles using stored or browser-form values in small and 10,001-project portfolios
- **THEN** all saves succeed, property values remain unchanged and existing WBS allocations are preserved

#### Scenario: Clear or retain authorized shares
- **WHEN** an authorized editor submits unchanged shares or an empty replacement
- **THEN** existing unchanged shares are retained or explicitly cleared as requested, without global capacity reads

#### Scenario: Upgrade a populated project portfolio
- **WHEN** an existing populated installation is upgraded and authorized editors save independent project titles
- **THEN** existing project records, WBS allocations, constraints and permissions are retained, and independent saves retain the same serializable isolation and bounded retry policy
