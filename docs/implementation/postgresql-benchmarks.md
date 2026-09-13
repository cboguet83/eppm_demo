# PostgreSQL planning diagnostics

The planning profiler, task-pool dialog profiler and JSON-lines planning session
use a consistent `pg_dump` snapshot restored into a new, randomly named
`eppm_benchmark_<uuid>` database on the same PostgreSQL cluster. They inspect and
dump the source; all identity setup, grants and benchmark edits occur in the copy.
Normal completion and handled failures close the restricted runtime pool and drop
only the database created by that invocation. Temporary archive files are removed
with the diagnostic's temporary directory.

Run these operator tools from the repository with Python 3.14. The explicitly
selected, ignored environment file must supply `DATABASE_OPERATOR_URL` and
`DATABASE_URL` for the same current application database, using separate operator
and restricted runtime users. The operator needs database creation rights. Native
`pg_dump` and `pg_restore` clients must be installed; alternatively, explicitly
select the same database server's local Docker container with `--client-container`.
The ordinary app container does not receive operator credentials.

```powershell
.venv/Scripts/python.exe -m scripts.benchmark_planning --env-file .local/postgresql.env --client-container eppm_demo-postgres-1 --projects 100 --no-profile
.venv/Scripts/python.exe -m scripts.benchmark_task_pool_dialog --env-file .local/postgresql.env --client-container eppm_demo-postgres-1
node scripts/benchmark_gantt.cjs --database --expanded --env-file=.local/postgresql.env --client-container=eppm_demo-postgres-1
```

The Gantt driver uses the repository's virtual-environment Python, or the explicit
`EPPM_BENCHMARK_PYTHON` executable. Its optional positional argument selects the
Chromium/Edge executable. `--all-projects` selects all projects; the Python planning
commands accept `--projects 0` for the same purpose. An explicit `--task-id` selects
the dialog's task; otherwise it prefers a task with resource assignments.

The profilers run the real Streamlit screens with `AppTest`. The standalone Gantt
driver loads the actual component from a local file and exchanges JSON-lines
events with the planning session. It uses the component's supported callback task
loading path because it has no ASGI origin. Timings exclude snapshot creation and
identity setup; profiler output and requested chart payloads are emitted to stdout.

These are component diagnostics. Their synthetic identity exists only in the
disposable copy and uses the application's normal signed actor/permission checks.
They do not test OIDC login, the production HTTP task endpoint or the migration's
50-user responsiveness criterion. Those require the separate authenticated full
application browser acceptance run.

The original SQLite baseline collector is preserved in
`docs/archive/sqlite/scripts/benchmark_migration_sqlite.py`. Run historical SQLite
measurements from the preserved SQLite revision/image described in
[migration evidence](postgresql-migration-evidence.md#sqlite-service-baseline),
not through the PostgreSQL runtime. Existing baseline data and archives are retained.
