# Employee identity, profile saves and pool warning presentation

Status: accepted by the requested employee and resource-pool interface changes.

## Employee identity and editing

Employee identity uses `employee_id`; the redundant `employee_code` field and
its preview/uniqueness interfaces are removed. Migration 0057 removes the column
and recreates the dependent active-record views with their existing invoker
security and grants. Employee IDs, function assignments, calendars and pool
mappings are retained. Existing migrations remain unchanged.

The employee profile's Save Changes action persists profile fields, function
assignments and the entire calendar grid in one authorized transaction. Draft
exception additions, changes and deletions do not write until that action.
Validation failures roll back all three sections. Cancel or closing the dialog
discards edits.

Percentage controls use five-percentage-point increments and zero decimal
places. Display formatting does not round stored capacity calculations. The
employee directory initially sorts by its displayed full name (uppercase last
name followed by first name), then employee ID ascending for ties. Employee
codes no longer appear in profile dialogs, directory filters or CSV exports.

## Pool warnings

The overallocated teams/employees summary tooltip lists affected resources,
their allocation totals and contributing pools. Employee entries also identify
their active function assignments. Deleted pools and resources remain excluded
by the existing allocation calculation.

Only leaf pools with an employee allocated above 100% across active pools have
red names in the hierarchy. Team-only, current-capacity and future-demand
warnings retain their warning icons and affected capacity-cell colors, without
turning the pool name red. Container names do not inherit red text.

## Validation

Regression coverage includes migration preservation, atomic profile/calendar
saves and rollback, five-point controls, integer percentage rendering, employee
code removal from exports, default full-name/ID sorting, and browser checks of
the pool tooltip and name colors.
