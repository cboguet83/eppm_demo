# protected-database-helpers Specification

## Purpose

Protect privileged database integrity checks from temporary-object shadowing while retaining WBS allocation rules, hierarchy constraints, and an auditable, append-only migration history.

## Requirements

### Requirement: Privileged integrity checks use trusted schema resolution
Privileged WBS and hierarchy integrity checks MUST explicitly resolve catalog and application objects before temporary objects. Hardening SHALL preserve the existing constraints and function bodies.

#### Scenario: Temporary objects cannot override integrity checks
- **WHEN** a runtime session creates temporary objects named like trusted application or catalog objects
- **THEN** privileged checks continue to use trusted objects and the WBS helper has the explicit search path `pg_catalog, eppm, pg_temp`

### Requirement: Hardening upgrades preserve migration history
The system SHALL apply helper hardening through a new ordered migration without rewriting previously applied migrations, changing stored business records, or changing the helper's executable body.

#### Scenario: Upgrade an existing schema
- **WHEN** the hardening migration is applied to a schema at the preceding version
- **THEN** prior ledger checksums, helper body, and business records remain unchanged and the hardened helper configuration is installed

#### Scenario: Initialize a clean schema
- **WHEN** the complete migration chain is applied to an empty database
- **THEN** the hardened helper is present and existing WBS allocation constraints continue to reject over-allocation
