# Spec Delta

## Purpose

Keep selected planning-cache reads bounded as unrelated schedules grow while preserving scoped cache fingerprints, active-plan membership, and append-only database upgrade history.

## ADDED Requirements

### Requirement: Selected planning cache reads have bounded task work
The system SHALL resolve selected planning cache sources without scanning unrelated projects' tasks and dependencies, retaining current-plan projections, authorization, dependency visibility and existing cache fingerprints. Bulk and selected reads SHALL return equivalent rows for the selected projects.

#### Scenario: Grow unrelated schedules
- **WHEN** 5,000 tasks and dependencies are added to an unrelated project without changing the selected project's dependency membership
- **THEN** a warmed selected read returns the same rows and uses no more than 64 additional shared buffer accesses

#### Scenario: Read full and scoped caches
- **WHEN** an authorized caller reads all planning cache keys and then selects one visible project
- **THEN** the selected rows and tokens equal that project's rows in the bulk result and inaccessible projects remain excluded

### Requirement: Cache query upgrades preserve storage and security
The query repair SHALL use a new ordered migration without rewriting prior migrations, modifying business records, or weakening function privileges and trusted search paths.

#### Scenario: Initialize or upgrade
- **WHEN** a clean database is initialized or an existing schema is upgraded
- **THEN** the bounded selected lookup is available, prior migration ledger entries and business records are preserved, and the helper remains private with its existing security configuration

### Requirement: Task-source fingerprints have bounded assignment membership work
Task-source fingerprint reads SHALL resolve task membership only for selected active assignments, preserving NULL-task eligibility, deleted/inactive task exclusion, source tokens and native invoker security.

#### Scenario: Grow unrelated task membership
- **WHEN** 5,000 unrelated tasks and dependencies are added without changing selected source membership
- **THEN** task-source fingerprints equal the independent revision oracle and remain unchanged while shared-buffer growth is at most 64

#### Scenario: Upgrade active assignment membership
- **WHEN** an existing schema is upgraded through a new ordered migration
- **THEN** active membership, invoker-security options, grants, local check option, assignment records and prior migration ledger entries remain unchanged
