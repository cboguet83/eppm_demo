# Proposal

## Why

The Planning page's 7,511-line browser asset combines Gantt rendering, resource usage, shared mutable state, Streamlit transport, HTTP hydration, and EPPM workflows. Extracting a cohesive planning visualization will make those responsibilities easier to maintain and allow the same display to be embedded in other Streamlit applications and ordinary web applications.

## What Changes

- Extract a framework-independent JavaScript planning module with focused calendar, state/loading, timeline/dependency, resource-grid, interaction, and layout internals behind a small mount/update/destroy interface.
- Keep the Gantt and optional resource grid coordinated through one calendar model and viewport coordinator; preserve existing scheduling, comparison, resource, localization, keyboard, and filtering behavior in EPPM.
- Define a validated, versioned data/event contract with opaque identifiers, inclusive calendar dates, snapshot/patch updates, display capabilities, optional comparison overlays, and host-provided lazy loading.
- Isolate DOM, styles, state, caches, listeners, timers, and requests per instance so multiple displays can coexist and be disposed safely.
- Move Streamlit messaging and frame sizing into a reusable adapter. Keep EPPM authorization, persistence, scenario lifecycle, navigation, CSV operations, and application dialogs in the EPPM integration.
- Deliver independently installable browser and Python package artifacts from this repository, with a plain-web example, a separate Streamlit example, reproducible asset assembly, and package installation checks outside the checkout.
- Replace Gantt source-slicing tests with behavior tests at module and host interfaces, retain the existing regression assertions, and add lifecycle, two-instance, contract, packaging, and performance comparisons.
- Remove duplicate mode handling and repeated splitter initialization as part of the extraction, with focused regressions.

### Scope and planning assumptions

The user confirmed reuse in both Streamlit and non-Streamlit web applications. The proposed default is a behavior-preserving extraction using native JavaScript modules and the current Streamlit component mechanism, developed and versioned in this repository first. No frontend framework or general plugin platform is needed.

Public registry publication, a new repository, database/schema or business-rule changes, and migration of the separate Project plans comparison Gantt are outside this change. That comparison display is a potential later consumer. Package names and directory names below are local implementation defaults, not claims of registry availability. There are no unresolved business decisions preventing this plan.

## Capabilities

### New Capabilities

- `planning-visualization`: An independently mounted planning display with synchronized Gantt/resource views, comparison overlays, calendar/capacity semantics, instance isolation, and bounded rendering/loading.
- `planning-embedding`: A versioned host interface, browser and Streamlit adapters, independently consumable packages, and EPPM integration preserving current workflows and authorization.

### Modified Capabilities

None. `bounded-planning-cache`, `bounded-planning-dependencies`, and `shared-project-filtering` remain unchanged constraints and receive regression coverage; their requirements do not need delta specs.

## Impact

Primary implementation targets are `app/presentation/assets/components/gantt/index.html`, `app/presentation/pages/planning.py`, presentation-owned planning data/events/transport helpers, and new standalone package directories. Existing Python application/domain services and PostgreSQL readers remain the authoritative business and security layers.

Packaging touches the root `pyproject.toml`, dependency/install instructions, `Dockerfile`, and `.github/workflows/tests.yml` as necessary to consume the local wrapper artifact and include all JavaScript/CSS/HTML assets. Current component packaging only includes component HTML files and must be extended or replaced for the extracted asset tree.

Affected validation includes the Gantt scrolling, permissions, lazy-hydration, menu, tooltip, resource-header, planning-event, native PostgreSQL/browser, and benchmark tests. Architectural documentation will record the implemented ownership and package interface. Existing SQL/API authorization semantics, Python 3.14 runtime support, and current navigation identities are preserved.

Planning is performed on `codex/reusable-planning-component`, based on refreshed `main` at `0b6ebb0`, in an isolated worktree so the in-progress performance-testing checkout is untouched. Implementation starts only after a separate apply request.
