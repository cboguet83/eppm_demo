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

On 2026-09-10, the complete Python suite passed **1,077 tests and 14 subtests**.
A subsequent **11-test capacity run** also passed, including one additional
operator-upgrade case (1,078 distinct Python tests validated).
Its single opt-in browser test was skipped in the regular run and passed separately
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

Template replacement tests reject malformed headers, row widths, quoting and
out-of-range references/lags before deleting existing records. Legacy predecessor
exports retain portable references and give explicit dependencies precedence.
Operator allocation tests exercise the fingerprint check under the writer lock,
unfulfillable generation, reuse of existing mappings, and capacity periods that
retain absences. Schema administration tests distinguish business administration
from editing/access administration and preserve fixed grants while translating aliases.
Directory/calendar tests cover both SQLite constraint conflicts and operational
failures without private error details or partial writes. Project dialog tests
cover denied creation, blank names and deletion that retains unrelated owners.

A caller audit of Python sources confirmed that the former portfolio row converter
and manager-option helper had no application callers. They and the obsolete
converter-only test were removed; current scoped service, UI and browser workflows
remain tested.

Final workflow checks cover returned Gantt events as well as callbacks, scoped
numeric filters and allocation popups, nested pool groups, and resource Settings
dialogs. A project-details fragment now handles revocation/disable failures locally;
deleted projects no longer render retained details. Empty planning portfolios now
show a project-specific message instead of the unrelated schema-parameter message.

Capacity race tests change actual persisted grants or allocations between calculation
and cache publication. Results are recomputed for a changed scope; repeated changes
produce a bounded retry error without caching stale data. Concurrent schema deletion,
invalid authentication addresses/environments, legacy property inputs, tag deletion,
and empty seed dictionaries are also exercised. The actual `main` entry point keeps
operator seeding separate from Streamlit rendering and fails closed without OIDC
configuration. The permission inventory was cross-checked against all 213 public
business-service methods.

The capacity cache now uses persisted capacity and security revisions from one SQL
snapshot. SQLite WAL file lifecycle and session-activity writes no longer cause
false retry failures. Actual input changes, scope changes and loss of shared-data
permission still invalidate results, including when readable project IDs stay the
same. Deployment initialization installs revision storage before authenticated
reads; migration and legacy operator-cache repair preserve business/access records.
These cases are covered in `tests/test_scoped_capacity_races.py`. The running
development app also passed fresh login, Planning rendering and capacity reload
after a session-activity update.

Portfolio and planning display revisions now use a persisted business epoch/counter
and the current security revision, read in one SQLite snapshot. Session activity,
WAL lifecycle and derived-cache writes no longer discard loaded project pages or
rebuild the Gantt scope. Every protected lookup still checks the current session
and readable projects; role changes invalidate displays even when read scope stays
the same. Metadata-only revision checks avoid installing business write guards;
actual business queries and mutations retain their existing enforcement.

The final responsiveness run on 2026-09-10 passed **1,135 Python tests and 14
subtests**, with one opt-in skip. All **42 focused JavaScript tests** for paging,
lazy task loading, scrolling, permissions and session activity passed.
New regressions cover session activity in DELETE/WAL modes, revoked/disabled/expired
sessions, unchanged read scope after permission changes, committed edits versus
rollback, migration preservation, and actual portfolio/Gantt render callbacks.

An isolated authenticated browser verified rapid scrolling on the development
portfolio containing 10,001 projects and retained the planning viewport and scope.
The database was backed up before the additive revision upgrade. Thirty authorized
revision lookups on the same isolated fixture averaged 8.89 ms before and 2.48 ms
after; this measures the revision lookup, not overall page rendering time.

Further live testing identified two additional causes of disruptive refreshes.
Login/logout audit events incremented the global security revision, disconnecting
unrelated WebSockets; those events now retain their audit records without changing
the permission revision. The transport still denies a revoked or expired session
on either message direction, and actual role/status/scope changes still invalidate
the binding. A regression reproduces another browser's login/logout while an
existing WebSocket remains open.

