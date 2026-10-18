# shared-business-dictionaries Specification

## Purpose

Provide centrally maintained project roles and event types with stable,
dictionary-qualified identities and localized labels while preserving project
integrity, authorization and established collaboration behavior.

## Requirements

### Requirement: Shared catalogs have dictionary-qualified identities

The system SHALL maintain project roles and event types through one shared
dictionary capability. Dictionary and entry codes SHALL remain stable when names
or translations change. Existing numeric IDs SHALL remain valid within their
original dictionary, including IDs shared by the two catalogs.

#### Scenario: Existing catalogs contain the same numeric ID
- **WHEN** a project role and an event type both have ID 7 before migration
- **THEN** both remain distinct entries with ID 7 in their respective dictionaries
- **AND** existing contact and log references retain their meanings

#### Scenario: Rename or translate an entry
- **WHEN** an administrator changes an entry's canonical name or localized label
- **THEN** its dictionary code, entry code and numeric ID remain unchanged

### Requirement: Dictionary administration has a bounded scope

The first release SHALL expose only the project-role and event-type dictionaries
through shared administration. It SHALL reject unknown dictionary codes and SHALL
retain other catalogs, custom-property choices, workflow status rules and packaged
interface translations in their current systems.

#### Scenario: Request an unsupported dictionary
- **WHEN** a caller requests shared-dictionary operations for a workflow status,
  a custom-property choice or an unrecognized dictionary code
- **THEN** the operation is rejected without accessing or modifying another catalog

### Requirement: Names are unique within their dictionary

The system SHALL require nonblank canonical names and enforce case-insensitive
name uniqueness within each dictionary. Identical names in different dictionaries
SHALL be allowed. Catalog reads SHALL retain localized, case-insensitive ordering
with numeric identity as the tie-breaker.

#### Scenario: Create case-equivalent names in one dictionary
- **WHEN** a role named Sponsor exists and another role named SPONSOR is submitted
- **THEN** the second write is rejected without a partial entry or translation

#### Scenario: Reuse a name across dictionaries
- **WHEN** an administrator creates an event type with the same name as a role
- **THEN** both entries are saved independently

### Requirement: Translations have deterministic fallback

The system SHALL resolve the requested locale's stored label and otherwise use
the canonical name. Ordinary canonical-name saves SHALL also save the English
label atomically, retaining other translations. Migration SHALL preserve all
existing translation rows without substituting labels or dropping locales.

#### Scenario: A requested translation is present or missing
- **WHEN** a caller reads a role with French label Parrain and canonical name Sponsor
- **THEN** the French read returns Parrain and a missing German translation returns Sponsor

#### Scenario: Rename a translated entry
- **WHEN** Sponsor is renamed Executive sponsor through ordinary catalog save
- **THEN** the canonical name and English label both become Executive sponsor
- **AND** its existing French label remains unchanged

### Requirement: Administrators can maintain localized labels

Authorized administrators SHALL edit translations in the existing role and
event-type Settings tabs using a common editor. It SHALL offer the five current
application languages, distinguish an absent translation from fallback text, and
allow blank optional labels to remove explicit translations. English editing
SHALL use the canonical-name save operation.

#### Scenario: Add and remove a translation
- **WHEN** an administrator saves a French label and later clears it
- **THEN** the first save changes French reads and the second restores canonical-name fallback
- **AND** neither action changes other labels or references

#### Scenario: View a fallback in the editor
- **WHEN** an administrator opens German translation editing for an entry with no German label
- **THEN** the editor identifies the translation as absent and does not persist fallback text unless explicitly saved

### Requirement: Dictionary input is validated before mutation

The system SHALL validate dictionary codes, entry references, canonical names,
locale identifiers and translation labels at the application boundary. Invalid
input SHALL fail safely without partial persistence or disclosure of internal
database details.

#### Scenario: Submit an invalid locale
- **WHEN** a caller attempts to save a translation using ../private as the locale
- **THEN** the request is rejected and no entry or translation changes

#### Scenario: Edit a missing entry
- **WHEN** a caller edits an entry deleted after the editor loaded
- **THEN** a safe missing-entry or conflict result is returned rather than creating a replacement

### Requirement: Business references enforce dictionary membership

Project contacts SHALL accept only project roles and project logs SHALL accept
only event types. These restrictions SHALL be enforced by the database as well as
application validation, including direct runtime SQL and concurrent mutations.

#### Scenario: Use an ID belonging only to the other dictionary
- **WHEN** a contact is assigned an ID present only in the event-type dictionary
- **THEN** the write is rejected without modifying the contact

#### Scenario: Forge a dictionary discriminator
- **WHEN** direct runtime SQL attempts to assign an event-type dictionary reference to a contact
- **THEN** the database rejects the write even if an event type with that numeric ID exists

### Requirement: Used entries cannot be deleted

The system SHALL reject deletion of roles referenced by contacts and event types
referenced by project logs. Unused entries SHALL remain deletable, with their
translations removed atomically. A rejected deletion SHALL retain the entry and
all translations.

