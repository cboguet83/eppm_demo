# Deploying OIDC and application access

This feature uses Python 3.14, Streamlit 1.63.0, Authlib 1.8.0, and the existing
SQLite database. Read [ADR 0019](../decisions/0019-oidc-identities-and-access-policy.md)
and the [permission inventory](access-permission-matrix.md) before rollout.
A successful local login does not replace the production checks below.

## Deployment order

1. Stop application writers and make a restorable SQLite backup, including any
   committed WAL contents. Use SQLite's backup API or an existing deployment backup
   procedure, not a copy of the main database while writers are active. Retain the
   pre-upgrade application image and verify the backup in a separate directory.
2. Apply the idempotent migrations to the intended database using the deployment
   account: `python -m scripts.access_admin --database /absolute/path/eppm.db migrate`.
   Security tables, audit protection, scope identities, and bootstrap state are
   installed alongside the existing business schema. Application startup does not
   migrate, seed, reset, or restore administrator assignments.
   This also installs the display revision and its business-table triggers for
   portfolio/planning caching. Run the migration before using the updated display
   code on an existing database; no project records or role assignments are reset.
3. Register one confidential OIDC client with the provider. Enable authorization
   code with PKCE S256, use only the exact `${APP_ORIGIN}/auth/callback` redirect,
   and disable implicit, password, and service-account grants for this client.
   Ensure ID tokens include the verified subject, issuer, audience, nonce,
   authentication time, issue time, and expiry. Keycloak's `basic` client scope
   supplies `auth_time`; retain it along with `profile`, `email`, and `acr`.
4. Configure the environment shown in `.env.example`. Use deployment secret storage
   for the confidential client secret and an independent random cookie secret.
   Set `APP_ENV=production`, an HTTPS application origin and exact issuer, and
   `OIDC_ALLOW_LOCAL_HTTP=false`. The `OIDC_MFA_ACR_VALUES` allowlist must name ACR
   values whose provider policy actually enforces MFA. Requesting an ACR alone
   does not configure provider MFA. Provider roles/groups do not grant EPPM roles.
5. Start the ASGI launcher: `streamlit run asgi_app.py`. The Docker image uses this
   entry point. Keep the supplied origin/XSRF and trusted-session-header settings.
   Plain `streamlit_app.py` cannot compose authenticated business services.
6. Have the intended first administrator sign in. The pending screen displays only
   that account's reference. Verify the identity through the trusted deployment
   process, then bootstrap that exact reference as described below.
7. Refresh the administrator's browser. Explicitly activate users and grant each
   fixed role with its own scope. Bootstrap gives access administration only.
   Assign business administration separately if the operator is also meant to
   manage projects or shared configuration.

With an HTTPS reverse proxy, preserve the public Host and Origin, support WebSocket
upgrades, and configure trusted proxy handling so the application reconstructs the
exact HTTPS callback URL. Restrict direct access to the backend. Verify this with
the actual deployment proxy; do not relax callback/origin checks to fix routing.
The supplied Compose port binding is loopback-only.

## Bootstrap and recovery

Run commands as the trusted deployment account against the explicit database:

```text
python -m scripts.access_admin --database /absolute/path/eppm.db pending-accounts
python -m scripts.access_admin --database /absolute/path/eppm.db bootstrap-admin --user-id 17
python -m scripts.access_admin --database /absolute/path/eppm.db recover-admin --user-id 17 --reason "Verified recovery ticket INC-123"
```

Replace `17` with the verified account reference. Neither email nor the first login
selects an administrator. Bootstrap permanently closes after initial setup or any
access-administrator grant. Disabling/revoking administrators does not reopen it.
Recovery is a separate audited operation requiring an existing verified identity,
explicit target, nonempty reason, and deployment filesystem authority. There is no
public bootstrap/recovery route or local password bypass. Ordinary administration
cannot remove the last active access administrator.

Account inspection returns up to 200 pending accounts in reference order. Use
`pending-accounts --after-id 217 --limit 100` to continue after the last returned
reference. The pending-status filter is applied before pagination.

## Local Keycloak

Docker Compose must support `!reset` overrides. Generate new ignored credentials:

```text
python -m scripts.configure_local_oidc
docker compose --env-file .local/oidc.env -f docker-compose.yml -f docker-compose.oidc.yml build app
python -m scripts.access_admin --database data/ppm_mock.db migrate
docker compose --env-file .local/oidc.env -f docker-compose.yml -f docker-compose.oidc.yml up -d
```

