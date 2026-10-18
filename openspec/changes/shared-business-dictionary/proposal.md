# Proposal

## Why

Project roles and event types duplicate catalog storage, translation tables and
administration logic. A shared dictionary will give these two business lists one
storage and translation model while preserving their existing references,
permissions and event behavior.

## What Changes

- Introduce shared dictionary definitions, entries and translations in PostgreSQL;
  register only `project_role` and `project_event_type` in this first increment.
- Migrate both existing catalogs and every translation without changing numeric
  role/event-type IDs, contact assignments or project log references. Identity
  remains qualified by dictionary so overlapping IDs are valid.
- Separate immutable dictionary/entry codes from editable canonical names and
  localized labels. Preserve case-insensitive name uniqueness within each list,
  localized ordering and canonical-name fallback.
- Reuse one typed catalog administration path, including translation editing in
  the existing Project Configuration role and event-type tabs.
- Preserve database-enforced reference typing and deletion protection, shared
  business administration permissions, project scoping, transactional writes,
  cache invalidation and blocking-point classification after renames.
- **BREAKING (internal database schema):** replace `project_role`,
  `project_role_translation`, `project_event_type` and
  `project_event_type_translation` with shared storage. Update all active SQL
  callers and operator seed/reset paths in the same release. Existing application
  method signatures and numeric reference contracts remain compatible.
- Exclude hierarchy types, pool types, strategic priorities, project types, tags,
  WBS, custom-property choices, workflow statuses and packaged interface text.
  Do not introduce arbitrary user-defined dictionaries, deactivation semantics,
  a new external API or an external translation service.

The user confirmed project roles and event types as the initial scope. The plan
uses the smallest compatibility-preserving defaults: keep existing Settings
navigation, keep unused-entry deletion, synchronize the canonical name and English
label on ordinary catalog saves, and allow optional translations for the five
current application languages. Preserve any additional existing locale rows.
There are no unresolved business-scope decisions for this increment.

## Capabilities

### New Capabilities

- `shared-business-dictionaries`: centrally stored, dictionary-qualified business
  entries and translations; authorized administration; safe migration and
  integration with project contacts, event logs and dashboard blockers.

### Modified Capabilities

None. Existing planning-cache and privileged-helper requirements remain in force;
their specified behavior does not change.

## Impact

- Domain/application: reusable typed dictionary records and validation, injected
  dictionary transaction ports/service, and compatibility through
  `CollaborationService` catalog methods.
- PostgreSQL: one new ordered migration after the current baseline (0068), typed
  contact/event foreign keys, scoped system classification, shared permissions,
  revisions, and dictionary/translation queries.
- Consumers: collaboration and dashboard adapters; reference/demo seeding,
  reset/maintenance paths; existing Settings composition and catalog forms.
- Tests: real PostgreSQL migration/integrity/security/concurrency coverage,
  application contracts, localized Streamlit forms and authenticated browser
  workflows. No new runtime dependency is needed.
- Documentation: add a focused ADR during implementation extending ADR 0010's
  collaboration persistence decision; retain its transaction and reference
  guarantees. ADR 0012's packaged interface translations and ADR 0063's native
  priorities remain applicable.
