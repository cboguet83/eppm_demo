# PPM Studio Pro - Enterprise Project Portfolio Management

PPM Studio Pro is a portfolio management proof of concept built with Streamlit, PostgreSQL, and Plotly. It supports project details, configurable properties, schedules, organizational hierarchies, resource pools, and portfolio reporting.
  
---

## Architecture and migration status

This branch runs on PostgreSQL 18.6 with a restricted connection pool and explicit
operator commands for migrations, seeding, backups and account bootstrap. See
[ADR 0024](docs/decisions/0024-postgresql-runtime.md) and the
[native runtime guide](docs/implementation/postgresql-runtime.md). The migration
is still in progress: complete regression/coverage, authenticated
load testing and recovery acceptance remain open. The
[evidence log](docs/implementation/postgresql-migration-evidence.md) records the
checks already performed. Existing SQLite files are retained without importing
their business data or application accounts into PostgreSQL.

The layered migration now covers **project types, project creation/editing/deletion,
portfolio browsing, schema administration, organization management, resource pools,
capacity calculations, tag management, planning, project collaboration, and budget
reporting**. See
[ADR 0001](docs/decisions/0001-layered-project-types.md) for the initial dependency
rules, [ADR 0002](docs/decisions/0002-layered-projects-and-portfolio.md) for project
workflows, [ADR 0003](docs/decisions/0003-layered-schema-administration.md) for
schema transactions, and [ADR 0004](docs/decisions/0004-layered-organization.md) for
organization transactions. [ADR 0005](docs/decisions/0005-layered-resource-pools.md)
covers atomic pool/group editing, pure capacity rules, and revision-checked caching.
[ADR 0006](docs/decisions/0006-layered-tags.md) covers tag catalogs and assignments.
[ADR 0007](docs/decisions/0007-layered-planning-core.md) covers atomic task and
dependency operations, CSV import, and scheduling rules.
[ADR 0008](docs/decisions/0008-layered-planning-read-models.md) covers planning
summaries and portfolio overload indicators.
[ADR 0009](docs/decisions/0009-layered-planning-presentation.md) covers the Gantt
screen, dialogs, and cached display loaders.
[ADR 0010](docs/decisions/0010-layered-project-collaboration.md) covers project
contacts, roles, event types, and logs.
[ADR 0011](docs/decisions/0011-layered-budget-reporting.md) covers shared Decimal
budget calculations and reporting. Existing budget storage remains compatible.
[ADR 0012](docs/decisions/0012-presentation-resources-and-locale-state.md) moves
translations and component assets into presentation and isolates locale state.
[ADR 0013](docs/decisions/0013-layered-database-maintenance.md) covers startup,
backups, database maintenance, and seed commands.
[ADR 0014](docs/decisions/0014-layered-application-shell.md) completes the application
shell, Settings navigation, startup composition, and developer command imports.
The application, commands, and tests use the owning `app` modules directly.
[ADR 0015](docs/decisions/0015-retire-compatibility-interfaces.md) removes `src`,
the `app.py` launcher, lazy package exports, and compatibility-only helpers.
Existing SQLite data and applied database migrations are preserved.
[ADR 0016](docs/decisions/0016-project-experience-and-allocation-generation.md)
covers project/contact dialogs, translated property aliases, numbered schedule
exports, and configurable allocation generation.
[ADR 0019](docs/decisions/0019-oidc-identities-and-access-policy.md) adds real OIDC
authentication, independent application accounts, fixed roles, project scopes, and
audited access administration. Start with the
[access deployment guide](docs/implementation/access-deployment.md); it covers local
Keycloak, migrations, exact-account bootstrap, recovery, and production MFA.

### C4 level 2: runtime containers

```mermaid
C4Container
    title EPPM runtime
    Person(user, "Portfolio manager", "Manages projects, planning, and resources")
    System_Boundary(eppm, "EPPM") {
        Container(web, "Application", "Python 3.14 / Streamlit / ASGI", "Authenticated UI and authorized application services")
        ContainerDb(database, "Application data", "PostgreSQL 18.6", "Business records, application accounts, grants, sessions, audit and derived caches")
    }
    System_Ext(provider, "OIDC provider", "Local Keycloak or enterprise identity provider")
    Rel(user, web, "Uses", "HTTPS; explicit local HTTP development")
    Rel(user, provider, "Authenticates", "Browser redirect")
    Rel(web, provider, "Validates authentication", "OIDC code flow with PKCE")
    Rel(web, database, "Runs authorized transactions", "Psycopg connection pool; restricted runtime role")
```

