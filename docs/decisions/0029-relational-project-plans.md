# ADR 0029: Relational plans and active schedule selection

Status: Accepted. Supersedes the JSON storage, projection rebuild and combined
current/baseline behavior in [ADR 0028](0028-project-plans.md).

## Decision

Each project has at most one active plan and at most one designated baseline.
Alternative scenarios are inactive until explicitly activated. Only Approved
plans can be activated or designated as baseline. Lifecycle authorization,
copying, activation, deletion and allocation cleanup run in Python services.
PostgreSQL provides foreign keys, uniqueness, transactions and row security;
no new database business functions are introduced.

The current portfolio is the default planning view. Its edit checkbox starts
unchecked and Python rejects Gantt mutations until it is enabled. Editing or
dragging a task normally updates the active plan; it does not create another plan.
All operational task, demand, capacity, filter and export reads select active
plans. Explicit scenario comparison and baseline display select their requested
plan IDs. A project without an active plan contributes no operational schedule
or demand.

The project context menu groups baseline creation, baseline soft deletion and
alternative display under Scenario management. Baseline mutations require edit
mode and existing approval privileges. Alternative selection excludes active,
deleted and frozen baseline plans. Comparison and baseline display are mutually
exclusive. Comparison uses half-height active bars above purple alternative
bars, with purple labels for alternative-only rows. Baseline lanes also retain
their purple color. In edit mode only alternative
bars can be dragged or resized; a revision-checked Python service updates that
scenario's existing task rows and audits the date change. Active plans and the
pool allocation grid remain unchanged.

Comparison starts disabled on a new browser session and whenever navigation
opens the page again. Scenario management can explicitly hide comparison or
activate the displayed approved alternative after confirmation. Close alternative
view beside Clear all filters also closes comparison while retaining portfolio
filters and edit mode. Activation retains the previous plan as inactive.
Purple dependency links use the alternative
schedule, including its added tasks. Contextual task, dependency, assignment,
CSV and task-tag operations target the selected alternative and check its revision
under the project lock. Deleted tasks release their scenario assignments.
Project tags and project logs remain shared; logging is available independently
of the Gantt edit checkbox, subject to project authorization.

In edit mode, Create alternative scenario prompts for a nonempty name, copies
the active plan including its resource assignments, and immediately opens the
new scenario in comparison. This newly opened view uses light-blue bars,
blue dependency links and labels, and light-blue left-pane backgrounds.
This color choice belongs to the view, not the plan status: selecting an existing
scenario uses purple, even if it is still Draft. Closing comparison or leaving
the page clears the new-scenario styling. Every newly created scenario starts as Draft,
including copies saved from the Project plans tab. Proposal and approval remain
explicit later lifecycle changes. Baseline snapshots and initial active plans
retain their separate creation rules.

Plan management is a lazy Project plans tab immediately after Project log in the
portfolio master-detail view. It uses the selected project without another project
selector. Unsaved drafts are kept separately for each project in session state.

## Storage

`project_plan` stores metadata only; migration 0045 removes `content` JSON.
`project_task`, `resource_pool_assignment` and `project_dependency` belong to
`project_plan` through `project_plan_id`. Task dependencies and tags inherit
ownership from their task. Composite foreign keys prevent assignments from
targeting tasks in another plan or project.

Physical row IDs distinguish versions. Task identity across versions is
`coalesce(stable_task_id, id)`; assignment identity uses the same pattern with
`stable_assignment_id`. Existing rows can therefore retain their physical IDs.
Comparison matches stable task IDs, including renames and removed tasks.
Progress is versioned in `project_task.progress_pct`. Copies inherit their source
plan's progress, then evolve independently. Activation never overwrites it.
Migration 0047 removes the redundant `plan_task_actual` mirror without changing
any existing task row or frozen baseline. This supersedes the earlier shared
actual-progress decision.
Project master data, finance, pool definitions and availability remain shared.

Activating an ordinary alternative changes the active designation atomically
under a project lock. It does not delete or recreate task or assignment rows.
Outgoing plans retain their latest edits. Cross-project dependencies resolve
stable predecessor identities against the predecessor project's active plan.
Missing active predecessors remain unresolved, with historical links retained.

Deleting a scenario is soft deletion: status becomes Deleted and both active and
baseline designations are cleared. It does not automatically activate another
plan. Deleted plans are excluded from default planning. Existing Business Admin
restoration rules continue to apply.

## Baselines and revisions

Setting the current schedule as baseline creates a separate frozen copy. An
identical existing baseline is reused. Replacing the designation retains the old
frozen plan. The Gantt still asks for confirmation before replacement. Activating
a frozen baseline creates an editable working copy, leaving history intact.

A new revision copies source tasks, dependencies, tags and resource allocations
by default. Allocation values, pool choices, fixed dates and relative-date rules
are preserved independently in the new plan. New tasks start without allocations.
Removing a source task removes its allocations, tags and local dependency edges
from the revision. Explicit allocation edits remain possible. Source and baseline
allocations remain unchanged. Inactive revisions contribute no operational demand;
their capacity impact can be inspected through explicit comparison.

## Migration and security

The checksummed Python migration expands every retained JSON snapshot into rows.
It also creates a working plan from each project's existing live rows, preserving
unsnapshotted edits. Existing baseline designations and audit history survive;
former baselines identified by audit history also remain frozen. The entire
migration and its ledger entry commit together or roll back together.

Operational readers use `current_*` views; resolved dependencies use `effective_*`
views. Runtime writes remain subject to project permissions and plan editability.
The redacted current-task view is read-only. Frozen and Deleted plan children
cannot be rewritten by the runtime role. Copying an inaccessible predecessor
requires an exact source-link match; public plan DTOs continue to hide it.

The additional rows increase storage and require disciplined active-plan scoping.
Indexes support plan ownership and stable identities. General database backup or
explicit operator reset intentionally includes all history.

## C3 — Components

```mermaid
flowchart LR
    UI[Current Gantt and scenario comparison] --> Service[ProjectPlanService]
    Service --> Rules[Python lifecycle and revision validation]
    Service --> Store[PostgresPlanStore]
    Store --> Rows[Relational plan reader and writer]
    Rows --> Tables[(Plans, tasks, assignments, links and tags)]
    Planning[Operational planning and capacity readers] --> Views[Active-plan views]
    Views --> Tables
    UI --> Baseline[Explicit baseline task reader]
    Baseline --> Tables
```

## Validation

Real PostgreSQL tests cover migration from populated storage, activation without
row replacement, single-active constraints, cross-plan assignment rejection,
frozen history, deletion, protected dependencies, independent progress and allocation
inheritance/cleanup. Browser tests cover the current portfolio and explicit
scenario comparison, baseline replacement confirmation and former-task lanes.

Migration 0046 corrects a portfolio-scale read regression: signed permission
scopes are evaluated once per statement and primary predecessor resolution uses
a join instead of a per-task lookup through the edit-access graph. The task view
retains its security barrier, hidden-endpoint redaction and SELECT-only runtime
grant. Performance regressions cover 1,000 projects with inactive history and
primary links, and repeated revision reads across 10,001 projects.
