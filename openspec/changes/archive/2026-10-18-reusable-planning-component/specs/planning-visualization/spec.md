# Spec Delta

## Purpose

Provide an embeddable planning display that coordinates task schedules and optional resource usage while preserving calendar meaning, bounded rendering, user interaction state, and independent instance ownership.

## ADDED Requirements

### Requirement: Timeline and resource periods stay synchronized
The planning display SHALL use the same calendar periods, horizontal positions, viewport width, and scroll position for the Gantt and an enabled resource grid. The resource grid SHALL be optional without requiring placeholder resource data.

#### Scenario: Change scale and scroll either view
- **WHEN** a user selects Day, Week, Month, Quarter, or Year and scrolls either enabled view horizontally
- **THEN** corresponding dates and period boundaries align in both views, including after column or container resizing

#### Scenario: Render a schedule without resource usage
- **WHEN** a host supplies projects and tasks and disables the resource grid
- **THEN** the timeline and its interactions work without resource rows, resource-specific controls, or reserved empty grid space

### Requirement: Calendar dates retain inclusive schedule meaning
The display SHALL interpret schedule dates as calendar dates with inclusive end dates, retain distinct milestone rendering for equal start/end dates, and preserve calendar boundaries across leap days, year changes, and daylight-saving changes.

#### Scenario: Render a task through its end date
- **WHEN** a task starts on 2028-02-28 and ends on 2028-03-01
- **THEN** its bar covers all three calendar days and the next period begins after its inclusive end

#### Scenario: Compare time zones and milestones
- **WHEN** the same date-only schedule is rendered in UTC and Europe/Luxembourg across a daylight-saving transition
- **THEN** task dates, day-based drag results, and dependency endpoints agree and an equal-date task remains a milestone

### Requirement: Resource period summaries preserve daily semantics
The resource grid SHALL display peak daily demand and minimum effective daily capacity for each period. Overallocation SHALL use the maximum positive daily demand minus that day's effective capacity. Explicit zero capacity SHALL remain zero; missing overrides SHALL use normal capacity.

#### Scenario: Demand and capacity extrema occur on different days
- **WHEN** a two-day period has demand/capacity pairs of 6/10 and 4/2
- **THEN** it displays peak demand 6, minimum capacity 2, and maximum excess 2

#### Scenario: Distinguish missing and zero overrides
- **WHEN** normal capacity is 5 and a period contains a zero-capacity override and a date without an override
- **THEN** those days use capacities 0 and 5 respectively and interval decoding preserves that distinction

#### Scenario: Fully overridden periods and demand scopes
- **WHEN** every day in a period has an override and total, selected-project, and comparison demand are supplied
- **THEN** no artificial normal-capacity day is added and each demand scope is summarized independently using the same effective daily capacity

### Requirement: Updates preserve relevant interaction state
Data updates SHALL preserve scroll position, expansion, selection, and an unrelated open editor draft for the same view scope. A new view scope or an explicit reset SHALL clear the applicable retained state. Invalid updates SHALL leave the last valid display intact and expose a safe error to the host.

#### Scenario: Hydrate or edit one project
- **WHEN** a valid patch replaces one project's tasks or resource series within the current scope
- **THEN** unrelated rows and editor drafts remain usable and the viewport retains its position

#### Scenario: Reset or change the selected scope
- **WHEN** the host changes the view scope or explicitly resets retained filters
- **THEN** retained state is reset according to the documented scope/reset policy rather than being carried into a different selection

#### Scenario: Patch removes an edited entity
- **WHEN** an authoritative update removes the entity currently open in an editor
- **THEN** the display safely invalidates that editor and explains the conflict without emitting a stale write

### Requirement: Dependencies and comparison overlays retain identity
The display SHALL support project/task dependency endpoints and optional baseline or alternative overlays with stable task pairing, added/removed rows, and caller-supplied diagnostic information. Hidden or unloaded endpoints SHALL be handled without inventing or requesting unauthorized metadata.

#### Scenario: Compare renamed and missing tasks
- **WHEN** a host supplies current and comparison tasks paired by stable identity, including renamed, added, and removed tasks
- **THEN** the corresponding lanes and overlay-only rows retain that pairing and only host-enabled editing targets emit edit requests

#### Scenario: Inspect bundled or external dependencies
- **WHEN** several dependency records share a visible path or an endpoint is outside the delivered schedule
- **THEN** delivered dependency records remain individually inspectable and unavailable endpoint details remain absent

### Requirement: Rendering and lazy loading stay bounded
The display SHALL virtualize timeline rows and resource rows/cells, coalesce visible-data requests within configured batch and retained-project limits, and prioritize visible rows over overscan. Replaced, cancelled, or stale-scope responses SHALL never overwrite a newer display.

#### Scenario: Scroll through a large schedule
- **WHEN** many projects and resource rows exist and the user scrolls through the display
- **THEN** live row/cell counts follow the viewport and overscan rather than total schedule size and pending reads do not produce duplicate in-flight batches

#### Scenario: Finish a request after the scope changes
- **WHEN** an earlier lazy request completes after a scope or revision change
- **THEN** its result is discarded and the newer view remains intact

#### Scenario: Retry a failed read
- **WHEN** a visible-data request fails
- **THEN** existing valid rows remain visible, a safe retry action is available, and no automatic repeating retry loop occurs

### Requirement: Instances own and release their resources
Each mounted display SHALL own its state, DOM, styles, identifiers, listeners, timers, observers, and pending work. Multiple instances SHALL operate independently. Disposal SHALL be idempotent, release owned resources, and prevent late callbacks or events from affecting the host or another instance.

#### Scenario: Mount two independent displays
- **WHEN** two displays with overlapping task identifiers are mounted in one page
- **THEN** changing scale, selecting rows, editing, resizing, or scrolling one display does not change the other or surrounding page styles

#### Scenario: Dispose and mount again
- **WHEN** a host disposes a display twice while reads, drag handling, or delayed tooltips are pending and then mounts another display
- **THEN** disposal produces no duplicate callbacks or exceptions, previous pending work has no effect, and the new display has one set of active interaction handlers

### Requirement: Hosts control labels and supported actions
The display SHALL accept host-provided labels, theme options, and supported-action capabilities. User-supplied names and descriptions SHALL render as text. Existing keyboard-accessible controls, delayed tooltips, read-only behavior, and disabled-action behavior SHALL remain available in EPPM.

#### Scenario: Localize and restrict controls
- **WHEN** a host supplies translated labels and read-only capabilities
- **THEN** visible and accessible control names use those labels and stale listeners cannot emit editing requests after capabilities are revoked

#### Scenario: Display text containing markup
- **WHEN** task, resource, or project labels contain HTML-like text
- **THEN** the text is displayed without executing markup or changing the host document