Open `http://localhost:8501`. Keycloak 26.7.2 runs at `http://localhost:8080` and imports
the `eppm` realm. Both containers share a network namespace so the application
process and host browser use the same issuer; no custom DNS or hosts-file entry is
needed. These HTTP settings are confined to explicit local development.

After the containers start, run account commands and database inspection inside
the application container. For example, append
`exec -T app python -m scripts.access_admin pending-accounts` to the same Compose
command above. The browser tests also read audit counts this way. Concurrent
Windows SQLite inspection of the Linux container's mounted database caused writer
lock failures during verification; stop the application before using host-side
SQLite tools, or perform the operation entirely inside its container.

The generated file contains independent random passwords for the fictional users
`alex.admin`, `sam.editor`, and `robin.viewer`, the local provider operator, the
client, and the application cookie. Obtain the relevant local password directly
from that private file; do not paste it into chat, commit it, or print an expanded
Compose configuration. Restrict its parent directory with the operating system's
file permissions/ACLs. Provisioning refuses to overwrite an existing file.

Use `--origin http://localhost:8502 --provider-port 8082 --output .local/other.env`
for different local ports. A separate Compose project name, environment file, and
`EPPM_DATA_DIRECTORY` are required for an isolated database/provider deployment.

Keycloak imports only a realm that does not already exist. Editing the realm JSON
or generating new passwords does not alter an existing provider volume. Change
test users through Keycloak administration or recreate only the intended disposable
provider volume. Never delete the application database to reset the provider.
Deleting/recreating a provider realm may change identity subjects: verify mappings
before reusing an application database. Changing the issuer creates distinct
identities, even when emails or usernames are unchanged.

## Sessions, logs, and audit operations

Defaults are 900 seconds idle, 28,800 seconds absolute, and the earlier verified
ID-token expiry. Access-administration writes require provider authentication within
300 seconds. Refreshing, reconnecting, and background status polling do not extend
authentication time. User interaction extends idle time only within the remaining
absolute/token lifetime. Each protected operation reads current account state and
permissions, including downloads and long-lived Streamlit connections.

Application logout revokes the browser's EPPM session across its open tabs. It does
not end the provider's SSO session; the next EPPM login nevertheless requests fresh
authentication. Provider-side disabling is not continuously introspected and has
no back-channel logout integration in this version. Its maximum remaining EPPM
access is bounded by the earlier application absolute/idle/ID-token deadlines.
Disable the EPPM account to deny its next protected operation independently.
Disabling leaves session rows in place so the browser can display its own disabled
account status. Reactivating the account can restore access through an otherwise
unexpired session. This version does not provide an administrator action to
permanently terminate every session; use provider reauthentication/session lifetime
policy and the documented recovery process when handling compromised identities.

Security audit entries are append-only through application interfaces and database
triggers. Required audit insertion is part of the same transaction as a security
change. Deployment administrators can still access database files; protect them and
their backups through OS permissions and the deployment's storage controls.
The application does not purge security audit records. Define retention, backup,
archive access, and legal deletion procedures in the deployment policy. Expired
transient OIDC state is pruned when new login state is created.
Application session records also require a deployment retention policy; the runtime
does not currently prune expired session rows or limit independent concurrent logins.

Operational security events contain an event category, reference, and sometimes
an exception class. Script failures also record the source basename and line number;
they never record exception messages, source text, local variables, or full traces.
No token/cookie/credential values or raw provider errors belong in these events.
Rejected business transactions also emit `security.event` followed by a JSON
record with action `business.authorization_denied`, actor reference, correlation,
permission category and denied outcome. These records survive transaction rollback
in the operational log; they contain no SQL, row values or session hashes. Normal
UI permission probes do not emit failed-operation events. Include these operational
events in the deployment's protected log collection and retention policy.
Access-administration operations use the same JSON event format, with actions
`access.authorization_denied` or `access.validation_failed`. The event records
whether fresh authentication is required; it omits submitted scope/profile values
and exception text. Administration permission is checked before validating changes,
and rejected changes are rolled back before their operational event is recorded.
Do not re-enable OAuth/HTTP-client debug logs or raw callback query logging in the
application or reverse proxy. Demo business reset operations preserve application
users, grants, security audit, and bootstrap state.

