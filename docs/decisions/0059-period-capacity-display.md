# Minimum capacity in period displays

Dashboard capacity lines and tooltips show the minimum effective daily capacity
within each quarter, matching the planning resource grid. Dates without capacity
exceptions use normal effective capacity; a fully overridden period never adds
an artificial normal-capacity day. Explicit zero capacity remains zero.

Daily allocation and overallocation calculations are unchanged. Peak demand and
peak excess may occur on different dates: overallocation remains the maximum of
daily demand minus that day's effective capacity, bounded below by zero. It is
not peak demand minus the minimum displayed capacity. Capacity lines remain
hidden when multiple pools are displayed.

This aggregation is implemented in Python; no database migration is required.
