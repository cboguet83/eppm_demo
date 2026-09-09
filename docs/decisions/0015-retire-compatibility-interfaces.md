# ADR 0015: Retire compatibility interfaces

- Status: Accepted; supersedes the compatibility-retention portions of ADRs 0001–0014
- Date: 2026-09-09

## Decision

The user requested removal of all adapters and elements retained for compatibility.
The layered implementation is now the sole supported application API.

Removed interfaces include the `src` package, the root `app.py` launcher,
`app/compatibility.py`, lazy exports from `app`, script-level re-exports of database
implementation functions, startup flag aliases, and compatibility-only budget and
schema validation helpers. Schema identifier previews require an initialized
database and use canonical `PRM_` codes. Application errors remain safe typed
exceptions; there is no adapter that translates them back to SQLite errors.
The obsolete bulk project export, unused schedule model classes, unused planning
bounds cache wrapper, and seeder alias are removed as well. Planning reads request
explicit property IDs; presentation
consumes attribute dictionaries keyed by those IDs, without parsing historical
JSON strings or looking values up by a translated name/display alias.

| Former interface | Supported owner |
| --- | --- |
| `streamlit run app.py` | `streamlit run streamlit_app.py` |
| `python app.py` startup options | `python -m app.main --help` |
| `from app import ...` helper exports | Explicit imports from the owning `app` module |
| `src.repositories.*` | Services composed in `app.main`; infrastructure adapters for persistence tests |
| `src.views.*` | Injected pages and components in `app.presentation` |
| `src.services.*` static helpers | Domain rules or presentation projections, according to responsibility |
| Database functions re-exported by scripts | `app.infrastructure.database`; commands invoke maintenance services |

Startup flags are `--force-reseed` and `--projects`; abbreviated and retired flags
are rejected by the command-line entry point before opening storage.

`PoolResourceContribution` and `PoolCapacityDetail.contributing_resources` replace
the historical function-oriented names. Redundant capacity property aliases are
removed. Capacity-cache format version 2 invalidates and rebuilds version-one
derived records instead of retaining an old-model decoder.

## Architecture and persisted data

C4 container and component relationships remain those in ADR 0014. The removed
compatibility modules are not runtime components. Docker copies/mounts only the
supported application, commands, launcher, configuration, and persistent data.
Package discovery and coverage configuration exclude the deleted package.

Applied database migrations remain unchanged. They upgrade persisted data and
preserve rollback/integrity guarantees; they do not expose the retired Python API.
SQLite tables and business rules for project types, function/team mappings,
unspecified pool capacity, and stored budget amounts are unchanged.

## Validation

Business, persistence, performance, and Streamlit regression tests now invoke
supported services, typed records, and explicit presentation formatters. Tests
that solely asserted identity of removed exports or their obsolete form helpers
are removed. Architecture checks forbid legacy imports in the application,
commands, and tests, and assert that the retired files and exports are absent.

New regressions verify safe rejection of retired startup flags and recomputation
of old capacity-cache data. Package and Docker checks verify that distribution
artifacts contain the supported code and no compatibility package or launcher.

Final validation on Python 3.14.6:

- Python: 491 tests and 14 subtests passed.
- Custom-component JavaScript: 23 tests passed.
- Ruff import/name checks (`F401`, `F811`, `F821`, `F822`, `F823`) passed.
- A freshly built wheel imported independently of the checkout and included all
  14 HTML/JSON presentation assets. The Docker image passed the same import and
  component checks without mounting the development database.
- The refreshed development container is healthy, mounts no retired source paths,
  and keeps `data/ppm_mock.db` with reseeding disabled.
- Statement coverage is 89.56% (7,429 of 8,295 statements). The repository-wide
  99% target remains unmet; the principal gaps are presentation paths and older
  database migration branches.