## Page navigation

The sidebar navigation callback targets the named `application_page` fragment.
Switching pages renders only the selected page, leaving account controls, language,
navigation and planning totals mounted. Totals are read on a full application run,
including language changes and explicit redirects, rather than on every page switch.
Nested page fragments retain their own local update behavior.

This retains display elements, not authorization decisions for subsequent reads.
The existing WebSocket session binding checks current account/security state on
incoming and outgoing messages, and page services enforce current access before
returning business data. Revoked access cannot load a newly selected protected page.

## Popup presentation

All 40 native Streamlit dialogs use the shared presentation decorator in
`app/presentation/components/dialog.py`. The shell loads the visibility rules before
opening actions are available. A completion component follows the dialog body and
reveals it after its initial elements and lazy widget placeholders have mounted.
This prevents an empty frame followed by fields appearing in stages. Already-open
dialogs remain mounted during subsequent interactions. Native keyboard dismissal,
backdrop dismissal, forms, file uploads and server validation keep their behavior.
Stopped permission errors become visible when the script finishes.

Contacts and project logs already prepare their entire browser-native modal before
showing it. Neither mechanism eliminates the time needed for authorized server
reads or writes; this presentation change removes partial opening without adding a
fixed loading delay or weakening authorization.

## Project creation and editing

Portfolio creation and `Edit details` each have a small action fragment, so opening
their dialogs leaves the master grid and project summary in place. `Edit details`
is shown only when the current permission snapshot allows editing that project,
and opens directly in edit mode. In the current role model, business administrators
can create projects and edit all projects; project editors can edit their assigned
scope. The planning chart's read-only details entry keeps its existing behavior.

Portfolio project forms use a Component v2 browser modal. The opening callback
prepares the references and all fields before the browser displays the form.
Text, numeric and date inputs, property tabs, multiselects and custom links remain
local. Changing the project template requests its fields from the server while
retaining explicitly edited values. Reopening loads fresh references.

Saving checks the current template, ownership and permissions in the existing
write transaction. Success closes the modal and refreshes only the grid and
selected project; the shell remains mounted and grid scroll position is retained.
Validation errors retain the draft. An obsolete form token cannot write another
project, and duplicate submissions are blocked while the request is pending.

The planning chart retains its native read-only project details dialog. Its sections
share a current permission snapshot only within one synchronous render; subsequent
independent interactions obtain current permissions again.

Gantt step creation and full step edits commit in the component callback before
the chart renders. The response contains one patch for affected projects instead
of rendering old data and then requesting a full-page rerun. Write failures are
displayed within the chart fragment and keep the existing authoritative checks.

## Project contact and log modals

Contacts and project logs use a self-contained Component v2 modal with the browser's
native `dialog` element. This avoids the full-app rerun required to programmatically
close Streamlit's dialog. Choices and existing values are prepared before the modal
is shown; its fields appear together. The component modifies only its own DOM.

Save events execute the authoritative collaboration service in the owning section's
callback, then render that list once and acknowledge closure of the modal. The
project summary, other sections and sidebar are retained. Validation failures keep
the form open with entered values and a safe error. Cancel, Escape and backdrop
dismissal do not write data. Duplicate clicks are blocked while a save is pending;
events replayed after a completed modal are ignored.

The operation, project and edited row identity stay in server-side session state.
The component submits only allowlisted string fields; service validation, scoped
transactions and current write authorization remain authoritative.

## Gantt task and dependency loading

Expanding projects and enabling external dependencies use bounded task HTTP reads.
Each batch now obtains tasks, dependency endpoints, tags, assignments, project
labels and referenced whole-project date bounds in one authorized database
snapshot. Capacity details are requested only for pools assigned to those tasks;
their calculations still include all authorized consumers of each requested pool.

Dependency queries start with the requested projects' tasks. Scoped task ownership
and predecessor checks use indexed lookups rather than materializing every visible
task. This retains the same endpoint visibility rules, including redaction of a
hidden legacy predecessor. Business write guards are unchanged. Current access and
the business/security revision are still checked before delivery.

The browser loads visible projects before off-screen overscan, with at most 25
projects per request and 100 loaded projects retained. These reads update the
existing chart without a Streamlit rerun or an activity-timeout extension.