Expanded Gantt scrolling now hydrates task batches through the authenticated
`POST /api/planning/tasks` route rather than component events. One bounded request
is in flight at a time; its result updates the existing chart rows. Stale scopes
and revisions are discarded, the browser working set remains capped at 100
projects, and a failed request offers an explicit retry. Each batch checks current
read permission for all requested projects, and checks the display revision again
before delivery. HTTP reads do not extend idle timeout. Edits retain their original
authoritative service path and refresh the currently loaded rows. A changed data
revision for the same chart selection preserves its viewport and collapse state.

The expanded 10,001-project development Gantt loaded four HTTP batches during a
rapid-scroll browser check with **zero Streamlit reruns**, preserving its viewport
and scope. A second browser then logged in and out; the first remained on Planning
and continued loading without a reset. This explicitly exercises expanded lazy
task loading, whereas the earlier live check had only scrolled collapsed headers.

Session controls count trusted wheel events in both the page and same-origin
chart frames using passive, throttled listeners. Synthetic scroll events and
background task reads do not extend idle timeout. Temporary network/5xx failures
in activity or session checks retain the current page and retry, rather than
resetting navigation; confirmed 401/403 or account-status changes still exit it.
After restarting the development process to reload its registered component,
the live browser retained Planning during a simulated 503 session response and
recorded genuine Gantt wheel activity through the endpoint's 204 response. This
final run also repeated the four task batches with zero Streamlit reruns and the
independent browser login/logout check successfully.

Application access now isolates account search/selection from navigation and the
audit report. Its nested role/scope editor updates independently of account status,
existing assignments and the effective-access form. Static administrator scopes
also perform a fresh protected catalog read on every editor rerun. The
effective-access form submits its project reference only when the check is requested.
Settings navigation also runs inside a page fragment. Project detail sections have
their own nested fragment, retaining the summary and master list while checking
current project access and loading only the selected section.

Eight regressions in `tests/test_fragment_reruns.py` enqueue real fragment requests
on Streamlit's script runner after initial rendering. They assert that navigation
receives no deltas, the audit is read once, and the project summary is built once.
They also verify denial after revocation/disablement and safe handling of deletion
inside the retained child fragment. These checks do not rely on ordinary AppTest
widget runs, which reconstruct the full script.

An isolated browser session on the running development app then changed the
selected account, roles, named/property/all-project scopes and Settings section.
Decoded Streamlit update messages showed zero sidebar deltas for those
interactions. Switching Contacts, Project log, Useful links and back to Contacts
updated only the detail-section fragment and its active collaboration child;
the summary received zero deltas and retained the same DOM element. No account,
role assignment, project or reference data was changed by this browser check.

The full UI responsiveness run measured `app` statement coverage at **99.03%**
(10,607 of 10,711 statements), meeting
the **99%** project target. The full and focused runs leave 104 uncovered statements;
the 420 existing excluded lines are unchanged. This figure is statement coverage,
not proof that every possible branch or deployment condition has been exercised.

The subsequent public-bundle caching correction passed **120 focused tests** across
real installed static asset serving, OIDC, session transport and planning HTTP
reads. New tests exercise JavaScript/CSS GET, HEAD, range and conditional responses,
missing-bundle HTML fallback, errors, cookie-setting responses and protected paths.
The correction preserves the framework's cache policy only on successful public
bundle responses; application data still receives `no-store`.

A fresh anonymous development browser loaded the reported Multiselect module and
its dependency graph successfully. After the correction, a second page loaded all
86 recorded JavaScript bundles from cache: recorded transfer bytes fell from
2,227,867 to zero. A separate isolated browser aborted the Multiselect request to
reproduce the TypeError, confirmed that the failed import remained failed after
network recovery in that document, and recovered successfully after one reload.
The original user's failed request was not captured, so its specific interruption
cause is not established by this reproduction.

