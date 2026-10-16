# Spec Delta

## Purpose

Keep project tag choices and matching consistent across the shared filter panel while exposing only projects and labels the current user is authorized to read.

## ADDED Requirements

### Requirement: Shared project tags include dictionary and free-text values
The system SHALL include both dictionary-backed and nonempty free-text project tags in shared filter choices and matching, using the dictionary label when a tag references the dictionary.

#### Scenario: Mixed tag sources
- **WHEN** readable projects have dictionary-backed and free-text tag assignments
- **THEN** choices include both kinds and selecting either kind matches the appropriate readable projects

#### Scenario: Any and All selection
- **WHEN** two selected free-text tags are present together on one readable project and only one is present on another
- **THEN** Any matches both projects and All matches only the project with both selected tags

### Requirement: Shared filters preserve project authorization
The system SHALL limit tag choices and matching results to the current user's readable projects, including after clearing filters.

#### Scenario: Hidden project tags remain private
- **WHEN** an unreadable project has a tag absent from readable projects
- **THEN** the tag does not appear in choices or delivered project payloads and resetting filters does not expose the hidden project

### Requirement: Clearing shared filters resets the planning view
Clearing shared filters SHALL restore In Progress, remove project/resource restrictions and signal the Gantt view to reset retained filter state without changing authorization.

#### Scenario: Clear a restricted planning view
- **WHEN** the user clears shared filters after restricting project and resource selections
- **THEN** matching authorized projects are unrestricted within In Progress, resource restrictions are removed and the chart receives a new reset signal
