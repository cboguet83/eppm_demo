# PostgreSQL architecture

This describes the migration branch's implemented runtime. Regression/coverage,
load and deployed recovery evidence is tracked separately in
[migration evidence](postgresql-migration-evidence.md).
[ADR 0024](../decisions/0024-postgresql-runtime.md) supersedes the SQLite storage
decisions. Existing business rules, optional hierarchy types and Finance editing
controls are retained. Planning revisions and stale-form protection are separate
work, not features of this migration.

## C1 — System context

```mermaid
C4Context
    title EPPM system context
    Person(user, "Application user", "Works with portfolios, projects, Finance and resources according to application grants")
    Person(operator, "Deployment operator", "Installs schema, provisions access and performs backups and recovery")
    System(eppm, "EPPM", "Portfolio management application")
    System_Ext(identity, "OIDC provider", "Authenticates identities; local development uses Keycloak")
    Rel(user, eppm, "Uses")
    Rel(user, identity, "Authenticates")
    Rel(eppm, identity, "Validates code-flow authentication with PKCE")
    Rel(operator, eppm, "Maintains through explicit operator commands")
```

Provider authentication establishes identity. Application accounts, grants and
current session state determine permissions; provider profile fields do not grant
business or administration access.

## C2 — Containers

```mermaid
C4Container
    title EPPM runtime and operator processes
    Person(user, "Application user")
    Person(operator, "Deployment operator")
    System_Ext(identity, "OIDC provider", "Keycloak or enterprise provider")
    System_Boundary(eppm, "EPPM") {
        Container(web, "Application", "Python 3.14 / Streamlit / ASGI", "UI, authentication and authorized HTTP endpoints")
        ContainerDb(database, "Application database", "PostgreSQL 18.6", "Business data, accounts, grants, sessions, immutable history and derived caches")
        Container(commands, "Operator command process", "Python 3.14 / PostgreSQL archive clients", "Explicit migrations, seeds, access bootstrap/recovery and archives; runs on the host or in a short-lived container")
    }
    Rel(user, web, "Uses", "HTTPS; explicit local HTTP development")
    Rel(user, identity, "Authenticates", "Browser redirect")
    Rel(web, identity, "Validates authentication", "OIDC")
    Rel(web, database, "Runs authorized transactions", "Restricted Psycopg pool")
    Rel(operator, commands, "Invokes explicitly")
    Rel(commands, database, "Maintains and archives", "Separate operator credentials")
```

The application never receives the operator URL. PostgreSQL has separate durable
volume storage. Native archives and retained old SQLite files are filesystem
artifacts outside the active runtime; SQLite data and accounts are not imported.

## C3 — Runtime components

```mermaid
flowchart LR
    subgraph Application
        Launcher[asgi_app.py / st.App]
        Routes[Authentication, session, planning and download routes]
        UI[Streamlit shell, pages and custom components]
        Composition[app.main and app.security factories]
        Resources[RuntimeResources]
        Access[AccessService / AuthorizationPolicy]
        Services[Business application services]
        Gateways[PostgreSQL gateways and transaction-bound stores]
        Pool[Database: restricted process pool]
        Caches[DerivedCacheState / PostgreSQL derived-cache adapters]
        Launcher --> Routes
        Launcher --> Resources
        UI --> Composition
        Composition --> Access
        Composition --> Services
        Composition --> Resources
        Routes --> Access
        Routes --> Services
        Access --> Gateways
        Services --> Gateways
        Resources --> Pool
        Resources --> Caches
        Gateways --> Pool
        Gateways --> Caches
    end
    Pool --> PostgreSQL[(PostgreSQL: RLS, signed actor context, constraints and audit)]
```

The launcher owns pool startup/shutdown through `RuntimeResources.lifespan`.
Startup checks schema compatibility and runtime privileges without migrating or
seeding. Entry-point factories inject the same pool/cache resources and each
request's `BusinessAccess`. UI code calls services rather than acquiring storage.