The subsequent master-list paging correction passed **1,181 Python tests and 14
subtests**, with one opt-in skip, plus **62 JavaScript tests**. These runs include
new real-database regressions for overlapping pool-cache subsets, summary/detail
reuse, mutation during cache extension, actor isolation and restricted capacity
inputs. Actual fragment requests verify that paging does not rebuild catalog
controls or the selected summary and still denies access after revocation.
Authenticated badge HTTP tests cover hidden/missing IDs, logout, disabled/revoked/
expired sessions, concurrent allocation/scope changes, body limits, foreign origins,
safe errors and unchanged session activity. JavaScript tests cover immediate row
display, late/malformed badge responses, explicit retry, timeout, bounded requests
and retained scrollbar identity.

Profiling the 10,001-project development portfolio identified repeated scoped
capacity calculations on the row-display path. Before this correction, jumps to
indices 5000, 2500 and 7500 took 1,511 / 1,833 / 2,271 ms to finish loading both
visible rows and off-screen overscan, emitting 58 / 102 / 102 Streamlit UI deltas.
In the final isolated browser run, visible rows appeared after 314 / 359 / 337 ms;
the comparable visible-plus-overscan times were 617 / 744 / 655 ms. Each jump
emitted four UI deltas, confined to the grid. Badges completed separately after
622 / 1,042 / 660 ms. An earlier post-change run measured visible rows at
458–613 ms, so these are local observations rather than a latency guarantee.

A continuous sequence of scroll movements from index 8000 to 9000 retained the
same scrollbar and selected-summary DOM elements, kept the final position and
finished its remaining page work 881 ms after movement stopped. The checks used
an isolated authenticated browser without modifying business data or permissions.
The coverage figure above belongs to the earlier UI run; coverage was not
remeasured for this paging correction.

The Gantt latency follow-up reproduced project expansions at indices 5000 and
7500 taking **9,516 / 8,748 ms**. Enabling external dependencies at index 2500
took **20,693 ms** for the visible rows and **30,518 ms** including overscan.
Both operations already had zero Streamlit reruns; server reads were a major delay.
Profiles identified full-pool capacity loading, repeated display-cache/security
reads and queries that scanned unrelated visible tasks.

The corrected task transport reads one authorized metadata snapshot, loads only
the tasks' assigned pools and checks revision freshness before delivery. Dependency
queries first select the requested successor tasks; scoped ownership checks use
indexed lookups. No write guard or endpoint visibility rule is removed. A database
work regression adds 5,000 unrelated visible tasks and dependencies and verifies
that the requested dependency query's SQLite instruction count remains bounded.
Other regressions verify duplicate project IDs, empty predecessor projects,
batched project bounds, unchanged read-snapshot semantics and scoped pool demand.

Follow-up browser network timing exposed a second cause of intermittent pauses:
one interaction issued **38 concurrent session-activity requests**. The session
component initialized listeners and polling again on repeated frontend renders,
although its cleanup only ran on unmount. These duplicate requests queued ahead
of task reads. The component now retains its controller and throttle state across
renders, with one polling timer and one request in flight per activity/session
check. Regression tests simulate 40 renders, slow responses, replacement content,
unmount/remount and late responses after disposal.

The final isolated browser check after both corrections on the same 10,001-project
development database showed expansions in **622 / 693 ms**, external dependencies
in **661 ms** and all external-link overscan in **1,227 ms**. Scrolling to indices
9000 and 1000 with external links enabled and immediately expanding projects took
**709 / 811 ms**, preserving the viewport. The duplicate activity requests were
absent: the whole browser scenario sent two activity requests at least ten seconds
apart, with no overlap. Task requests started within one millisecond of their
network dispatch. The preceding run measured expansions at 614 / 765 ms and
visible external dependencies at 609 ms.
The chart rendered the same 11 dependency bundles with zero Streamlit UI deltas.
These are observed local timings rather than a general latency guarantee.

The full regression run passed **1,188 Python tests and 14 subtests**, with one
opt-in skip. A subsequent **36-test** task-HTTP run added coverage of the filtered
chart's whole-project predecessor fallback. All **65 JavaScript tests** passed,
including the subsequent session-controller lifecycle regressions.
After that lifecycle correction, **108 focused Python tests** passed across task
HTTP, session transport, actual fragment reruns, planning snapshots and account
presentation/entry. The temporary HTTP timing instrumentation was removed.
Combined statement coverage is **99.01%** (10,678 of 10,785 statements), meeting
the 99% target. The checks retain current-scope denial, allocation redaction,
revision-race rejection and transactional write enforcement.

