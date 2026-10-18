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
