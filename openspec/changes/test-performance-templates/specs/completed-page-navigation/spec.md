# Completed page navigation

## Purpose

Keep the main workspace blank during page navigation and reliably reveal the completed destination, including fast navigation whose transient running state is not visible in the browser.

## ADDED Requirements

### Requirement: Navigation blanks unfinished destinations
The application SHALL hide the main workspace and show its loading indicator immediately after a page navigation request, retaining that state while the destination is unfinished.

#### Scenario: Slow destination
- **WHEN** the user navigates from a rendered page to a destination that is still rendering
- **THEN** the old workspace and partial destination remain hidden behind the loading indicator

### Requirement: Completed destinations become visible
The application SHALL reveal a completed destination and clear its loading indicator once rendering is complete and the application is idle, even if the browser never exposes an intermediate running state. Completion of an earlier navigation SHALL NOT reveal a later unfinished navigation.

#### Scenario: Coalesced running state
- **WHEN** a destination finishes successfully without exposing an intermediate running state
- **THEN** its completed content becomes visible and its loading indicator is cleared

#### Scenario: New navigation supersedes a pending reveal
- **WHEN** another navigation starts before an earlier completion is revealed
- **THEN** the main workspace remains hidden until the new navigation completes

#### Scenario: Existing fragment navigation responses
- **WHEN** a chart navigation completes through a full rerun or returns an inaccessible-destination response through its fragment
- **THEN** the completed response becomes visible and the loading indicator is cleared