Project and task context-menu filters target the named planning workspace
fragment. The filter controls and chart update together; the application shell
and sidebar remain mounted. The callback queues the filter before rendering,
so the former chart-fragment-to-full-app refresh is unnecessary.

Dependency filters follow indexed task/project endpoints as connected projects
are discovered. The redacted legacy predecessor projection is materialized once,
and `UNION` terminates cycles. Every endpoint still passes the current scoped
views; a hidden project cannot connect two otherwise visible projects. Chart
rebuilds read current capacity details once, including when the display payload
is already cached.

Session controls retain one listener set and one polling timer across component
renders. Activity is throttled across the page and same-origin charts; activity
and session checks each permit only one request in flight. Repeated renders do
not reset this state or accumulate requests ahead of task loads. Unmounting
removes listeners and timers, and late responses from disposed controls are ignored.

## Portfolio scrolling

The master list reads 100 rows at a time and retains at most five pages in the
browser. Scrollbar jumps load the visible page before off-screen overscan.
Paging reruns only the grid fragment; controls, navigation and the selected
project summary remain mounted. The scrollbar element is retained across updates.

Master-list header filters are neutral until a filter is applied, then turn red;
opening or hovering over an unused filter does not activate its red highlight.
The portfolio removes the top padding and empty style rows. Selected-project
details follow the matching-project count directly, without a separate template
caption or divider. The template remains available in the grid and project editor.

Resource-overallocation badges load after the rows through the same-origin
`POST /api/portfolio/allocations` route. Allow this route alongside the existing
planning task route when configuring a reverse proxy. Each request contains at
most 25 project IDs and rechecks current access and the display revision. The
browser permits one badge request at a time, times out after 15 seconds, and
offers an explicit retry after a failure. These reads do not extend session activity.

Scoped capacity calculations are reused per pool within the same current
user/session, readable scope, capacity/security revision and day. Pool input reads
include only assignments to the requested pools and the task bounds of their
authorized consuming projects. They still include every authorized consumer needed
to calculate each pool's warnings correctly.

## Browser bundle loading

Streamlit's versioned public JavaScript and CSS under `/static/js/` and
`/static/css/` retain the framework's immutable cache policy. Initial HTML, account
and project responses, downloads, error responses and responses that set cookies
remain uncached. Application static files and custom component responses do not
receive this exception.

If a browser reports `Failed to fetch dynamically imported module` after a
connection interruption or development restart, first check that the named bundle
is available. A failed import can remain failed in the current browser document
even after the server recovers. Reload the page once (Ctrl+F5 for a hard reload) to
start a fresh document. The application does not force automatic page reloads for
this condition.

## Verification before production

Run the regular pytest suite and the Gantt JavaScript tests. The real-provider
browser test is opt-in and uses independent generated credentials, Compose resources,
and a database under `.local/oidc-e2e/`; it never reads the development database.
Its additional `!override` Compose file removes development source bind mounts,
so this workflow exercises the built image. Rebuild the image after source changes.

```text
python -m pip install -e ".[dev,browser-tests]"
```

Set `EPPM_RUN_OIDC_E2E=1`, then run
`python -m pytest tests/test_oidc_browser_e2e.py -q --tb=short` after building the image.
The default browser channel is installed Chrome; `EPPM_BROWSER_CHANNEL` can select
another installed Playwright-supported channel. No traces, HARs, passwords, or
tokens are written to test output. Disposable containers/volumes are removed after
the run; ignored fixture files remain for controlled local cleanup.
The test binds only localhost ports 18501 and 18080. Run it separately from another
copy using these ports. `EPPM_KEEP_E2E=1` retains its uniquely named disposable
resources for diagnosis; remove only that named Compose project afterwards.

Verify production MFA, actual token expiry, reauthentication, Secure/HttpOnly cookies,
proxy origin handling, multi-tab logout, disabling, revocation, scoped export fetching,
and audit-failure rollback in the deployment environment. Report actual coverage and
remaining gaps; the project target is 99% statement coverage. Authentication and
authorization must remain enabled during rollback or incident recovery.

References: [Keycloak 26.7.2 upgrade notes](https://www.keycloak.org/docs/26.7.2/upgrading/),
[realm import](https://www.keycloak.org/server/importExport),
[Compose merge/reset rules](https://docs.docker.com/reference/compose-file/merge/),
[Playwright browser channels](https://playwright.dev/python/docs/browsers).
