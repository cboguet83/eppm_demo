# Finance budget plans

Open **Finance** in the sidebar. Every active account can view/export the shared
plan. To edit, import, save or cancel, an access administrator assigns the
application-wide **Finance editor** role; Business administrators already qualify.

1. Click **Edit** to enable the initially read-only grid, CSV import, and **Save new version**.
   Saving or selecting a version returns to read-only mode. Enter WBS
   codes and amounts directly in the blank spreadsheet grid, paste plain
   Excel values, or import CSV. Matching descriptions appear automatically; French
   labels use OTP. Unused rows are gray until a WBS is entered. Rows grow as needed.
2. Enter nonnegative euro amounts with at most two decimals. Past-year cells remain
   gray and read-only. Tab/Shift+Tab moves between editable columns; Enter/Shift+Enter
   moves vertically. Completely empty rows are ignored; amounts require a WBS.
3. Click **Save new version**. Enter a name (the selected version's name is prefilled)
   and choose Draft, Proposed, Approved, or Canceled. The new number is allocated
   automatically as 1, 2, 3…; no major/minor choice remains.
4. Select any older version to inspect or edit a copy. Saving always creates a new
   version, including a status-only change. Existing budget values are preserved.
5. In edit mode, **Delete this plan** cancels the selected saved version after
   confirmation without creating another number. Its amounts remain visible/exportable and cancellation
   is audited. Cancellation cannot be undone, but the version can be copied and
   saved as a new version with a different status.
6. **Exit edit mode** is visible only while editing. It restores the selected saved
   version and returns to read-only mode. Unsaved changes require confirmation;
   canceling that prompt keeps edit mode and the draft. **Delete this plan** is
   also hidden outside edit mode.

Saving releases the previous grid's navigation listeners before mounting the saved
version. You can navigate immediately afterward. Leaving genuinely unsaved changes
still asks whether to discard them; canceling keeps the entered values.

CSV exports include all saved WBS rows and exactly the current year through current
year +14, excluding past years. Use the exported headers and UTF-8 encoding when
editing a file. CSV imports replace the entire current/future grid after validation
and a warning; omitted codes retain any past amounts. Invalid uploads never save a
partial result. Descriptions in the file cannot update Settings.

To paste from Excel, select the destination cell and paste plain values. Full rows
can use the export layout (code, description, 15 future-year values), or the visible
layout with unchanged historical values. Shift-click selects a rectangle for copy.
Formulas and workbook formatting are not supported. Maximum CSV size is 2 MiB;
maximum plan size is 10,000 rows, including rows retained for historical values.

Before first use on an existing installation, back up the database and apply the
normal operator migration command inside the running app container:

```powershell
docker exec eppm_demo-app-1 python -m scripts.access_admin --database /app/data/ppm_mock.db migrate
docker restart eppm_demo-app-1
```

The new migration preserves existing snapshots and numbers them in creation order.
It does not reseed business data or change existing role assignments. Finance remains independent of project budgets, project allocation
percentages, and database seeding workflows. See ADR 0021 for the detailed rules.