### Source locations

| Location | Purpose |
| --- | --- |
| `asgi_app.py` | Authenticated ASGI launcher |
| `streamlit_app.py` | UI script hosted by the authenticated launcher |
| `app/main.py` | Dependency construction and startup |
| `app/presentation/` | Application shell, pages, components, locale state, and bundled assets |
| `app/application/` | Project/type/schema/organization/pool use cases, capacity services, portfolio queries, ports, and boundary errors |
| `app/domain/projects/` | Project/schema records, validation, and effective property values |
| `app/domain/organization/` | Organization records, validation, and bounded hierarchy traversal |
| `app/domain/resources/` | Pool/group records, validation, deduplication, and daily capacity rules |
| `app/infrastructure/postgresql/` | Native transactions, migrations, authorization, typed queries, derived caches and operator storage |
| `app/infrastructure/authentication/` | OIDC protocol and HTTP integration |
| `app/shared/` | Configuration and logging |
| `scripts/` | Seeding, database maintenance, and benchmarks |
| `tests/` | Existing regressions, layer checks, and migration tests |
| `docs/decisions/` | Architecture decisions and migration status |

## 🚀 Getting Started (Local Development)

### 1. Prerequisites
- Python 3.14.x
- PostgreSQL 18.6
- Virtual environment (`venv` or `conda`)
- Docker and Docker Compose with `!reset` support for local Keycloak

### 2. Environment Setup
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Generate ignored local credentials (refuses to overwrite an existing file)
python -m scripts.configure_local_oidc
python -m scripts.configure_postgresql
```

### 3. Run the Application
Follow the [native deployment commands](docs/implementation/postgresql-runtime.md#deployment-and-operator-commands)
to start PostgreSQL and Keycloak, build the application, provision the restricted
role, apply migrations, configure request signing, and seed explicitly before
starting the UI. Use the generated OIDC and PostgreSQL environment files together.

Open `http://localhost:8501`. First login creates a pending account with no business
access. Use the native guide's `pending-accounts` and `bootstrap-admin` commands
to appoint the intended verified account, then assign further roles explicitly.
The running application checks schema compatibility and never migrates, seeds,
resets or supplies operator credentials. A host process uses
`python -m scripts.run_app` with native database and authentication settings supplied
through its environment.

### 4. Run Automated Tests
Prepare isolated PostgreSQL test credentials and the test service as described in
the [PostgreSQL foundation guide](docs/implementation/postgresql-foundation.md).
Run database tests with the restricted runtime role and separate fixture setup
credentials. The complete suite also needs the `browser-tests` extra, Chromium,
and a current `eppm-demo:local` image for authenticated browser tests.

```powershell
# Run against the isolated PostgreSQL test environment
$env:POSTGRES_TEST_CLIENT_CONTAINER = 'eppm_demo-postgres-1'
$env:EPPM_RUN_OIDC_E2E = '1'
python -m dotenv -f .local/postgresql.env run -- python -m pytest -q --cov=app --cov-fail-under=95

# Run custom-component regressions
node --test tests/*.cjs
```

---

GitHub Actions runs only on manual request. Open **Actions → Application and
PostgreSQL checks → Run workflow**, choose the branch, and start the checks.
Pushes and pull requests do not start CI automatically.

## Project types and custom properties

Manage project types in **Parameters Definition → Project types**. Each template
includes built-in fields and applicable custom properties. Properties apply to all
current and future types by default, or to selected types. Each type can inherit
or override required flags and set typed defaults. Defaults apply only at project
creation. Changing type preserves inactive values and restores their visibility
if they become applicable again.

Values live in `project_property_value`, with ordered child rows for multi-select
and tag items. Template defaults use equivalent relational tables. The Python
`Project.dynamic_attributes` interface remains a dictionary keyed by property ID;
project DataFrames now return dictionaries instead of JSON strings.

