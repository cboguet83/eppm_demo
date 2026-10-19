# Spec Delta

## ADDED Requirements

### Requirement: Dependency connectors are discoverable and distinct
When dependency creation is enabled, the display SHALL reveal separate start and finish connectors on eligible task and project bars on hover or keyboard focus. Connectors SHALL have accessible endpoint labels and hit areas distinct from date resizing, moving, progress editing, and project expansion.

#### Scenario: Reveal task and project connectors
- **WHEN** an authorized user enables editing and hovers or focuses a dated task or project bar
- **THEN** eligible start and finish connectors become available without changing dates, selection, or expansion

#### Scenario: Milestones and project bounds
- **WHEN** a milestone or project summary is eligible for linking
- **THEN** its two connectors remain separately selectable, with milestone endpoints on its single date and project endpoints on its earliest start and latest finish

#### Scenario: Preserve other gestures
- **WHEN** a user manipulates an existing resize handle, bar body, progress handle, or expansion control
- **THEN** that control retains its existing behavior and does not start dependency creation

### Requirement: Connection gestures define directed endpoints
The display SHALL support drag-to-connect and click–move–click, showing a preview arrow and highlighting eligible destination connectors. The first endpoint SHALL be the predecessor and the destination SHALL be the successor. Finish/start, start/start, finish/finish, and start/finish SHALL produce FS, SS, FF, and SF respectively, independent of chronological or screen order.

#### Scenario: Create each endpoint combination
- **WHEN** the user completes either pointer gesture for each of the four endpoint combinations on eligible tasks or projects
- **THEN** one creation intention has the corresponding directed endpoints, derived type, and zero-day lag without opening a confirmation form

#### Scenario: Link across entity kinds
- **WHEN** a user connects task-to-task, task-to-project, project-to-task, or project-to-project endpoints allowed by the host
- **THEN** the intention preserves both entity kinds and identities, including links between different visible projects

#### Scenario: Complete with the keyboard
- **WHEN** a user activates a focused source connector with Enter or Space, moves focus to an eligible destination connector, and activates it
- **THEN** the same directed, zero-lag creation intention is submitted and completion is announced accessibly

### Requirement: Connection state cancels safely
The display SHALL cancel an unsubmitted connection on Escape, an empty-space drop or click, pointer cancellation, source removal, edit revocation, scope/revision invalidation, or disposal. Ineligible destinations SHALL never submit a creation intention. Connection state SHALL remain instance-owned and bounded by the rendered viewport.

#### Scenario: Cancel before submission
- **WHEN** the user presses Escape, drops or clicks on empty space, or the active pointer is cancelled
- **THEN** preview and destination highlighting disappear without any write request or date edit

#### Scenario: Stale or inaccessible targets
- **WHEN** an endpoint becomes unavailable or the applicable scope, revision, or edit capability changes during connection
- **THEN** the pending gesture is cancelled without submitting stale identities or revealing unavailable metadata

#### Scenario: Virtualized rows and independent displays
- **WHEN** a connection is active while the user scrolls, expands rows, or uses another mounted display
- **THEN** targets resolve from currently rendered delivered endpoints, removed sources cancel safely, and the other display retains independent state

### Requirement: Newly created links remain editable through existing controls
After authoritative acceptance, the display SHALL render the created dependency with its persisted identity and expose the established dependency inspection/editing route. Users SHALL be able to adjust type and signed calendar-day lag there. Creation SHALL leave schedule dates unchanged and retain warning-only conflict evaluation.

#### Scenario: Adjust a new link
- **WHEN** the user opens an accepted link through dependency inspection and edits its type or lag in the successor's existing dependency editor
- **THEN** the change follows the established authorized save flow and the arrow and warning state reflect the authoritative result

#### Scenario: Link dates already conflict
- **WHEN** an accepted zero-lag link conflicts with endpoint dates
- **THEN** the dependency shows the existing scheduling warning without moving either endpoint or other tasks