The dependency-filter follow-up reproduced the reported nine-project group in
**11,873 ms**, including **10,318 ms** for dependency traversal. The context-menu
action emitted two framework rerun cycles and 19 sidebar deltas. The callback now
targets the named planning workspace instead of starting a full application rerun.
Modern dependency traversal uses indexed endpoints; the redacted legacy links
are materialized once, and `UNION` preserves cycle termination. Catalog revision
hashing follows the existing tuple-key convention, and a chart rebuild no longer
reads the same capacity details twice.

The final isolated browser run selected the same nine projects in **2,260 ms**;
the independent dependency lookup took **421 ms**. Predecessor-only and single-
project filters took **2,269 / 2,172 ms**. Each action emitted one chart update and
zero sidebar deltas. Streamlit still uses two internal dispatch cycles to route
the callback; the first now emits zero UI deltas, followed by 15 planning deltas.
These local observations are not a latency guarantee.

New regressions exercise actual component callbacks, retained navigation, current
account disabling, one capacity read per rebuild, hidden-project graph boundaries,
legacy and whole-project links, duplicate seeds and cycle behavior. A deterministic
SQLite-work check holds 5,000 unrelated tasks constant while expanding the
connected group from two projects to eleven, guarding against a repeated global
scan for each discovered project.

Validation passed 1,193 Python tests and 14 subtests in the full run, with one
opt-in skip. One AppTest source-extraction error resulted from a test-file edit
during that run; rerunning the affected module from its final source passed all
30 tests, including the added account-disabling regression. All 65 JavaScript
tests passed. Combined statement coverage is **99.01%** (10,675 of 10,782
statements), meeting the 99% target.

The subsequent page-navigation check reproduced 19 sidebar deltas on each switch
between Portfolio, Planning, Settings and Application access. Navigation now
targets the named `application_page` fragment. Two isolated authenticated browser
runs, including returning to Portfolio and Planning, emitted zero sidebar deltas
on every switch and retained the same navigation and language-selector DOM nodes.
The destination page was checked for visibility; the development health endpoint
returned HTTP 200. These checks did not alter business data.

Navigation regressions assert that the shell and totals reader execute once per
initial load, the selected page replaces the previous page, and explicit redirects
still perform a full application update. Tests also retain language/deep-link
behavior and reject an unavailable route. Real scoped SQLite services deny the
next page read when access is revoked or the account is disabled between initial
render and navigation. Existing WebSocket session-binding enforcement is unchanged.

The navigation follow-up passed 92 focused tests, then the complete Python suite:
**1,198 passed, 1 opt-in skip and 14 subtests passed**. Combined statement coverage
remains **99.01%** (10,682 of 10,789 statements). Changed-file secrets scans and
`git diff --check` also passed.

The contact/log modal follow-up replaces the native Streamlit dialog close/rerun
path with a self-contained Component v2 form using the browser `dialog` element.
All fields are built before opening. Successful callbacks commit through the
existing scoped service, update only the owning list and close the modal after
acknowledgment. Validation failures preserve entered values. The server retains
the project, operation and edited row identity; submissions cannot supply them.

An isolated browser run verified contact removal, contact creation and log creation
with zero sidebar deltas and exactly one initial shell render. Log validation kept
the modal open, and multiline description/comment values were preserved. Opening
and cancelling both modals was also verified in the signed-in development app
without changing its project data; its health endpoint returned HTTP 200.

Validation passed **317 relevant Python tests and 5 JavaScript tests**. Regressions
cover sibling-list isolation, replayed submissions, malformed values, revoked or
disabled actors, safe text rendering, complete-before-open presentation, pending
save protection, validation retry, Cancel, Escape and backdrop dismissal. Combined
statement coverage remains **99.01%** (10,713 of 10,820 statements).

