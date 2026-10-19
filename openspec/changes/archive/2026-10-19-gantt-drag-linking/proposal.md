# Proposal

## Why

Planners currently use forms to create dependencies even when both endpoints are visible on the Gantt chart. Linking directly from the start or finish of a task or project makes that relationship quicker to express and easier to understand.

## What Changes

- Reveal small start/finish connectors on task and project bars on hover or keyboard focus, with hit areas separate from date resizing.
- Support drag-to-connect and click–move–click, a live preview arrow, eligible destination highlighting, and keyboard completion. Escape or an empty-space drop cancels.
- Treat the first endpoint as predecessor and the destination as successor. The chosen edges determine FS, SS, FF, or SF.
- Submit a completed link immediately with zero calendar-day lag, without a confirmation form. Let users adjust type and lag afterward through the existing dependency editor.
- Preserve authoritative host acceptance, scoped permissions, revision checks, and current-versus-alternative editing. Dependencies continue to warn without moving dates.
- Keep link creation inside the existing reusable planning display and EPPM adapter; extend the host contract for creation of a dependency that has no existing dependency ID.

## Capabilities

### New Capabilities

None; this extends the existing planning capabilities.

### Modified Capabilities

- `planning-visualization`: endpoint connectors, connection gestures, preview/cancellation, accessibility, and later dependency editing.
- `planning-embedding`: opt-in dependency creation intentions and authoritative EPPM handling for task/project successors and alternatives.

## Impact

- Browser package: timeline bar rendering, scoped styles, interaction state, action validation, dependency inspection, and instance cleanup under `packages/planning-view/src/`.
- Host bridge: Streamlit event correlation and EPPM contract/transport/bootstrap modules under `app/presentation/assets/components/gantt/`, plus Python event validation, planning dispatch, and narrowly scoped application service changes where needed.
- Existing task/project dependency persistence, authorization, warning evaluation, and alternative draft operations are reused. No new storage technology, scheduling engine, or schema migration is expected.
- Tests: package contracts/actions and browser gestures; EPPM adapter tests; pytest boundary/service tests and real PostgreSQL/browser integration regressions. Packaged generated assets and embedding documentation must stay synchronized.

Agreed boundaries: tasks and projects, both endpoint sides, immediate zero-lag submission, and later editor adjustment. Automatic rescheduling, new cycle policy, direct arrow rewiring, bulk linking, and new undo/history behavior are outside this change. There are no unresolved material product decisions. Minor defaults (duplicate-gesture handling, visible targets, and opt-in host compatibility) are documented in the design.
