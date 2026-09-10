# Finance budget plans

Open **Finance** in the sidebar. Every active account can view/export the shared
plan. To edit, import, propose or approve, an access administrator assigns the
application-wide **Finance editor** role; Business administrators already qualify.

1. Add WBS rows, paste plain Excel values, or import a CSV. Codes may be absent
   from Settings; matched descriptions appear automatically. French labels use OTP.
2. Enter nonnegative euro amounts, with at most two decimal places. Past-year cells
   are gray and read-only. Use the right-pane scrollbar to see the full year range.
3. Save changes. The first save requires a name and creates 1.0 Draft. Later saves
   offer a revision or a named new major version. Nothing is overwritten.
4. Propose or approve a saved snapshot using the confirmed status actions. These
   create new minor revisions. Edit an approved snapshot to create another Draft.
5. Use the version selector to inspect history. Older minors are read-only and
   offer **Copy to new major version**.

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

Migration is additive and does not reseed business data or change existing role
assignments. Finance remains independent of project budgets, project allocation
percentages, and database seeding workflows. See ADR 0021 for the detailed rules.
