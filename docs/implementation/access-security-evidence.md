# OIDC and access-control verification evidence

This is a feature-specific checklist, not an ASVS certification or a claim that
the whole application meets an ASVS level. Identifiers were checked against the
**v5.0.0 release** on 2026-09-09, not the changing main branch. Brief topics below
are paraphrases; the linked release files contain the normative requirements.

Evidence uses actual SQLite transactions and Authlib/JOSE verification. Focused
OIDC tests substitute only remote HTTP responses. The opt-in browser suite uses
real Keycloak, real signed tokens, the actual ASGI launcher, and separate browser
contexts. No browser event, role label, or UI visibility hint grants authorization.
The actual Authlib exchange regression also rejects a token-endpoint profile object
when no ID token was verified. Only the library's parsed `UserInfo` result is accepted
on this path; ordinary token-response JSON cannot substitute for that result.

## Authentication and federation

Release sources: [V6 authentication](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x15-V6-Authentication.md),
[V9 tokens](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x18-V9-Self-contained-Tokens.md),
[V10 OAuth/OIDC](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x19-V10-OAuth-and-OIDC.md).

| ASVS 5.0.0 control | Topic | Implementation and evidence | Boundary / remaining responsibility |
| --- | --- | --- | --- |
| v5.0.0-6.3.2 | No default application administrators | `tests/test_access_security.py`, `tests/test_access_operator.py`: pending-first onboarding, verified-account-only bootstrap, permanent setup marker, concurrent bootstrap | Fictional Keycloak accounts are local-only and receive random passwords; production must not import the demo realm |
| v5.0.0-6.3.4 | Documented authentication paths | ASGI launcher and [deployment guide](access-deployment.md); `tests/test_local_oidc_configuration.py` checks actual Streamlit launcher discovery | Only OIDC signs in users; operator recovery grants access to an already verified identity |
| v5.0.0-6.8.1 | Provider identity namespaces | Exact issuer/subject mapping and no email merge in `tests/test_access_security.py` | Initially one configured provider; storage retains issuer as part of identity |
| v5.0.0-6.8.2, v5.0.0-9.1.1 | Assertion integrity | `tests/test_oidc_authentication.py`: real signatures, invalid key/signature rejection, JWKS rotation | Production provider keys and discovery endpoint must remain trusted |
| v5.0.0-6.8.4 | Verified authentication strength/time | Verified ACR/authentication time; production administrator MFA and recent-write checks in `tests/test_access_security.py` and `tests/test_oidc_authentication.py` | Provider MFA policy and its ACR semantics require deployment verification |
| v5.0.0-9.1.2, v5.0.0-9.1.3 | Algorithms and trusted keys | Asymmetric allowlist; Authlib resolves configured discovery/JWKS; wrong algorithms and keys are rejected in OIDC tests | Review the pinned library behavior on upgrades |
| v5.0.0-9.2.1, v5.0.0-9.2.3 | Lifetime and audience | Authlib lifetime/audience validation plus application expiry bounds; wrong audience, expiry, and future time tests | Keep provider/application clocks synchronized |
| v5.0.0-10.1.1 | Restrict token exposure | Server-side code exchange and PKCE cache; cookie tests verify no identity/access tokens or verifier in browser cookies | Proxy and client debug logging must not reveal callback parameters |
| v5.0.0-10.1.2, v5.0.0-10.2.1, v5.0.0-10.5.1 | Transaction binding and replay resistance | Authlib state/nonce and S256; single-use SQLite state; mismatch and replay tests in `tests/test_oidc_authentication.py` | Browser workflow is also exercised against real Keycloak |
| v5.0.0-10.2.3 | Minimal scopes | OIDC client requests `openid profile email`; realm retains identity timing/ACR mappings | Provider roles/groups are not authorization inputs |
| v5.0.0-10.5.2, v5.0.0-10.5.3, v5.0.0-10.5.4 | Identity, issuer, audience | Exact issuer/subject and metadata/audience pinning; equal-email separation and malformed metadata tests | Issuer changes require explicit identity migration planning |
| v5.0.0-10.4.1, v5.0.0-10.4.4, v5.0.0-10.4.6 | Provider redirect/grant/PKCE configuration | Committed Keycloak realm uses exact callback, code flow, and required S256; real login checks those paths | These are provider controls, not a certification of Keycloak or the enterprise IdP |

## Sessions

Release source: [V7 session management](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x16-V7-Session-Management.md).

