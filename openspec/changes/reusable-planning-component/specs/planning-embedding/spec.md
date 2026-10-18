# Spec Delta

## Purpose

Let Streamlit and ordinary web applications embed the same planning display through a documented, validated host contract and standalone packages, while preserving EPPM's application workflows and authoritative server checks.

## ADDED Requirements

### Requirement: Hosts use a validated versioned contract
The embedding interface SHALL document a versioned contract for initial data, snapshot/patch updates, capabilities, labels, load requests, and emitted events. Unsupported versions, invalid dates or identifiers, duplicate identities, and cyclic hierarchies SHALL be rejected safely before changing valid instance state. Identifiers SHALL support opaque strings.

#### Scenario: Supply nonnumeric identifiers
- **WHEN** a host supplies project and task identities such as project-alpha and task-build-1
- **THEN** rendering, dependency resolution, patch replacement, and emitted events preserve those identities without integer coercion

#### Scenario: Reject an incompatible or malformed update
- **WHEN** an update has an unsupported contract version, invalid calendar range, duplicate identity, or cyclic resource hierarchy
- **THEN** the host receives a documented safe failure and the last valid instance state remains unchanged

### Requirement: Host dependencies are supplied explicitly
The browser package SHALL run with fully supplied data or a host-provided asynchronous loader without importing EPPM, requiring Streamlit messages, or assuming EPPM URLs, credentials, or database access. Load requests SHALL carry enough scope and revision identity for cancellation and stale-result rejection.

#### Scenario: Embed in an ordinary web page
- **WHEN** an application mounts the packaged browser display with fixture data and its own event handler
- **THEN** the display works without Streamlit, EPPM services, or network calls to an EPPM endpoint

#### Scenario: Use another application's loader
- **WHEN** a host supplies a loader with its own authentication and response mapping
- **THEN** visible-project reads use that loader, support cancellation, and return results through the documented contract without changing the display implementation

### Requirement: User actions are requests to the host
Editing and application actions SHALL emit uniquely identified user intentions through the host contract. The display SHALL not persist business records or approve scenarios. Acknowledged updates or safe rejections SHALL reconcile transient interaction state, and one user action SHALL produce one host request.

#### Scenario: Accept or reject a dragged task
- **WHEN** a permitted user drags a task and the host accepts or rejects its requested dates
- **THEN** one request identifies the task and requested dates, and the display settles on host-authoritative dates with a safe error on rejection

#### Scenario: Invoke an application extension action
- **WHEN** a user invokes a host-provided context action for a task, project, dependency, or resource period
- **THEN** the event contains the documented target context and the host owns its dialog, navigation, import/export, or scenario operation

### Requirement: Streamlit preserves component semantics
The standalone Streamlit wrapper SHALL provide the display through normal component data and events, support distinct instance keys, report frame height, and preserve usable display state across same-scope reruns. It SHALL function without EPPM application imports or services.

#### Scenario: Run a separate Streamlit application
- **WHEN** a clean application installs the wrapper artifact, supplies fixture data, and handles its events
- **THEN** the chart, optional resource grid, sizing, and task event delivery work without an EPPM checkout

#### Scenario: Rerun two keyed displays
- **WHEN** two independently keyed displays exist and an action causes a Streamlit rerun
- **THEN** each retains its applicable state, event delivery is deduplicated per instance, and frame sizing does not clip either enabled resource grid

### Requirement: EPPM integration preserves existing behavior
The EPPM adapter SHALL preserve current planning filters, navigation, task/dependency editors, resource drill-through, CSV actions, baseline operations, scenario comparison, and opt-in editing. Current and baseline data, alternative-only editing during comparison, and safe server failures SHALL retain their established meanings.

#### Scenario: Edit current tasks and compare alternatives
- **WHEN** an authorized editor enables editing, changes a current task, then opens an editable alternative
- **THEN** current editing retains its existing persistence behavior, comparison edits target only the alternative, and saved baseline content remains unchanged

#### Scenario: Use project and resource actions
- **WHEN** a user opens existing task/project/dependency menus, filters consuming projects, selects resource allocations, imports/exports, or opens project details
- **THEN** the corresponding current EPPM workflow receives equivalent target and period context and remains accessible

#### Scenario: Clear the shared filters
- **WHEN** a user clears shared planning filters
- **THEN** current authorized In Progress selection is restored, resource restrictions are removed, and retained chart filters receive the established reset signal

### Requirement: Server authorization and bounded reads remain authoritative
EPPM SHALL continue to authorize reads and writes on the server, redact inaccessible dependency endpoints, and retain revision/source-token validation. UI capabilities SHALL remain presentation hints. EPPM hydration SHALL retain a maximum batch of 25 projects and a maximum retained working set of 100 projects.

#### Scenario: Revoke permission or forge a client event
- **WHEN** permissions change or a caller bypasses disabled controls with a forged event
- **THEN** server checks prevent unauthorized reads or writes and the client refreshes or reports a safe error without disclosing protected metadata

#### Scenario: Hydrate a large EPPM selection
- **WHEN** scrolling a selection requires more than 100 projects over time
- **THEN** individual batches request at most 25 authorized projects, no more than 100 projects remain hydrated, and unrelated schedules are not fetched

### Requirement: Installed artifacts contain a usable independent display
The browser archive and Python wheel/source distribution SHALL include all required JavaScript, CSS, HTML, and version metadata and use the same browser implementation. Consumers SHALL be able to use those artifacts outside the repository without source-tree paths, editable installs, EPPM dependencies, or a frontend build at application startup.

#### Scenario: Install outside the checkout
- **WHEN** the browser archive and Python distributions are installed into isolated directories or environments with required runtime dependencies
- **THEN** the plain-web and Streamlit examples render and deliver an event using only installed package assets

#### Scenario: Build without asset drift
- **WHEN** both distributions are assembled from the same source revision
- **THEN** their included browser modules and styles match the declared source/version manifest and missing or stale assets fail package validation

### Requirement: Consumers have documented upgrade and integration guidance
The packages SHALL document installation, a minimal host example, lazy loading, update/reset behavior, disposal, safe event handling, supported runtime versions, and contract compatibility. Package and contract versions SHALL be distinguishable and incompatibilities SHALL fail explicitly.

#### Scenario: Upgrade a compatible host
- **WHEN** a host upgrades to a compatible package release while retaining a supported contract version
- **THEN** the documented embedding path continues to work and any unsupported version is rejected with a clear compatibility error