Complete read callbacks use repeatable-read snapshots; writers use serializable
transactions. The transaction runner retries only complete callbacks after SQLSTATE
`40001` or `40P01`, rebinding the actor and checking current permissions each time.
Unknown commit outcomes and unrelated errors are not automatically replayed.
Database row policies and guards also enforce access for direct runtime SQL.

Derived cache publication checks current scope and source fingerprints. Cache
records are not financial or business truth: approved Finance and audit records
remain immutable, while authoritative monetary values use decimal/numeric storage
and exact form transport.

`PostgresPortfolioReader.revision` reads two compact fingerprints from
`eppm.portfolio_cache_revision()`: current actor/session/catalog/security/scope,
and the complete visible project and pool generations. Whole-view invalidation
uses the existing owner-revision triggers instead of expanding dependency and
demand graphs. Per-project and per-pool calculation fingerprints still include
their scoped dependencies. Every display-cache lookup reauthorizes its caller.

## C4 — Planning code example

```mermaid
classDiagram
    class RuntimeResources {
        +Database database
        +DerivedCacheState caches
        +lifespan(application)
    }
    class Database {
        +open()
        +close()
        +run(operation, write, bind)
        +statistics()
    }
    class PlanningService {
        +read_task_bundle(project_ids)
    }
    class PlanningGateway {
        <<Protocol>>
        +run(operation, write, permission, project_ids)
        +get_project_summaries(project_ids)
    }
    class PostgresPlanningGateway {
        +run(operation, write, permission, project_ids)
        +get_project_summaries(project_ids)
    }
    class PostgresPlanningStore {
        +read_task_bundle(project_ids)
    }
    class ActorBinding {
        +BusinessAccess access
        +__call__(connection)
    }
    class Connection["psycopg.Connection"]
    RuntimeResources o-- Database : injected pool
    RuntimeResources o-- DerivedCacheState : shared cache state
    PlanningService o-- PlanningGateway : injected gateway
    PlanningGateway <|.. PostgresPlanningGateway : structural implementation
    PostgresPlanningGateway o-- Database : injected pool
    PostgresPlanningGateway --> PostgresPlanningStore : creates for each callback
    Database --> ActorBinding : invokes transaction binding
    PostgresPlanningStore o-- Connection : caller-owned connection
```

`create_planning_service` in `app/main.py` constructs this service/gateway pair.
`run_business` in `app/infrastructure/postgresql/business.py` supplies the complete
callback and `ActorBinding` to `Database.run`. Binding signs the actual backend
and transaction context; a store borrows that connection and never commits it.
The store returns application records defined in `app/application/ports/planning.py`.
The service does not import PostgreSQL or UI packages.

The planning workspace also receives a `PlanningSourceReader` for bounded task
delivery. It captures initial chart revision/fingerprint data before chart reads;
HTTP delivery compares the selected sources before and after reading task data.
The composition root injects `PostgresPlanningSources`. Its native source query
expands only the selected projects and assigned pools while preserving current
actor, scope and shared-source checks.

```mermaid
classDiagram
    class PlanningWorkspace
    class PlanningSourceReader {
        <<Protocol>>
        +capture(project_ids) PlanningDisplaySources
        +read(project_ids) dict
    }
    class PostgresPlanningSources
    class PlanningDisplaySources {
        +tuple revision
        +dict tokens
    }
    class Database
    PlanningWorkspace o-- PlanningSourceReader : injected reader
    PlanningSourceReader <|.. PostgresPlanningSources : structural implementation
    PostgresPlanningSources o-- Database : injected pool
    PostgresPlanningSources --> PlanningDisplaySources : returns snapshot
```

See the [runtime guide](postgresql-runtime.md), [backup guide](postgresql-backups.md)
and [diagnostic tools](postgresql-benchmarks.md) for operational commands. Source
and test import guards prevent the archived SQLite adapters from re-entering the
application, tools or active tests.
