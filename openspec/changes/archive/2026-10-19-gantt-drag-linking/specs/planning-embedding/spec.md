# Spec Delta

## ADDED Requirements

### Requirement: Hosts explicitly enable dependency creation
The versioned embedding contract SHALL provide an explicit dependency-creation capability, defaulting to disabled when omitted. Enabled hosts SHALL receive a validated creation intention containing opaque predecessor/successor identities and kinds, type, zero lag, successor edit context, scope/revision, and a unique request ID. Creating a dependency SHALL not require an existing dependency ID.

#### Scenario: Existing host omits creation support
- **WHEN** a host supplies the existing contract without the creation capability
- **THEN** existing dependency rendering/editing remains usable and no creation connectors or creation requests are introduced

#### Scenario: Create with opaque identities
- **WHEN** an enabled host receives a completed connection between opaque task/project IDs
- **THEN** exactly one validated request preserves both endpoint identities, FS/SS/FF/SF type, zero lag, and the successor's current or alternative revision context

### Requirement: Creation reconciles with authoritative host results
Completing a connection SHALL submit immediately without a confirmation dialog. The display SHALL distinguish a pending link from accepted data, correlate acceptance or rejection by request ID, and prevent duplicate delivery from pointer/click events or Streamlit reruns. Rejection SHALL clear pending visuals and expose a safe error while preserving the last valid schedule and unrelated drafts.

#### Scenario: Accept a creation
- **WHEN** the host accepts a creation request and returns authoritative dependency data
- **THEN** the pending link is replaced by the accepted identity and becomes available through the normal dependency editor

#### Scenario: Reject or replay a creation
- **WHEN** the host rejects a stale or unauthorized request, or a component rerun repeats the same request ID
- **THEN** rejection leaves the previous schedule intact and a repeated delivery cannot create a second dependency

### Requirement: EPPM creates links within existing scheduling authority
EPPM SHALL authorize and validate dependency creation server-side using existing endpoint restrictions and revision/source checks. Creation SHALL append only the requested incoming link, preserving existing and inaccessible links. Live creation SHALL update the live schedule; comparison creation SHALL update only the editable successor alternative. Saved plans, baselines, and dates SHALL retain their established meanings.

#### Scenario: Preserve all endpoint combinations and existing links
- **WHEN** an authorized actor creates any supported task/project pairing and FS/SS/FF/SF type
- **THEN** EPPM adds one zero-lag incoming dependency to the successor without replacing unrelated links or changing schedule dates

#### Scenario: Enforce endpoint and permission restrictions
- **WHEN** a forged request targets a hidden endpoint, a self-link, a prohibited project/own-task pairing, an unauthorized successor, or a stale source
- **THEN** EPPM rejects it safely without mutation or disclosure of protected endpoint details

#### Scenario: Edit an alternative
- **WHEN** an eligible connection is completed during comparison
- **THEN** the successor's editable alternative draft receives the dependency through its revision-checked workflow and the live schedule and saved snapshots remain unchanged

#### Scenario: Preserve comparison source meaning
- **WHEN** an alternative successor is selected during linking
- **THEN** only sources from that same alternative within its project, or current/live sources in other projects, are eligible, matching the established dependency resolver after saving

#### Scenario: Follow existing predecessor authorization
- **WHEN** a predecessor is visible but read-only and the actor can edit the successor
- **THEN** project-successor linking follows its existing predecessor-visibility policy and live task-successor linking retains its existing predecessor edit restrictions
