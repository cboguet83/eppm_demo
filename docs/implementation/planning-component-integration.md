# Planning component integration

EPPM's planning page embeds the same browser implementation used by the plain-web
and independent Streamlit examples. The former monolithic `gantt/index.html` is
now a document loading `eppm-bootstrap.js`; it contains no renderer or inline
handlers. There is one active renderer, one mode handler and one main splitter
binding per mounted instance.

## C3: browser and presentation ownership

```mermaid
flowchart TB
    Page["planning.py: chart fragment and existing event handlers"]
    Python["planning_component.py: keyed component and receipt acknowledgement"]
    Bridge["planning-view/adapters/streamlit.js: parent/origin, queue, sizing"]
    Bootstrap["eppm-bootstrap.js: instance composition and cleanup"]
    Mapping["eppm-contract.js: DTO, overlay, interval and event translation"]
    Transport["eppm-transport.js: partial reruns and HTTP provider"]
    Commands["eppm-commands.js: application menus and confirmations"]
    Choices["eppm-choices.js: correlated authorized predecessor choices"]
    ProjectForm["eppm-project-editor.js: revision-checked project dependency batch"]
    Core["planning-view/workspace: mount, controls, editors and lifetime"]
    State["planning-view/state: indexed store and bounded loader"]
    Timeline["planning-view/timeline: rows, columns and dependencies"]
    Resources["planning-view/resources: hierarchy, summaries and grid"]
    Calendar["planning-view/calendar: shared date-only geometry"]
    HTTP["POST /api/planning/tasks: existing authenticated reader"]
    Services["PlanningWorkspace: existing application services"]
    Page --> Python
    Python --> Bridge
    Bridge --> Bootstrap
    Bootstrap --> Core
    Bootstrap --> Commands
    Bootstrap --> Choices
    Bootstrap --> ProjectForm
    Bridge --> Transport
    Transport --> Mapping
    Transport --> HTTP
    Choices --> Transport
    ProjectForm --> Choices
    ProjectForm --> Transport
    Core --> State
    Core --> Timeline
    Core --> Resources
    Core --> Calendar
    Timeline --> Calendar
    Resources --> Calendar
    HTTP --> Services
    Page --> Services
```

These are implemented modules and call relationships. The existing PostgreSQL
service/store C3 map remains in [the scheduling guide](postgresql-planning.md).
The portable module imports neither EPPM nor Streamlit; only the optional
Streamlit adapter speaks its transport protocol.

## EPPM transport

The Python adapter preserves the `interactive_gantt` declaration, widget key,
callback timing and established application event fields. It acknowledges a
received string nonce on the next render. The browser transport converts full
application DTOs into checked snapshots and partial reruns into patches. Its
public scope uses the selection/locale `view_scope`; the independent server
`scope_token` still correlates authenticated HTTP reads. A rebuilt server token
within the same selection therefore preserves applicable viewport state.

The shared bridge queues component events until receipt acknowledgement, then
advances the single Streamlit component-value channel. EPPM's codec translates
generic dates/progress/task intentions into the existing Python handlers.
Task saves and immediate edits commit before the fragment produces its patch.
Safe failures return a correlated rejection, preserving the editor draft.
Alternative task/form requests retain the plan revision captured when the editor
opened. Authoritative data updates settle previews; the browser does not persist
or activate plans.

Lazy schedule reads use the same-origin endpoint, cookies, server scope/revision,
nonce and per-project source tokens. The injected controller coalesces visible
projects before overscan, requests at most 25 projects, and retains at most 100.
EPPM's transport keeps this bounded identity list and host comparison metadata,
without another expanding current-task cache. It releases raw task replacements
after mapping them. Stale/aborted responses
are ignored. A 403 or 409 requests one authorized refresh for that source
revision. Other failures retain data and expose the shared explicit retry control.

Predecessor choice reads are separate from schedule hydration. The generic
editor receives a cancellable reader; EPPM routes current choices through the
existing authorized `load_dependency_tasks` handler and alternative choices
through the supplied comparison context. Unavailable endpoints are never filled
from invented task metadata or an unrestricted schedule fetch.

## Application commands and editors

EPPM supplies declarative project/task/resource menus. Record capabilities and
edit mode are rechecked on invocation; the server reauthorizes every operation.
Navigation, CSV, tags, pool assignments, project logs/details, baseline capture
and alternative creation/activation retain their Python handlers and dialogs.
Cancelled confirmations emit no request and leave the command menu usable.
Resource commands retain pool/group identity, inclusive dates and allocation
scope. Alternative demand rows remain comparison data and do not emit current
allocation selections.
Their details/allocation commands remain visibly disabled; allocation filters
remain available through nested pointer and keyboard menus. Task assignment
uses the person icon. Menus are clamped to the viewport and child panels can
open on either side.

The shared task editor owns task fields and incoming dependency controls. It
supports editing and creating tasks, preserves drafts across unrelated reruns,
and checks capabilities again on Save. Alternative frozen task rows address the
alternative; current and baseline bars remain read-only during comparison.
Dependency inspection opens the successor task editor or EPPM's project panel.
Project-scoped predecessor reads coalesce by scope, revision and project while
each caller retains independent cancellation. Failed reads preserve the selected
predecessor and draft, show a safe retry message, and prevent incomplete saves.
Creation patches expand their project without moving the retained viewport.

The project dependency panel is application-owned because its server contract is
an atomic revision-checked batch with explicit upserts/deletions. It contains no
step fields. Failed saves retain rows and the original revision; Reload explicitly
discards the draft and reads current dependencies. Closing/disposal cancels choice
callbacks and ignores late correlated responses.

The shared calendar keeps timeline/resource scale and horizontal scroll aligned.
EPPM selects a 234–495 px overall timeline panel (including its 56 px header),
retaining the previous size limits. Rows remain 41.4 px and resource rows 23.8 px.
Main and individual frozen columns resize within the instance. Baseline and
alternative lanes, new-scenario colors, milestones, diagnostic counts, progress,
description/link visibility and expansion controls share this one renderer.
EPPM selects concise capacity tooltips; demand remains available in accessible
cell descriptions. Only deviating capacity badges change color. Availability
and excess retain green/red status text with FTE units.

## Source and verification boundaries

See [package assembly](planning-component-packaging.md) for deterministic browser,
wheel, source-distribution and Docker resources. EPPM's small host modules/styles
are also included in root wheels and source distributions; generated shared
resources remain ignored and are checked against their source manifest.

`tests/test_eppm_planning_adapter.cjs` checks DTO/event/HTTP translation without
private renderer globals. `tests/test_eppm_planning_browser.py` mounts the actual
bootstrap through Streamlit messages. Native PostgreSQL scenario and project
dependency tests exercise the same bootstrap with real services. AppTests retain
single-rerun edits, filters and revoked-access checks. Independent module/browser
and installed-consumer tests cover the reusable boundary. Final acceptance,
coverage and repeated benchmark evidence belong to the OpenSpec verification
record; targeted checks alone do not establish that gate.