PostgreSQL stores these values in native relational tables with foreign keys and
typed values. Migrations are ordered, checksummed and applied explicitly in one
transaction. Old SQLite JSON-column conversion procedures belong to the
[archived migration history](docs/archive/sqlite/README.md); this migration starts
with a fresh PostgreSQL database.

## 🗄️ Database Seeding & Mock Data Generation

PPM Studio Pro supports two complementary database seeding workflows:

### Pool allocation controls

Pool allocation generation and clearing are deployment-only CLI operations. Clearing
removes project/task demand while preserving pools and staffing. Both operations
back up the database before applying changes; neither is exposed in the browser.

Generation first previews the mix without changing the database. Configure:

- Allocated pools as a percentage of all pools.
- Average allocation as the mean capacity percentage of selected pools.
- Overallocated and underallocated pools as percentages of the selected pools;
  the remaining selected pools receive exactly 100% allocation.
- Maximum overallocation as excess above 100%: `20` permits up to 120% usage.
- Pools without employees or teams as a percentage of all pools.

Counts round to whole pools. An impossible average/category combination is rejected
with its feasible range. Generated demand follows available staffing capacity and
calendar changes; unstaffed pools use defined capacity. At 0.001-FTE precision,
achieved percentages can be slightly below their targets; the preview reports both.
Combinations too small to preserve their category at this precision are rejected.

Applying replaces current allocations and adjusts staffing to achieve the requested
unstaffed share. It removes mappings from unstaffed pools and adds an employee to
other pools when needed. Unstaffed pools without positive defined capacity receive
their previous available capacity, or 1 FTE. Existing projects and task dates remain.
The preview reports these changes; a changed database requires a fresh preview.

