# Streamlit planning view

Independent adapter for the same native browser modules used by ordinary web
hosts. Python 3.14 and Streamlit 1.63 or later in the 1.x series are required.
Package version 0.1.0 and data contract version 1 are distinct. This repository
prepares local wheel/source artifacts; no public registry release is implied.

The package imports Streamlit and Python's standard library. It has no EPPM,
database, pandas or application-service dependency. The browser uses native ES
modules and adjacent styles, with no compilation at application startup.

## Full-data host

```python
import streamlit as st
from streamlit_planning_view import planning_view

if "snapshot" not in st.session_state:
    st.session_state.snapshot = {
        "version": 1, "kind": "snapshot", "scope": "my-view", "revision": "r1",
        "projects": [{"id": "alpha", "name": "Alpha"}],
        "tasks": [{"id": "build", "projectId": "alpha", "name": "Build",
                   "start": "2026-01-01", "end": "2026-01-05"}],
        "capabilities": {"edit": True},
    }
    st.session_state.updates = []

event = planning_view(
    st.session_state.snapshot, key="schedule",
    updates=st.session_state.updates,
    options={"grouped": False, "mode": "Day"},
)
if event and event["type"] == "dates":
    # Real hosts authorize, validate the revision and persist here. This example
    # accepts fixture dates into session data only.
    task = st.session_state.snapshot["tasks"][0]
    task.update(start=event["start"], end=event["end"])
    st.session_state.updates = [{
        "version": 1, "kind": "response", "scope": event["scope"],
        "revision": event["revision"], "requestId": event["requestId"],
        "accepted": True,
    }]
    st.rerun()
```

Enable editing through the display checkbox, or set `editEnabled: True` in
options. UI hints never authorize a server operation. Reject a write using the
same correlated response with `accepted: False` and safe text `error`.
Task/dependency events carry `values`; date/progress fields are at the top level.
Generic application commands belong in the host. The browser contract documents
resources, hierarchy, comparisons, scopes and capabilities.

Use explicit stable, distinct keys for multiple displays. `planning_view`
returns each event once per key, using a bounded 256-event acknowledgement
history. Component callbacks prepare acknowledgements before script rendering.
The browser waits for acknowledgement before using Streamlit's single value
channel again; unsent actions precede queued reads. Receipt is distinct from
accepting a business change.

Same-scope data retains applicable zoom, scroll, expansion and drafts. Change
scope or send `reset: True` to reset them. Labels/capabilities belong in data.
Keep `options` stable per key; changing mount configuration remounts the display.
Unsupported versions raise a safe `PlanningContractError`. Supplied names and
errors render as plain text.

## Event-driven lazy host

Supply project headers with task counts/date summaries, `tasks: []` and
`loadedProjectIds: []`, then call `planning_view(..., lazy=True)`. Configure
finite limits through `options={"loading":{"batchSize":25,"maxProjects":100}}`;
those are the defaults. Fully supplied hosts need no loader.

```python
if event and event["type"] == "load":
    requested = event["projectIds"]
    # Implement this application function with current authorization/revisions.
    tasks = authorized_tasks_for(requested, event["revision"])
    st.session_state.updates = [{
        "version": 1, "kind": "patch", "scope": event["scope"],
        "revision": event["revision"], "requestId": event["requestId"],
        "replaceProjectIds": requested, "tasks": tasks,
    }]
    st.rerun()
```

Answer exactly the requested IDs. The browser owns retention/eviction,
cancellation and stale-generation checks. Reject reads with a correlated
rejected response. Valid rows remain and Retry loading starts an explicit retry;
there is no repeating retry loop. Old-scope/revision intentions are acknowledged
and withheld from the current host view. A view revision change reconciles an
unfinished write unless an explicit response is supplied in that render.

The bridge pins the actual Streamlit parent window/origin after its first valid
render. Unrelated senders cannot change the display. Disposal cancels owned
work and late delivery. Frame heights include resource controls and content;
Python needs no separate sizing call.

Unit tests cover the Python parser/wrapper independently. The native Streamlit
harness copies only this package and the browser sources into a temporary host
and checks three keys, lazy reads, accepted/rejected edits, deduplication,
retained zoom and sizing, with no `app.*` imports.