#### Scenario: Delete a referenced role
- **WHEN** an administrator deletes a role assigned to an existing project contact
- **THEN** deletion is rejected and the contact, role and translations remain unchanged

#### Scenario: Delete an unused entry
- **WHEN** an administrator deletes an entry with no business references
- **THEN** the entry and all its translations are removed in one transaction

### Requirement: Existing business authorization remains authoritative

Shared-dictionary writes SHALL require shared business administration permission
on the server and in the database. Shared catalog reads SHALL retain their
existing access rules. Project contacts, logs and dashboard results SHALL retain
current project scoping and sensitive contact-data protections.

#### Scenario: A project editor attempts catalog administration
- **WHEN** a project editor without shared administration permission calls a dictionary write or attempts direct runtime SQL
- **THEN** the write is denied and no labels or entries change

#### Scenario: A scoped reader reads translated project data
- **WHEN** a reader restricted to one project reads contacts, events or dashboard blockers
- **THEN** translations are resolved without revealing records or private contact details outside their authorized scope

### Requirement: Catalog changes commit and replay as one operation

Entry, canonical English label and submitted optional-translation changes SHALL
commit or roll back together. Concurrent conflicts SHALL replay the complete
authorized operation under the existing transaction policy; exhausted retries
SHALL return a safe conflict or storage error without partial changes.

#### Scenario: A translation write fails after the name update
- **WHEN** persistence fails while saving translations in a catalog edit
- **THEN** the entry name and every translation retain their previous committed values

#### Scenario: Administrators rename the same entry concurrently
- **WHEN** two authorized operations rename the same entry
- **THEN** successful results preserve canonical-name and English-label consistency
- **AND** failed operations leave no partial changes

### Requirement: Blocking-point identity survives centralization

The system SHALL preserve existing event-type system classifications and retain
the established Blocking Point creation classifier. Classification SHALL apply
only to event types. Renaming or translating a classified event type SHALL NOT
change its blocking-point behavior or the dashboard's current active-event rules.

#### Scenario: Rename an existing blocking-point type
- **WHEN** the canonical name and French label of a blocking-point event type change
- **THEN** its active events remain dashboard blockers with the appropriate localized label

#### Scenario: Create a role named Blocking Point
- **WHEN** an administrator creates a project role named Blocking Point
- **THEN** it receives no event-type system classification and changes no dashboard blocker result

#### Scenario: Create the first Blocking Point event type
- **WHEN** an event type named exactly Blocking Point is created and no blocking-point type exists
- **THEN** it receives the existing blocking-point system classification

### Requirement: Committed labels invalidate cached displays

Committed dictionary mutations SHALL invalidate affected shared catalog display
revisions so subsequent reads resolve current names and translations. Rolled-back
mutations SHALL NOT publish changed labels. Cache isolation and existing project
authorization SHALL remain intact.

#### Scenario: Change a label after warming a display
- **WHEN** an administrator commits a translation change after a collaboration or dashboard display has been cached
- **THEN** the next authorized display read uses the new label

#### Scenario: Roll back a translation change
- **WHEN** a translation mutation is rolled back
- **THEN** subsequent display reads retain the previous committed labels

### Requirement: Upgrades preserve business data and migration history

An ordered atomic upgrade SHALL preserve catalog identities, names, all locale
labels, system classifications, contacts, log records and earlier migration
checksums. Initialization and upgrades SHALL produce equivalent shared-dictionary
behavior. A failed upgrade SHALL leave the preceding schema and records intact.

#### Scenario: Upgrade populated catalogs
- **WHEN** catalogs containing overlapping IDs, non-English labels and referenced entries are upgraded
- **THEN** all names, labels, classifications and references retain their prior values and meanings
- **AND** subsequent entry creation does not collide with migrated IDs

#### Scenario: Upgrade failure
- **WHEN** an upgrade fails after copying catalogs but before completing reference replacement
- **THEN** the schema, business rows and migration ledger remain at the preceding version

### Requirement: Operator lifecycle operations use shared catalogs safely

Reference/demo seeding and full-reset operations SHALL use the shared catalogs
while preserving their current installation markers and reset boundaries. Ordinary
project flushes SHALL retain catalogs; full reset SHALL retain unrelated catalog
data and restore the established event-type seed behavior.

#### Scenario: Seed again after an administrator changes labels
- **WHEN** ordinary initialization or demo seeding runs against an already initialized catalog
- **THEN** its existing seed-marker rules prevent replacement of administrator-maintained entries and translations

#### Scenario: Flush projects without resetting references
- **WHEN** an operator performs the ordinary project flush
- **THEN** project data is removed according to existing rules and both shared dictionaries remain intact

#### Scenario: Reset reference data
- **WHEN** an operator performs the existing full reset
- **THEN** role and event-type reset behavior uses shared storage and restores the established event seed
- **AND** unrelated dictionaries and preserved organization catalog data remain outside that reset