Run these commands in an operator environment whose `DATABASE_OPERATOR_URL`
identifies the intended migrated database. The
[native guide](docs/implementation/postgresql-runtime.md#deployment-and-operator-commands)
shows how to forward that credential into a separate Docker command. Add
`--apply` only when ready to change data:

```powershell
python -m scripts.pool_allocations generate --allocated-pools 80 --average-allocation 80 --overallocated-pools 20 --max-overallocation 50 --underallocated-pools 50 --unstaffed-pools 10
python -m scripts.pool_allocations clear --apply
```

### Project and contact workflows

Project creation uses the same property tabs as the details panel. Property labels
resolve in this order: selected-language alias, default alias, parameter name.
Maintain translations in **Parameters Definition → Parameters → Parameter alias
translations**. Translations use a relational table; parameter IDs and stored values
remain unchanged.

The contacts tab shows mobile and landline numbers, with **Add contact**, **Reassign**,
and confirmed **Remove contact** actions. Reassignment changes the function while
keeping the role. Employee forms include landlines, and fresh demo seeding supplies
them. Phone fields are optional in the native organization schema.
Deleting a project from its edit popup now requires a separate confirmation view.

Adding a Gantt task retains project focus. The capacity panel can show only
overallocated pools, combined with its selected-project filter. Portfolio rows offer
overallocation navigation through their context menu or ellipsis button. Settings
allocation rows expose **Open** and confirmed **Unassign** actions directly.
The CSV section exports the selected project's schedule and offers an import
template; both start with `step_number`, numbered from 1.

### A. Explicit Demo Seeding (`app/infrastructure/postgresql/seeder.py`)
The deployment command `python -m scripts.seed_defaults` populates the demo catalog.
It is separate from application-account bootstrap and is never run automatically by
the authenticated UI. The catalog contains:
- **5 Schema Groups**: `basic info`, `scoping`, `localization`, `useful links`, `classification`.
- **31 Custom Properties**: Cover all eight supported types, including `URL` and `MULTI_ENUM`, with aliases, applicability, and relational values.
- **5 Project Types**: General, Infrastructure, Digitalisation, Compliance, and Renovation. Localization applies to Infrastructure/Renovation; interfaces apply to Infrastructure/Digitalisation/Renovation. Scope is globally required but optional for General. Infrastructure requires code line; Compliance requires acceptance criteria. Three types provide distinct scope defaults.
- **Discrete Enumeration Sets**:
  - `phase`: `FAI`, `APS`, `APD1`, `APD2`, `EXE`, `CHA`, `DEF`, `N/A`
  - `code_line`: 19 railway lines (`1`, `1a`, `1b`, `2b`, `3`, `4`, `5`, `6`, `6a`–`6k`, `7`)
  - `code_station`: 136 unique railway stations
  - `complexity`: `High`, `Medium`, `Low`
  - `category`: `categ1`, `categ2`, `categ3`
  - `strategic_priority`: `Critical`, `High`, `Medium`, `Low`
- **Organizational Structure**: 5 hierarchy levels, 9 function types, 50 job functions with parent-child management chains, teams, and sample employees.
- **Sample Projects**: One curated project per type, with managers, schedules, dependencies, tags, and resource assignments. Ordinary startup preserves user changes. Install the revised demo catalog in a fresh database or with an explicit full reseed.

### Employee Occupation & Calendar Exceptions

Every employee has a normal **occupation percentage from 0% to 100%**. The default is 100%.

Temporary calendar exceptions override that normal percentage over an **inclusive** start/end date range. For example, maternity leave can be represented as 0% from date A through date B. The application prevents overlapping exceptions for the same employee so that the effective percentage on any date remains unambiguous. Outside an exception period, the employee's normal occupation percentage applies.

Organization saves now run through application services. A team and its membership
save atomically, as do a new employee and an optional initial calendar exception.
PostgreSQL constraints prevent overlapping calendar periods, including concurrent
writes. Complete application transactions roll back together on failure.

Manage these values in **Settings → Organization Structure → Employees**:

1. Add or edit an employee to set the normal occupation percentage.
2. Select an employee in the **Employee Calendar Exceptions** section.
3. Add an exception with start date, end date, temporary percentage, and an optional reason.
4. Edit or delete existing exceptions as needed.

### B. High-Volume Batch Generator CLI (`scripts/seed_database.py`)
For stress-testing, portfolio analytics demos, and UI verification, a dedicated command-line script generates hundreds or thousands of realistic projects with complex task schedules and dependencies:

```powershell
# Generate 50 mock projects with realistic tasks and dependencies
python -m scripts.seed_database --projects 50

# Generate 500 projects with 5 to 20 tasks per project
python -m scripts.seed_database --projects 500 --min-tasks 5 --max-tasks 20

# Append against the configured operator database
python -m scripts.seed_database --projects 100 --no-clean

# Seed with a fixed random seed for reproducible demo datasets
python -m scripts.seed_database --projects 50 --seed 12345
```

#### Supported CLI Options:
| Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--projects` | `int` | `1000` | Total number of projects to generate. |
| `--min-tasks` | `int` | `0` | Minimum tasks / milestones per project. |
| `--max-tasks` | `int` | `15` | Maximum tasks / milestones per project. |
| `--url-variable` | `str` | `DATABASE_OPERATOR_URL` | Environment variable containing the target operator URL. |
| `--env-file` | `path` | unset | Optional protected operator environment file. |
| `--backup-directory` | `path` | configured archive directory | Destination for the pre-operation PostgreSQL dump. |
| `--no-clean` | `flag` | `False` | Appends projects with fresh IDs, preserving existing records and templates. |
| `--seed` | `int` | `42` | Random seed for deterministic data generation. |

#### Generated Mock Data Characteristics:
- **Assigned Project Managers**: Selected from actual persisted organizational functions, with valid foreign keys.
- **Custom Properties**: Projects rotate across types deterministically and receive only applicable values. Values use persisted definitions/options and the same validation as interactive creation.
- **Counts and resets**: Clean generation creates exactly the requested count, including zero. Reference-only initialization creates no temporary projects. Project-only flushes retain templates; full flushes rebuild the catalog. Summaries include type and property-value counts.
- **Milestone Scheduling**:
  - **Single-phase schedules (~20%, when bounds allow)**: One N/A phase lasting 3 months to 3 years.
  - **Multi-phase schedules**: Sequential phases (`FAI` ➔ `APS` ➔ `APD1` ➔ `APD2` ➔ `EXE` ➔ `CHA` ➔ `DEF`), approval milestones, and additional work packages when needed for the requested minimum. Schedule shape is independent of project type.
- **Dependency Graph**: Generates Finish-to-Start (`FS`), Start-to-Start (`SS`), and Finish-to-Finish (`FF`) links internally between sequential phases and cross-project external dependencies.

---

## 🐳 Docker Container Management & Deployment

PPM Studio Pro is containerized following enterprise 12-factor standards using a lightweight, secure multi-stage Docker build.

### Multi-Stage Build Architecture
- **Builder Stage (`python:3.14-slim-trixie`)**: Installs dependencies into a user space (`/root/.local`).
- **Runtime Stage (`python:3.14-slim-trixie`)**: Includes PostgreSQL 18.6 archive clients and runs as an unprivileged user (`appuser`, UID 1000), with HTTP healthchecks on `/_stcore/health`.

---

### Compose and standalone deployments

The [base Compose configuration](docker-compose.yml) requires restricted native
database and OIDC settings. The [PostgreSQL overlay](docker-compose.postgresql.yml)
uses its own named volume; the [local OIDC overlay](docker-compose.oidc.yml) adds
Keycloak. The host data mount retains historical archives and new PostgreSQL
dumps. Reuse the complete environment-file and Compose-file list from the native
guide for subsequent operations, and preserve database/provider volumes.

For a standalone container or production reverse proxy, follow the
[native runtime guide](docs/implementation/postgresql-runtime.md). Supply database
and authentication settings through deployment secret storage or a protected
environment file. Keep authentication enabled during recovery. The image starts
`python -m scripts.run_app`; the UI script alone is not an authenticated launcher.

### Deployment-only seeding

The running application never seeds, resets, or restores administrator privileges.
To change demo data, run an explicit deployment command against the intended
installation using separate operator credentials. For example, in that operator
environment, after reviewing its destructive business-data scope:

```powershell
python -m scripts.seed_defaults --force
```

Seed commands back up existing data and preserve application users, grants, security
audit, and initial-bootstrap state. Run regression tests in the development
environment; the runtime image does not include tests or test dependencies.

### Configuration

[.env.example](.env.example) lists the provider, cookie, MFA, and session settings.
Actual credentials belong in ignored local configuration or deployment secret
storage. `APP_ENV` defaults to production in Compose. `DATABASE_URL` identifies
the restricted runtime connection, `DATABASE_CONTEXT_KEY` signs actor context,
and `DATABASE_OPERATOR_URL` is supplied only to explicit deployment commands.
`EPPM_DATA_DIRECTORY` selects the archive mount. Local ports are generated
consistently by `scripts.configure_local_oidc`.

---
## 📋 Features Overview

Pool capacity summaries and details use private PostgreSQL derived caches and
are reauthorized before reuse across page loads and application restarts.
Project/pool revisions and shared catalog/security revisions invalidate affected
entries after source changes. Cache publication rejects results whose source or
access scope changed during calculation. Daily minimum capacities and single-day
overallocation checks are preserved.
Settings loads only the selected tab and fetches full details for the selected pool.
The Resource Pools settings tab retains capacity totals, overallocation alerts,
resource mappings and allocation details; the daily capacity-versus-demand chart
is no longer displayed. The Planning capacity grid is unchanged.
The first request after invalidation recalculates missing entries with shared inputs;
subsequent requests read the cache. Planning still renders its selected Gantt data,
so sub-100-ms pool reads do not imply a sub-100-ms complete page render.

Planning reuses cached capacity timelines when all assigned projects are selected,
indexes organization/project lookups, and avoids sending selected tasks twice to
the dependency editor. The Gantt reuses overscanned rows and batches scroll work
once per animation frame. The benchmark adapters are still being ported; see the
[authenticated browser performance requirements](docs/implementation/postgresql-migration-plan.md#52-reproducible-responsiveness-test)
for the outstanding acceptance workload. Run the Gantt component checks with:

```powershell
node --test tests/test_gantt_scrolling.cjs
```

Planning now reads a lightweight project directory and loads template-property
values only when those flexible-filter fields are selected. Task/dependency
queries use project/task indexes; predecessor choices for other projects load
on demand without rebuilding the chart or losing an open task-editor draft.
Revision-aware caches reuse selected-scope capacity calculations. Gantt actions
run in a Streamlit fragment, while scrolling stays entirely in the browser.
The pool grid renders only nearby rows/columns and reuses indexed period
statistics (minimum capacity and any-day overallocation detection are preserved).
External dependency links start hidden; enable them with the chart toolbar toggle.
When enabled, their SVG layer is clipped to an overscanned viewport and reuses
unchanged paths. Identical projected links (including collapsed-project links)
are drawn once: click/right-click a shared line to select any underlying dependency
and inspect or edit it. Detail labels are prepared on demand, not while scrolling.

The initial chart sends **project summaries, not every task**. Tasks are requested
for visible expanded projects (and visible external-link endpoints), in batches
of at most 25 projects with a 100-project task cache. Expand All reserves row space
without fetching the entire portfolio. Task batches replace only those rows.
Date/progress edits return patches for the edited project, linked successors and
affected pools; shared-pool warnings update without refetching unrelated projects.
Project summaries use PostgreSQL derived caches with dependency-aware invalidation.
Pool demand uses interval boundaries instead of assignment-by-day nested loops,
and repeated daily values use lossless interval encoding during transport.
Planning totals are available in the navigation pane on every page.

The **Manage Task Resource Pools** dialog reads theoretical capacities directly
for its dropdown and loads cached capacity summaries only for pools assigned to
the task (plus legacy pools without a defined capacity). Changing FTE, dates or
selection no longer recalculates every pool. Assignment and calendar changes
still invalidate the relevant summaries, including single-day overallocation.
The modal and database-backed planning benchmark commands still require native
PostgreSQL adapters. Their earlier SQLite results are retained in the migration
evidence; they do not establish PostgreSQL browser responsiveness. Final acceptance
requires the isolated, authenticated 50-user workload specified in the plan.

Large deployment-side seeds and the first capacity calculation afterward take
longer; filtering the planning view to the projects of interest reduces its task
payload. The authenticated sidebar exposes no seeding or reset controls.

Every actual native seed operation creates a PostgreSQL custom-format archive
before changing the database. With Docker, archives are stored in
`data/backups/postgresql/` on the host. Append seeds, forced seeds and pool-scenario
seeds share this guarantee. Nested seed calls produce one archive, no-op checks
produce none, and a backup failure aborts seeding. Backups are retained until
manually removed. The native runtime guide documents the separate operator
credentials and archive directory.

Pool hierarchy scenarios can be previewed without modifying the database, from
an environment configured with the separate operator credentials:

```powershell
python -m scripts.seed_pool_scenarios --year 2026
```

Add `--apply` to apply the previewed seed without replacing projects or tasks.
Normal project seeds and the default demo seed now include this scenario step:
six base groups, **five units under each Service group and four pools per unit**:
Unallocated (defined capacity, no mapped employees), Overassigned (employee capacity
above theoretical capacity), Underassigned (below theoretical capacity), and Fully
assigned (equal theoretical capacity). Project/task demand is seeded independently
of those employee-capacity scenarios. The default catalog has 100 scenario pools
plus the three original example pools, and 31 groups. Repeated v2 additive calls
are no-ops. Existing v1 generated hierarchies require a full backed-up seed rather
than silently mixing old and new layouts. The legacy annual exception scenario is
no longer generated by this new layout; user calendar exceptions are not removed.
Project/task-free seeds still create the hierarchy without inventing tasks.
Append seeding into a user-defined catalog without the demo organization leaves
that organization's employees and pools untouched.

Settings → Task Tags loads 100 assignments per page. Search, column filters, and
sorting run against the entire database; paging never limits their scope.
Task and dictionary choices load only when an add/edit dialog opens, with task
search limited to 50 matches (an exact `#ID` finds any task). Browser regression
checks: `node --test tests/test_task_tag_table.cjs`.

The Portfolio Overview master list uses seamless, scroll-driven pagination:
100 projects are fetched automatically for the visible scroll position, with
nearby batches prefetched. Only a small row window is rendered, and the browser
retains at most five batches (500 projects). No page selector is needed.
The viewport shows eight projects. Search, column filters, sorting, and header statistics cover
the full matching portfolio, not just loaded rows. Header choices/statistics load
only when opened; search finds values beyond the first 200 distinct choices.
Scroll requests rerun only the portfolio browser fragment. Bounded server caches
are keyed by authorized scope and PostgreSQL source revisions.

The UI calls project types **project templates**; native table/column
names use `project_type`. Details and create/edit dialogs expose
every applicable template property, including unfilled, ungrouped, and custom
properties. Defaults apply only on creation, and effective required-field rules
remain enforced. Portfolio regression checks:
`pytest tests/postgresql/test_portfolio_paging.py tests/postgresql/test_project_type_views.py`
and `node --test tests/test_portfolio_table.cjs`.

1. **📊 1. Portfolio Overview**:
   - Compact eight-row list without a page-title/KPI banner or standalone template filter; portfolio totals remain in navigation.
   - Compact master grid with six curated properties: `phase`, `code_line`, `strategic_priority`, `category`, `category_tags`, and `complexity`; complete template properties in details and dialogs.
   - Project search plus Excel-style per-column filtering, sorting, and statistics.
   - Interactive Master List with single-row click selection, compact same-size summary labels/values, and lazy detail tabs for all template property groups, Project Contacts, and Project log.
   - Resource-overallocation icons open the affected project's Gantt. A project is flagged when its positive allocation overlaps any overloaded pool day, using the shared assigned-capacity/calendar-exception calculation (defined capacity is the fallback only for unstaffed pools).
   - Project creation, editing, and deletion through focused modal dialogs.
2. **📅 2. Planning & Milestones**:
   - Interactive Plotly Gantt timeline chart with 4 dependency link types (`FS`, `SS`, `FF`, `SF`) and lag offsets.
   - Expandable recursive resource-pool group hierarchy with collapsed assignment totals and direct navigation to pool details.
   - Optional **Hide pools unused by selected projects** checkbox filters the resource grid immediately, retains ancestor groups, and removes empty groups. A used pool has a positive project/task allocation to a selected project; filtering does not alter the pool's global demand or its staffing capacity.
   - Real-time constraint violation diagnostics detecting scheduling breaks.
   - Bulk CSV milestone loader with validation and downloadable template.
3. **⚙️ 3. Settings**:
   - Consolidated single settings hub with a top-level section toggle:
     - **🏢 Organization Structure**: Manage 9 areas (Job Functions, Function Types, Teams, Employees with occupation percentages and calendar exceptions, Tag Groups, Tag Dictionary, Project Tags, Task Tags, and Resource Pools with dynamic capacity timelines).
     - **🧩 Parameter Definition**: Dynamic schema builder to manage schema groups, create/edit typed parameters (TEXT, DATE, NUMBER, ENUM, TAGS, HYPERLINK), configure discrete options, and inspect the real-time schema hierarchy tree.
     - **Project configuration**: Maintain project roles and event types. Entries in use cannot be deleted.
4. **🌐 5-Language Internationalization (i18n)**:
   - Full live interface translation across English (`en`), French (`fr`), German (`de`), Luxembourgish (`lb`), and Portuguese (`pt`) with 100% key parity guaranteed by automated unit tests.

### Project contacts and log persistence

The native PostgreSQL schema includes `project_role`, `project_contact`,
`project_event_type`, and `project_log_event`. Catalog labels support locale
fallback through their `_translation` tables. Normal application startup preserves
existing data and never reseeds it.

Contacts reference a role and **function**, not an employee. Occupants' full names
are resolved live (all occupants if several share a function); vacant functions
fall back to their name. One role may be assigned to several functions in the
same project, but an identical project/role/function triple cannot be duplicated.

Log events contain title, description, optional deadline, scope, comment, type,
state and creation/update timestamps. States are New, Active, Completed,
Cancelled, Rejected and Closed. Internal/Global is a classification field, not
an access-control boundary; events are listed under their owning project.
History is loaded in bounded 50-event pages. Forms save through callbacks with
one automatic fragment refresh. Project deletion cascades to contacts and logs.

Initial event types are **General information**, **Blocking Point**, and
**Project update**. Startup does not re-create deliberately deleted catalog
entries. An explicit full demo reset restores these defaults; a projects-only
flush preserves the catalogs and removes project contacts/logs with projects.

Regression checks, using the isolated PostgreSQL test environment described above:
`pytest tests/postgresql/test_collaboration_workflows.py
tests/postgresql/test_project_overallocation.py tests/postgresql/test_project_type_views.py` and
`node --test tests/test_portfolio_table.cjs tests/test_gantt_scrolling.cjs`.
