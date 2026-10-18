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
