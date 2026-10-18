# ADR 0065: Reusable planning visualization with host-owned workflows

The planning chart and resource grid share a native JavaScript module with a
validated version-1 contract and a `mountPlanningView(root, options)` lifecycle.
It owns calendar geometry, virtual rows, dependencies, resource summaries,
generic editors and interaction state. Streamlit messaging is a separate adapter;
EPPM owns its DTO mapping, authenticated task reads, source tokens, project
dependency batch workflow, confirmations and application commands. Server
authorization and application services remain authoritative.

The same browser sources are assembled into an independent browser archive,
an independent Python/Streamlit distribution, and EPPM's component assets. This
adds an explicit contract/build boundary, but avoids maintaining divergent
renderers or coupling ordinary web consumers to Streamlit. Native modules retain
the existing runtime without introducing a frontend framework. The packages
remain in this repository; registry publication is a separate operation.

See [the integration guide](../implementation/planning-component-integration.md)
for current ownership, transport and validation boundaries.
