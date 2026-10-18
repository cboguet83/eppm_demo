# EPPM: OIDC authentication and scoped application access

## 1. Task and implementation instructions

Implement this specification in the existing EPPM application. Deliver working code, migrations, tests, and documentation; do not stop at another implementation plan.

The objective is to introduce application users, OIDC authentication, fixed roles, and project-scoped authorization. Application access must follow the OWASP requirements in this document, with tests demonstrating enforcement.

### Confirmed product decisions

- Application users are independent of employees.
- Roles and their permissions are fixed in code. Administrators assign roles and scopes; they do not create custom roles.
- First successful OIDC login creates a pending application user with no business access.
- Development uses local Keycloak and the real OIDC flow. There is no fake-identity or anonymous-access mode in the running application.
- The first access administrator is appointed through a one-time deployment-side bootstrap command.
- Access administration and business administration use separate roles.
- Approval permission remains separate from editing and administration.
- Scope belongs to each role assignment and can select all projects, named projects, or projects matching supported property values.

### Repository grounding

Before changing code:

1. Read and follow applicable `AGENTS.md` instructions, including secrets scanning before reading workspace files.
2. Inspect Git state and preserve unrelated working-tree changes.
3. Inspect the existing architecture, database, migrations, configuration, installed Streamlit version, services, components, and affected tests.
4. Inventory existing business entry points and map every one to an explicit permission.
5. Follow Python 3.14 and the existing layered architecture. Introduce no new database technology or external authorization service.
6. Record the resulting architecture in `docs/decisions/` and update relevant C4 documentation.

At the time this brief was prepared, repository source inspection was blocked because the required Sonar secrets scanner was unauthenticated. Source-code details and database capabilities have therefore not been verified. Resolve that prerequisite before reading application files. Do not assume that proposed command names, types, or tables already exist.

The detailed policies below are implementation defaults for this feature. Preserve existing financial and approval business rules. If inspection reveals a conflict with a locked architectural or business decision, explain the conflict and obtain a decision before changing it.

### Security verification reference