| ASVS 5.0.0 control | Topic | Implementation and evidence | Boundary / remaining responsibility |
| --- | --- | --- | --- |
| v5.0.0-7.1.1, v5.0.0-7.1.3 | Timing/federation documentation | Explicit 15-minute idle, 8-hour absolute, earlier token expiry and provider-session distinction in [deployment guidance](access-deployment.md) | Project defaults are not a claim of universal NIST compliance |
| v5.0.0-7.2.1 | Backend session verification | Current database session/status/grants checked by application services and connection middleware; `tests/test_session_transport.py` | Browser activity/UI controls are not authorization evidence |
| v5.0.0-7.2.2, v5.0.0-7.2.3 | Unpredictable session references | Fresh `secrets.token_urlsafe(32)` values, SHA-256 persisted references; `tests/test_access_security.py` and OIDC cookie tests | Protect the signing secret and database independently |
| v5.0.0-7.2.4 | Login rotates the current session | `AccessService.sign_in` replaces/revokes the prior browser session; OIDC/session tests | Other independent browser sessions remain separate |
| v5.0.0-7.3.1, v5.0.0-7.3.2 | Idle and absolute expiry | Clock-controlled boundary tests, reconnect tests, and background checks that do not touch activity | Real production token lifetimes also need validation |
| v5.0.0-7.4.1 | Logout/expiry prevents reuse | Persistent session revocation, rechecked downloads and WebSocket traffic; `tests/test_session_transport.py` | EPPM logout does not perform provider SSO logout |
| v5.0.0-7.4.2 | Disabled-account sessions | Current disabled status denies all protected business operations across sessions | Partial ASVS coverage: disabled status does not itself permanently revoke every session row; reactivation semantics require separate consideration |
| v5.0.0-7.4.4 | Logout visibility | Shared session control on active, pending, and disabled account views; `tests/test_access_presentation.py` | Browser multi-tab workflow is in the opt-in suite |
| v5.0.0-7.5.3, v5.0.0-7.6.1 | Sensitive actions and federation timing | Access changes require verified provider authentication within 300 seconds; no refresh/reconnect extension | IdP-side disabling is bounded by EPPM/token deadlines; no back-channel revocation integration |

## Authorization

Release source: [V8 authorization](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x17-V8-Authorization.md).

| ASVS 5.0.0 control | Topic | Implementation and evidence | Boundary / remaining responsibility |
| --- | --- | --- | --- |
| v5.0.0-8.1.1, v5.0.0-8.1.2 | Operation and field rules | [Permission inventory](access-permission-matrix.md), fixed role sets, protected categorical fields, minimal workflow references | Approval permission is registered; no new approval business process is invented |
| v5.0.0-8.2.1 | Function permissions | Explicit actor on all browser-composed business factories; shared administration checks; `tests/test_business_transaction_security.py` | Operator services require deployment authority and are absent from presentation imports |
| v5.0.0-8.2.2 | Object permissions | Scoped SQL views before pagination/counts/joins/export, persisted child ownership, both dependency endpoints, atomic bulk operations | Direct identifiers and client ownership assertions cannot broaden access |
| v5.0.0-8.2.3 | Field permissions | Protected project type/ENUM mutation checks and audit; minimal employee/capacity projections | The UI disables fields for usability; SQL transaction checks remain authoritative |
| v5.0.0-8.3.1 | Trusted enforcement | `BusinessAccess`, `AuthorizationPolicy`, actor-bound gateways and SQLite mutation guards; forged-event/ID tests | JavaScript permission hints never authorize writes |
| v5.0.0-8.3.2 | Current decisions | Revision-bound connections, actor-isolated caches, current grants and properties; revocation/disable/cache tests | Already displayed data cannot be recalled; subsequent operations are checked |
| v5.0.0-8.3.3 | Originating actor | Explicit application actor remains attached to composed services and downloads | No implicit service or administrator fallback |

## Audit, logging, and failures

Release source: [V16 logging/errors](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x25-V16-Security-Logging-and-Error-Handling.md).

| ASVS 5.0.0 control | Topic | Implementation and evidence | Boundary / remaining responsibility |
| --- | --- | --- | --- |
| v5.0.0-16.1.1 | Logging inventory | [Deployment guide](access-deployment.md): persistent audit plus sanitized operational output | Retention, log collection, access policy, and archive procedures are deployment responsibilities |
| v5.0.0-16.2.1 | Audit metadata | Actor/operator, target, action, outcome, timestamp, correlation, safe changes; real SQLite audit tests | Infrastructure logging must supply its own relevant context |
| v5.0.0-16.2.5 | Sensitive-value exclusion | Tokens/credentials excluded from audit; OAuth/client debug and raw callback access logs disabled; negative logging tests | Verify reverse proxy, IdP, and deployment log configuration |
| v5.0.0-16.3.1, v5.0.0-16.3.3 | Security events | Login/security changes and failure categories; bootstrap, recovery, grant, revoke, status and protected-property audit tests; correlated operational events for propagated business and access-administration denials | Ordinary business-validation errors outside access administration are not all operationally logged |
| v5.0.0-16.4.1, v5.0.0-16.4.2 | Injection and tampering | Safe text validation, JSON audit details, append-only triggers and access-admin-only audit inspection | OS administrators can alter database files; separate protected collection is not implemented by the application |
| v5.0.0-16.5.1, v5.0.0-16.5.2, v5.0.0-16.5.3 | Safe failures | Bounded HTTP problems, sanitized script errors, fail-closed configuration, transaction rollback on failed authorization/audit | Test deployment proxy failures and infrastructure outages before rollout |

