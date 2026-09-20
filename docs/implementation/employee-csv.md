# Employee CSV import

The Employees page exports CSV and provides a template, preview and import dialog.
Imports require the existing shared-data management permission. Each import is
one serializable transaction; invalid records roll back the complete operation.

- Existing `employee_id` values update profiles, including deleted records.
- Missing or unknown IDs create employees using database-generated IDs.
- `deleted_flag` defaults to false. Optional deletion of employees missing from
  the file is unchecked each time the dialog opens and uses soft deletion.
- Required columns are `firstname`, `lastname`, and `email`. Other profile fields
  follow the export template, including occupation percentage and deletion state.
- `function_id` assigns one function at 100%. `function_assignments` accepts the
  exported JSON array of `function_id` and `allocation_pct` objects and takes
  precedence when populated. `[]` clears assignments. Leaving both assignment
  fields blank or absent retains an existing employee's assignments.
- Allocation across active functions cannot exceed 100%. New function references
  must identify active functions. Existing deleted-function links are retained.
- Calendar exceptions and pool mappings are outside the import and are retained.
  The existing organization gateway refreshes staffing projections after commit
  validation, in the same transaction.

Downloads reauthorize each request and use UTF-8 CSV attachments with no-store
headers. Reopening the dialog clears the previous upload. Errors identify the
source row where possible, and success counts describe committed changes.
