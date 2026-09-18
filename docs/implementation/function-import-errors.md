# Function CSV import errors

The import popup distinguishes CSV parsing from validation/database-save errors.
User-correctable errors identify the CSV row, function name, supplied identity
when available, and the offending field or reporting relationship. Hierarchy
errors identify missing/deleted managers and cycles; delete-missing conflicts
include a reminder to retain parents of active functions.

Imports remain atomic: a failed import saves no catalog changes. The popup stays
open so the user can replace the file and retry. Database constraint failures
are translated to safe field-specific messages. Unexpected database failures
display an error reference matching an application log entry containing the
error class and SQLSTATE, without exposing SQL or database payloads.

PostgreSQL regression tests cover invalid references, percentages, cycles,
delete-missing conflicts, database constraint failures and transaction rollback.
Browser coverage checks parsing/save-stage diagnostics and successful retry.

Function, team and pool import controls start a fresh upload component session
each time the dialog opens. Reopening after dismissal or successful import clears
the filename, file contents and preview; dialog interactions retain the current
upload until that dialog is closed. The Employees page currently offers CSV
export only and has no CSV import dialog.