## Validation status and gaps

On 2026-09-09, the complete Python suite passed **969 tests and 14 subtests**.
Its single opt-in browser test was skipped in the regular run, then passed separately
against real Keycloak and the rebuilt application image without source bind mounts.
The browser workflow passed three consecutive runs after moving live audit
inspection into the Linux container, avoiding concurrent Windows/Linux SQLite
access to the mounted fixture database.
All **42 JavaScript tests** passed. Repository-wide per-file Sonar secrets scans
were clean; these are secrets scans, not a SonarCloud quality-gate result.

The browser scenario verifies login, pending-account isolation, exact-account
bootstrap, access-administrator isolation from business data, activation, a named
project grant, scoped totals and portfolio rendering, read-only project details,
authorized/unauthorized export fetching, revocation, and logout across two tabs.
The built image's ASGI launcher discovery also passed.

Additional regressions cover strict integer token timestamps, missing/corrupted
nonce state, production Secure/HttpOnly cookies and security headers, stale
application transport bindings, malformed stored grants, scoped child ownership,
and server pushes after revocation. Script-error tests verify that operational
diagnostics contain code location/category without exception payloads or browser
disclosure. Legacy-upgrade tests preserve projects, dependency owners, parameter
identifiers and constraints, retain a recoverable backup, and create no accounts.

Scoped planning-dialog workflows exercise dictionary/free tags, custom/full-period
resource assignments, invalid-date rejection, persisted task ownership despite a
forged browser label/project, preservation of hidden owners, and revocation while
an assignment form is open. Shared directory pages deny project editors before
producing browser payloads. Business-only administrators can create, edit and
delete directory records without receiving access administration or changing
application accounts, identities or grants, including when employee/user emails match.

Allocation popup and Gantt filter tests verify scoped rows, totals, related projects,
owner resolution, and safe rejection of malformed action values. CSV import tests
exercise day/month/year previews, invalid-template preservation, permission changes,
and atomic replacement requiring edit permission on every affected project.
Shared tag menus and scoped task-tag deletion tests retain the same boundaries.
Additional real legacy migrations preserve directory relationships, employee
occupation, pool mappings and demand without creating application identities.

Propagated business authorization denials emit one structured operational event
with actor, correlation, permission category and outcome. Tests cover denied reads,
shared-catalog access, rolled-back writes and log-line injection. They verify that
session hashes, business payloads and routine negative UI permission hints are absent.

Access-administration tests cover denied reads and changes through every public
administration operation, stale reauthentication, invalid scope/profile data and
last-administrator rejection. Operational events omit submitted values and escape
control characters; failed writes leave security records unchanged.

Additional Settings workflows cover storage failures, duplicate employee identifiers,
calendar validation and creation, missing-record editing, resource mapping changes,
stale unassignment confirmations and project-catalog CRUD without modifying application
roles or identities. Streamlit 1.63 AppTest does not serialize native tab containers;
tests supply the selected tab explicitly while keeping widgets and services real.
Flexible-filter and dependency-selector tests preserve current read scopes. An empty
resource-consumption filter now renders no projects until it is cleared.

Portfolio and collaboration regressions exercise scoped numeric facets, malformed
component identifiers, authorized navigation, read-only detail dialogs, disabled-user
cache rejection, contact row actions, stale contact ownership and multiline log creation.
They reproduced two portfolio failures: malformed IDs could raise during conversion,
and an error handler outside the Streamlit fragment did not handle fragment failures.
Portfolio IDs now require positive integers, and safe error handling runs inside the
fragment. Task-tag callbacks allowlist query arguments and retain scoped totals.
Gantt update tests verify scoped hydration, pool-demand refresh, project-filter reruns,
and unchanged tasks/allocations after invalid or unauthorized updates.

Measured `app` statement coverage is **97.75%** (10,363 of 10,602 statements), below the
**99%** project target. Coverage remains unfinished work; the passing workflow tests
do not establish that target. Missing statements include legacy planning and
organization UI branches, schema upgrades, and additional access boundary cases.

Additional ASVS features outside the specified implementation are not claimed:
device/posture risk evaluation, MFA for every non-administrator, self-service session
inventory, an administrator "terminate every session" function, provider back-channel
logout, and remote tamper-resistant log collection. This document does not substitute
for a deployment threat assessment or a complete independent ASVS review.
