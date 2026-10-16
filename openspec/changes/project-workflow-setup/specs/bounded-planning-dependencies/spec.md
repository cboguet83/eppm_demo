# Spec Delta

## Purpose

Keep scoped dependency metadata reads bounded as unrelated schedules grow while preserving native row-level authorization, active-plan endpoint identity, and auditable append-only index upgrades.

## ADDED Requirements

### Requirement: Dependency metadata reads remain bounded and authorized
Planning dependency reads SHALL select active, non-deleted owner tasks before resolving only their dependency endpoints. Native PostgreSQL row-level security and hidden-endpoint redaction SHALL remain authoritative, and copied tasks SHALL resolve to their current logical endpoint.

#### Scenario: Grow unrelated visible tasks
- **WHEN** 5,000 unrelated visible tasks and dependencies are added
- **THEN** the selected dependency result remains equivalent, shared-buffer growth is at most 64 and no task/dependency scan examines more than two rows

#### Scenario: Resolve a copied predecessor
- **WHEN** a dependency references an earlier task revision with a current copied endpoint
- **THEN** the read returns current endpoint identity and metadata under the same authorization and bounded-work rules

#### Scenario: Hide inaccessible endpoint metadata
- **WHEN** the caller lacks permission to read an endpoint project or loses project access
- **THEN** dependency reads and authenticated hydration do not disclose inaccessible task metadata

### Requirement: Stable reference indexing preserves existing storage
The system SHALL add the stable endpoint lookup index through a new ordered migration while preserving prior ledger entries and stored business records.

#### Scenario: Initialize and upgrade the index
- **WHEN** a clean database is initialized or an existing schema is upgraded
- **THEN** the stable-reference index exists without rewriting prior migrations or task records
