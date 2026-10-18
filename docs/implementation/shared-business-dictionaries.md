# Shared business dictionaries

Project roles and event types use the typed dictionary operations defined in
`app/domain/dictionaries.py` and `app/application/services/dictionaries.py`.
The application service accepts an injected transaction gateway; it never opens
storage itself. Other catalogs remain outside this capability.

Names are trimmed and required. Locale identifiers are bounded language tags,
normalized to lower case for new requests. Canonical-name saves also submit the
English label. Omitted translations are preserved; explicitly blank non-English
labels remove overrides. Invalid input fails before entering the gateway.

All mutations request `business.manage`. The gateway and database remain
authoritative for permissions, transaction isolation and reference integrity.
Catalog projections retain numeric `id`, canonical `name` and resolved `label`.

## PostgreSQL upgrade

Migration 0069 replaces the four old catalog tables with three shared tables.
Keys include dictionary code, including the generated role/event discriminators
on project contacts and logs. Existing IDs, labels and system classifications are
copied atomically. The immutable code is `entry_<id>`, qualified by dictionary;
the common sequence is advanced beyond migrated IDs. Only names and labels are
editable through runtime grants. The Blocking Point insertion classifier is
restricted to event types and survives name changes.

Run the operator migrations with application writers stopped, and deploy the
matching application release. Earlier migration files remain unchanged. Use the
existing verified backup procedure before upgrade. Migration failure rolls back
the complete transaction; after success, repair forward or explicitly restore
the verified pre-upgrade backup before restarting an old binary. Restoration can
discard later writes and is not an automatic down migration.

## Shared reads and writes

`PostgresDictionaryStore` runs on the caller's existing authorized connection.
`PostgresDictionaryGateway` uses the normal whole-operation transaction retry
boundary and translates storage failures to safe application exceptions.
`CollaborationService` keeps its `role` / `event_type` method contracts and
delegates its catalog operations to this same store. Contacts, logs and dashboard
blockers join the dictionary code as well as the numeric ID. No translated label
is used to identify blocking-point behavior.

An entry edit writes its canonical name and submitted locale rows atomically.
Optional labels are deleted when explicitly blank and omitted locales remain
untouched. Explicit translation reads distinguish absent rows from fallback
display labels. Concurrent edits replay the full authorized transaction.

## Operator lifecycle

Reference and demo installers use dictionary-qualified entries and labels. The
existing reference/demo markers retain their prior meaning, so ordinary startup
does not restore removed event choices or overwrite configured translations.
Ordinary project flush retains both lists. Full reference reset clears only their
entry rows, preserves the definition rows and unrelated catalogs, and restores
the established event-type seed. Sequence repair advances the common entry
high-water mark before reset and never rewinds it.

## Settings translation editor

Open Settings → Project Configuration → Project roles or Event types. Both tabs
use the shared editor while retaining independent selections and lazy loading.
The Name field is also the English label. Optional French, German, Luxembourgish
and Portuguese fields show explicit stored labels; an empty field means that
reads use the canonical name. Saving an empty optional label removes the override.
Additional stored locales are preserved. Save writes the entire submitted edit
atomically, and deleting a referenced choice remains prohibited by PostgreSQL.