Use [OWASP ASVS 5.0.0](https://owasp.org/www-project-application-security-verification-standard/) for applicable authentication, session, authorization, and logging verification. Produce a control-to-evidence checklist with version-qualified identifiers verified against that release. Do not invent identifiers or claim complete ASVS compliance from implementing this feature alone.

## 2. Users, permissions, roles, and scopes

### Users and external identities

For a named-project assignment, use **Search project names or references** to
narrow the authorized choices, check the desired projects in the scrollable
**Projects** list, and choose **Grant access**. Checking or clearing a project
does not create an assignment; the explicit grant retains server-side validation.

Maintain an internal user identifier and an external identity mapping uniquely constrained by OIDC issuer and subject: `iss` + `sub`.

Email and display name are profile attributes, never authorization keys. Do not merge identities by matching email, and do not automatically link identities across providers. Follow the [OpenID Connect guidance on claim stability](https://openid.net/specs/openid-connect-core-1_0.html#ClaimStability).

Users are independent of employee records. Do not require an employee link, create employees automatically, or infer application permissions from employee functions or organizational membership.

Support these states:

| State | Behavior |
| --- | --- |
| `pending` | Authenticated identity awaiting activation; no business access. |
| `active` | Eligible for access through assigned roles. No assignment means no business access. |
| `disabled` | Business access denied, including through existing sessions. |

An unfamiliar identity from the configured and validated OIDC provider creates a pending user without assignments. Concurrent or repeated logins must not create duplicates. Login must never reactivate a disabled user.

An access administrator can register a user before first login if the exact configured issuer and subject are known. Otherwise, use the pending-user workflow. Do not introduce email-only invitations that automatically bind privileged accounts.

### Fixed catalog

Define stable permission codes and fixed role membership in code. Use the existing translation system for user-facing labels. Administrators cannot edit permission definitions or role membership.

At minimum, distinguish project reading, ordinary editing, approval, creation, deletion, protected property management, shared business-data management, and access management. Adapt code naming to repository conventions while preserving those distinctions.

| Role | Capabilities | Scope |
| --- | --- | --- |
| `project_viewer` | Read projects and their authorized related information. | Project scope. |
| `project_editor` | Viewer capabilities and ordinary project editing. | Project scope. |
| `project_approver` | Viewer capabilities and existing approval actions. | Project scope. |
| `access_admin` | Manage application users, role assignments, scopes, and access audit records. | Application-wide. |
| `business_admin` | Read and edit all projects; create/delete projects; manage access-relevant project properties and shared business/reference data. | Application-wide. |

The roles have explicit permission sets. Do not implement implicit role inheritance or assume that an administrator bypasses all authorization.

Approval remains separate from editing and business administration. Existing rules for self-approval, closed periods, historical approvals, and financial integrity remain authoritative. If no approval workflow exists, register the approval role and permission without inventing a new business approval process.

Bootstrap grants only `access_admin`. Other roles require explicit assignments. Access administrators can assign the fixed roles, including administrator roles; this is a powerful permission and must be audited. This design does not claim hard separation of duties against an access administrator who can grant roles.

Raw database backup, restore, reset, and maintenance are deployment-operator functions. Application roles must not bypass scoped access through unrestricted database downloads or maintenance tools. Distinguish these operations from normal business property/schema configuration.

### Assignment and scope rules

A role assignment contains a user, a role, and its scope. The same user can hold multiple assignments with different scopes.

Support three scope types:

1. All projects, selected explicitly.
2. A nonempty set of project identifiers.
3. Projects matching supported property conditions.

Property conditions use an explicit allowlist of stable, single-valued categorical project properties. Support equality and membership in a nonempty set. Combine conditions within one assignment using AND; use additional assignments for alternatives.

Reference stable property/value identifiers rather than translated labels. Reject empty, malformed, unsupported, or unresolved rules. Missing project values do not match. A broken rule must never turn into unrestricted access. Do not support arbitrary SQL, Python, regular expressions, or executable expressions.

Evaluate property scopes using current persisted project values. A project entering or leaving a matching category changes the access supplied by that assignment.

An operation is permitted only when the user is active and at least one assignment both contains the required permission and matches the target project. Never combine the permission from one assignment with the scope of another. Use positive grants only; do not introduce explicit deny rules in this version.

Example:

- Alice has `project_viewer` for all projects.
- Alice has `project_editor` for Project A.
- Alice has `project_approver` where department is Finance.
- Alice may edit Project A only. The global viewer assignment must not broaden her editing scope.

### Protecting properties that control access

Properties eligible for authorization scopes are protected from ordinary editors, even before a particular value is used by a rule.

Changing their values, definitions, or dictionary entries requires `business_admin`. Apply this rule to forms, imports, bulk changes, and indirect operations. Audit these changes because they can alter other users' access.

Do not silently retarget an existing scope when a property or reference value is removed or replaced. Invalid references must deny matching access and be visible to access administrators for repair.

## 3. OIDC and local development

### Authentication boundary

Use a maintained OIDC implementation, preferably Streamlit's native authentication when the installed version supports the required controls. Keep provider-specific behavior behind the authentication boundary.

Use one configured provider per deployment initially. Local development uses Keycloak; production uses the selected enterprise provider. Do not derive application roles from provider group or role claims in this version.

Require:

- Authorization Code flow with PKCE S256.
- State and nonce validation.
- Signature validation with allowed algorithms and provider signing-key rotation support.
- Exact configured issuer, expected audience, and applicable authorized-party validation.
- Token lifetime validation.
- Exact registered callback URLs and controlled post-login redirects.
- HTTPS outside explicitly configured local development.
- Fail-closed behavior for invalid configuration, protocol responses, or identity information.

Use discovery, token verification, and cryptography supplied by the maintained library. Do not implement them manually. Request only the identity claims needed by EPPM and avoid exposing tokens to components or browser code.

Reference: [OWASP OAuth guidance](https://cheatsheetseries.owasp.org/cheatsheets/OAuth2_Cheat_Sheet.html).

### Keycloak development environment

Provide a version-pinned Keycloak Docker Compose service with a repeatable development realm, application client, and fictional test users. Bind development services to local interfaces by default. Configure issuer and callback URLs consistently for both the browser and application process.

Use Keycloak's supported realm import mechanism. Keep real or generated passwords and client secrets out of committed realm files; inject or provision them from ignored local configuration. Document initial setup, startup, resetting the development environment, and changing test users.

Reference: [Keycloak container and realm import documentation](https://www.keycloak.org/server/containers).

The running application has no fake-user setting, anonymous business-access mode, or fallback identity when OIDC fails. Test identity injection belongs only in automated test fixtures.

### Configuration

Use typed settings and safe `.env.example` placeholders. Keep actual secrets in ignored local files or deployment secret storage.

Document provider discovery/issuer configuration, client credentials, callback URL, cookie secret, environment selection, session limits, and local service startup.

Connect configuration to the installed framework's supported authentication mechanism. Do not assume `.env` automatically populates Streamlit authentication secrets. Verify required protections and dependencies before selecting native authentication or a supported integration.

Reference: [Streamlit authentication documentation](https://docs.streamlit.io/develop/concepts/connections/authentication).

## 4. Initial administrator and recovery

### Bootstrap workflow

Add deployment-side commands for pending-account inspection, initial bootstrap, and recovery. The following command names are interfaces to implement, not existing commands.

Initial setup:

1. Start EPPM with OIDC enforced.
2. The intended administrator signs in and becomes pending.
3. The pending screen displays that user's own application account reference, without exposing other accounts or raw identity payloads.
4. A deployment operator verifies the intended account and runs `bootstrap-admin --user-id <id>`.
5. The command activates that account, grants `access_admin`, records an audit event, and permanently marks initial setup complete.
6. The user refreshes the application and gains access to user administration.

Requirements:

- Execute using the configured application/database environment and trusted deployment access.
- Expose no public bootstrap endpoint.
- Target an existing account linked to a verified OIDC identity.
- Never select the first login automatically or grant administrator rights by email alone.
- Atomically perform activation, assignment, audit recording, and setup completion.
- Concurrent bootstrap attempts must allow at most one initial setup.
- Refuse bootstrap after setup completion; restarting, disabling an administrator, or revoking rights must not reactivate it.
- Existing installations containing administrator assignments must not allow another initial bootstrap.

### Recovery and continuity

Prevent changes leaving no active `access_admin`, including concurrent demotions and disables. Enforce this in the authoritative application/database operation, not only through disabled buttons.

Provide a separate deployment-only `recover-admin --user-id <id> --reason <reason>` command. It activates and grants access administration to the explicitly verified account and records operator context, target, and reason.

Recovery requires trusted deployment access. It is not a public page, environment-variable backdoor, or automatic startup action. Do not create a local application password as a recovery bypass.

Demo seeding and business-data reset operations must preserve users, assignments, security audit records, and bootstrap state. A genuinely fresh database requires initial setup again.

## 5. Session security

Use these initial project defaults:

- Idle timeout: 15 minutes.
- No absolute application-session limit while active.
- Identity-token expiry is checked at sign-in; application activity renews the idle deadline.
- Dashboard is the normal landing page; explicit internal project/planning links survive sign-in.
- Access-administration changes require reauthentication within the preceding 5 minutes.
- Production administrator identities require MFA enforced by the identity provider.

These are application defaults, not universal OWASP-prescribed values. Make them explicit and testable. Reference: [OWASP session management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

Refreshing, reconnecting, or opening another tab must not reset an expired authentication period. Background polling does not count as user activity. Reauthentication must use verified provider information rather than a browser-supplied timestamp.

Logout invalidates application access for that browser's application session, including associated open tabs. Document identity-provider logout behavior separately.

Disabling an EPPM user or revoking permissions must affect the next protected operation across all existing sessions. Do not rely on sign-in-time role claims or stale session permissions. Newly granted access may become visible on refresh, but stale permissions must not authorize an operation.

Inspect the installed framework's cookie/session guarantees. Native Streamlit authentication must not be assumed to provide all of these controls. Use a supported integration and the minimum application-session state necessary to enforce the requirements; do not weaken them silently.

Document the bounded behavior of identity-provider account disabling. Do not promise immediate propagation without an implemented and tested revocation mechanism. Application-side disabling must remain independently effective.

## 6. Authorization and application integration

### Application-service boundary

Create a centralized authorization policy used by application services. Presentation checks improve usability but cannot grant permission.

Business-service interfaces receive an explicit trusted actor context. Do not add anonymous or implicit-superuser defaults for existing callers. Keep deployment operations and automated test fixtures explicit and separate from user-facing operations.

Separate responsibilities:

1. Authentication resolves a verified external identity.
2. User resolution finds the internal user and current status.
3. Authorization checks current assignments against the operation and persisted resource.

Deny access when required identity, account, role, scope, permission, or authorization data is invalid or unavailable. No service failure may turn into permission to proceed.

Inventory and protect every reachable business operation: pages, callbacks, fragments, custom component actions, imports, downloads, and user-initiated background work.

Reference: [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

### Data visibility and writes

Apply access filtering before pagination, counts, totals, grouping, and export generation. Project-scoped users receive authorized projects and related information only.

Shared reference lookups return only the fields required by an authorized workflow. Full employee, organization, resource, and shared configuration administration belongs to `business_admin`.

Validate direct identifiers against authorized resources. Guessing a valid project, task, budget, attachment, or export identifier must not disclose or modify it. Use consistent inaccessible/not-found responses where necessary to prevent enumeration.

Reference: [OWASP object-access guidance](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html).

EPPM-specific write rules:

- Derive a child record's project from persisted relationships, not client assertions.
- Require appropriate permission on every affected project for cross-project operations.
- Reject the entire bulk write if any target is unauthorized.
- Project creation requires `business_admin`; ordinary editor scopes do not grant creation rights.
- Recheck permissions and relevant persisted resource state within the mutation transaction.
- Preserve domain validation, financial precision, closed-period restrictions, and approval invariants for every role.

### Streamlit, browser components, and caches

Gate protected rendering and data loading, including direct navigation and callbacks. Pending or disabled users see only their own account status and logout controls.

Treat browser events as untrusted. Reject forged operations and ignore browser-supplied role names, actor identities, project ownership assertions, and authorization decisions.

Preserve framework CSRF/XSRF protections and allowed-origin checks. Authorize every protected action within long-lived connections, rather than trusting the initial connection indefinitely.

Reference: [OWASP WebSocket security guidance](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html).

Review shared caches. Scope-sensitive results must be isolated by effective access context and invalidated when assignments or relevant project properties change. Never store mutable current-user state in shared service instances.

Generated downloads must remain access-controlled when fetched. If an existing download path cannot recheck access, replace that path with controlled delivery. Hiding a button or making a URL difficult to guess is insufficient.

## 7. Persistence and security audit

Follow existing migration, repository, configuration, and dependency-injection conventions. Persist the logical concepts below using the actual repository architecture:

- Users and external identity mappings.
- Role assignments and validated scope definitions.
- Bootstrap completion state.
- Required authorization/session invalidation state.
- Security audit events.

Enforce identity uniqueness and reference integrity in the database. Disable users instead of deleting records required for attribution. Protect bootstrap and last-administrator invariants with transactions and concurrency controls supported by the actual database.

Audit user-state changes, grants/revocations, bootstrap, recovery, protected property changes, and approvals. Record actor/operator, target, timestamp, outcome, correlation identifier, and safe change details. Include authentication/security failures through appropriate sanitized operational events.

Security-changing writes fail if their required audit event cannot be recorded. Normal application functions cannot edit or delete security audit records. Document operational access to those records and their retention configuration.

Never log passwords, tokens, authorization headers, cookie values, client secrets, or complete identity payloads. Sanitize untrusted event fields and use structured logging.

Reference: [OWASP logging guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

## 8. Administration UI

Follow the existing Streamlit presentation structure, styling, and translations.

Provide:

- Login/logout controls and a clear current-user display.
- Pending and disabled account screens with no business information.
- An access administration area for user search, status changes, fixed-role assignment, and scope configuration.
- A readable summary of each assignment, including whether it covers all projects, selected projects, or property conditions.
- Effective-access inspection that explains which assignment grants access to a selected project without exposing unrelated business information.
- Clear validation for invalid scopes, protected property changes, and last-administrator restrictions.
- Access audit inspection for authorized access administrators.

The UI must not suggest that application users are employees or that identity-provider administration grants EPPM administration automatically.

## 9. Required validation

Use pytest for meaningful unit, integration, and boundary coverage, plus browser tests for critical workflows. Follow the repository's coverage requirements and report the actual result; do not add low-value tests just to inflate coverage.

| Area | Acceptance scenarios |
| --- | --- |
| OIDC | Valid login succeeds; wrong issuer/audience, invalid signature, expired identity, and state/nonce failures establish no access. |
| Onboarding | Unknown identity becomes pending without business access; concurrent login creates one user; disabled users remain disabled. |
| Identity mapping | Equal email addresses with different subjects do not merge accounts; the same subject under another issuer is distinct. |
| Roles | Viewers cannot edit; editors cannot approve; approvers cannot edit; access administration does not automatically grant business access. |
| Scope evaluation | Global, explicit-project, and property scopes work; a permission never inherits another assignment's broader scope. |
| Invalid scopes | Empty selections, unsupported fields, missing values, and deleted references never grant unrestricted access. |
| Protected properties | Ordinary editors cannot change classification through forms, imports, bulk operations, or forged events; authorized changes update access. |
| Reads and exports | Lists, totals, filters, related records, and fetched downloads exclude inaccessible data. |
| Writes | Forged identifiers and unauthorized cross-project actions fail; unauthorized bulk operations leave no partial writes. |
| Sessions | Expiry, logout, user disabling, and revocation work across tabs, reconnects, callbacks, and cached views. |
| Bootstrap | Bootstrap succeeds once; concurrent attempts cannot create competing initial administrators; startup does not restore revoked rights. |
| Recovery | Recovery requires the explicit deployment command and reason, targets the verified account, and is audited. |
| Administrator continuity | Concurrent administrator changes cannot remove the last active access administrator. |
| Configuration | Missing or invalid authentication settings deny business access; there is no production-accessible development bypass. |
| Auditing | Required records exist; failed audit persistence prevents security-changing writes; sensitive credentials do not appear in logs. |
| Domain behavior | Existing financial, historical-record, and approval rules still hold for every role. |

Run end-to-end login, pending-user activation, scoped access, and administration tests against local Keycloak. Mock identity boundaries where useful for focused tests, but do not mock away database integrity or concurrency behavior.

Follow the repository's real-database and PostgreSQL validation requirements. If those requirements conflict with the discovered architecture, resolve that conflict before changing database technology. Verify fresh installation and upgrade of an existing database without rewriting applied migrations.

## 10. Deliverables and completion criteria

Deliver:

1. Working OIDC authentication, users, fixed roles, scopes, and authoritative access enforcement.
2. Migrations and tested database integrity/concurrency behavior.
3. Local Keycloak setup and safe configuration examples.
4. Bootstrap, account-inspection, and recovery commands with operator instructions.
5. Administration UI using existing application conventions and translations.
6. ADR and relevant C4 documentation.
7. A permission matrix covering every existing business entry point.
8. Test results and an OWASP control-to-evidence checklist, including any remaining gaps and deployment responsibilities.
9. A reviewed final diff with no unrelated changes or secrets.

Document deployment order: migrate the database, configure the provider and application secrets, start with OIDC enforced, sign in the intended administrator, bootstrap that exact account, and assign further roles explicitly. Include production MFA and session/revocation verification in the deployment instructions.

Do not deploy or describe the feature as complete while business entry points remain unprotected or required access-control tests fail. Do not disable authentication or authorization as a rollback mechanism. Do not commit or create a pull request unless explicitly requested.