The portfolio project-dialog follow-up restricts `Edit details` to current
`project.edit` scope and opens editing immediately. Business administrators already
hold both creation and editing permissions; viewer, approver, unrelated-project
editor and access-only administrator cases do not expose this action.

Creation/edit actions now run independently from the portfolio and summary.
Reference data is retained only within the open dialog. Basic fields and property
tabs have separate fragments, with current permission checks before rendering.
Hidden property tabs preserve their drafts, including dates. The service still
validates current schemas, constraints and authorization at save time.

An authenticated browser check measured 1,779 ms to open creation, 1,253 ms to open
editing and 679 ms for a basic-field edit. The field edit previously took 1,287 ms
and emitted 52 UI deltas; it now emits 15. These observations include a 300 ms
settling allowance and are not latency guarantees. All measured actions emitted
zero sidebar deltas. Browser checks used unsaved drafts only.

Validation passed **180 relevant Python tests**, including actual fragment dispatch,
role/scope visibility, cross-tab text/date retention, lost permission, deleted-project
saves, existing template/link workflows and project deletion confirmation. Combined
statement coverage is **99.02%** (10,781 of 10,888 statements).

The shared popup presentation follow-up applies the same completion rule to all
40 native dialogs. Browser tests sample animation frames while a deliberately slow
dialog emits fields in separate stages, including a cold multiselect load. Every
visible frame contains the completed form. Reopening, Escape, the close button,
backdrop dismissal and a stopped permission error are covered. Authenticated checks
of project creation, basic-field editing and project editing recorded zero partial
frames and zero sidebar deltas; no business data was saved. Cold opening latency
remains variable, and these checks do not claim instantaneous server reads.

The project permission projection is reused only during one synchronous dialog
render. Tests verify that independent field-fragment interactions read it again,
alongside the existing downgrade, disabled-actor and write-authorization checks.

The full Python suite and corrected-case reruns account for **1,247 passing tests**;
the separate opt-in Keycloak deployment test was skipped. The final targeted run
also dispatches real Cancel fragment events across nine settings dialogs and
verifies that the database remains unchanged. Four existing browser-modal
JavaScript tests pass. Combined statement coverage is **99.00%** (10,820 of 10,929
statements). Older broad component mocks were narrowed to their intended tables,
and the property-form test now navigates lazy tabs and preserves explicitly cleared
text when saving from another section.

Additional ASVS features outside the specified implementation are not claimed:
device/posture risk evaluation, MFA for every non-administrator, self-service session
inventory, an administrator "terminate every session" function, provider back-channel
logout, and remote tamper-resistant log collection. This document does not substitute
for a deployment threat assessment or a complete independent ASVS review.

The subsequent portfolio form change replaces its native project editor with a
prepared Component v2 modal. Browser tests verify complete content at `showModal`,
viewport bounds, local typed inputs/tabs/custom links, validation retries, explicit
deletion confirmation and reopening after dismissal. Real fragment dispatch against
isolated storage verifies one grid/selection update per successful save, no sidebar
deltas, disabled-account denial, protected ENUM denial and forged-delete rejection.
Gantt create/full-edit events now commit before one affected-project chart patch;
a revoked editor cannot create a task through a retained component.

An authenticated development check, using unsaved drafts only, observed creation
opening in 2,526 ms and editing in 2,040 ms, including a 300 ms settling allowance.
Each opening emitted two UI deltas and zero partial frames or sidebar deltas.
Changing a field emitted zero deltas; its 338 ms observation includes that same
settling allowance. The form appeared with all 29 creation controls or 35 editing
controls present. These measurements address staged rendering and unnecessary
reruns; server reads still impose opening latency and are not claimed instantaneous.

Final validation accounts for **1,283 passing Python tests** across the full suite
and corrected/added-case reruns, with the separate opt-in Keycloak test skipped.
The final 48-test run passes, as do all **70 JavaScript tests**. Combined statement
coverage is **99.01%** (10,998 of 11,108 statements), including every statement in
the new portfolio form controller. The revoked-grid assertion now checks removal
of the protected table and absence of new component payloads; an empty modal host
retained outside that fragment does not carry project data.
