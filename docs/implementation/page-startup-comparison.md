# All-page versus selected-page startup

Date: 2026-09-10. Baseline commit: `05d2064`, including the accepted compact
authorization-cache improvement.

## Decision from the experiment

Retain the existing eager page composition for now. Lazy composition reduced the
initial Portfolio wait modestly, but introduced substantially longer first visits
to Settings and Application Access. The trial was reversed after measurement;
the compact-cache improvement remains committed and active.

The reverted trial patch and temporary composition benchmark were removed after
the evaluation. The measurements and decision are retained in this report.

## What was changed in the trial

`create_application_workspace` registered lightweight authorized callbacks instead
of importing all page modules and constructing every allowed page's dependencies.
Each callback imported its page and built its workspace when selected. Settings
and schema deep links shared the same callback. Sidebar totals remained a separate
authorized query. No authenticated workspace was cached globally, and current
server-side business authorization remained in place.

Shared dependencies required by Portfolio, including capacity badge services,
were retained. This trial did not defer every application service import, alter
frontend bundles, change authentication, or add background preloading.

## Browser measurements

Two fresh-container, fresh-browser runs per variant, using the same development
data and administrator role. The compact-cache change was active in both variants.
No project, task, allocation, or settings records were edited. Each temporary
browser session logged out after measurement.

`.local/compare_page_startup.py` measures initial Portfolio from the authenticated
application document request until rows are visible and the initial script has
finished. It excludes typing/login-provider time but includes browser startup
assets. This is a broader measurement than selecting project details in an
already-open Portfolio page. Navigation measurements start at the radio click,
wait for new UI deltas followed by script completion, and check for UI exceptions.
Gantt readiness additionally waits for the chart iframe and project summaries.

Medians in seconds, with two samples per cell:

| Operation | All pages at startup | Selected page only |
|---|---:|---:|
| Initial Portfolio ready | 7.369 | 6.815 |
| First Planning script complete/browser idle | 4.364 | 3.810 |
| First Gantt chart ready | 4.636 | 4.383 |
| First Settings visit | 0.666 | 2.432 |
| First Application Access visit | 0.574 | 2.137 |
| Return to Portfolio | 0.526 | 0.570 |
| Repeat Planning script complete/browser idle | 0.749 | 0.575 |
| Repeat Gantt chart ready | 1.677 | 1.381 |
| Repeat Settings visit | 0.898 | 0.617 |
| Repeat Application Access visit | 0.609 | 0.477 |
| Repeat Portfolio visit | 0.532 | 0.516 |

The approximate 0.55-second initial saving is about 7.5%. The first Settings visit
costs an additional 1.77 seconds and the first Access visit an additional 1.56
seconds. With only two runs, small differences should not be treated as proven
improvements. The first-visit Settings/Access penalty repeated in both runs.

Raw samples, milliseconds, all-page / selected-page:

- Initial Portfolio: `[7102,7636]` / `[7070,6559]`.
- First Planning: `[3671,5057]` / `[3853,3767]`.
- First Gantt ready: `[4156,5116]` / `[4527,4239]`.
- First Settings: `[536,795]` / `[2361,2502]`.
- First Access: `[504,644]` / `[2060,2214]`.
- First return to Portfolio: `[458,593]` / `[661,478]`.
- Repeat Planning: `[685,813]` / `[586,564]`.
- Repeat Gantt ready: `[1496,1857]` / `[1376,1385]`.
- Repeat Settings: `[757,1039]` / `[592,642]`.
- Repeat Access: `[523,694]` / `[473,480]`.
- Repeat Portfolio: `[463,601]` / `[510,521]`.

Initial rendering emitted 35 UI deltas, including 19 sidebar deltas, in both
variants. All subsequent page navigations emitted zero sidebar deltas. First
Planning and Settings visits emitted 16 deltas, Access 15, and Portfolio returns
13. Counts and rendered content remained consistent between variants.

## Isolated composition measurements

The temporary composition benchmark compared explicit baseline and candidate
startup source files in fresh Python subprocesses using an isolated
synthetic SQLite database. It measured route registration/dependency construction,
not rendering. The original source was taken from `05d2064:app/main.py`; the
candidate was the tested lazy implementation.

In the development container, three runs gave:

| Metric | All pages | Selected page only |
|---|---:|---:|
| Composition samples, ms | 1282.46, 1407.18, 1257.22 | 125.01, 127.05, 98.91 |
| Median composition, ms | 1282.46 | 125.01 |
| Registered routes (operator fixture) | 5 | 5 |
| Imported page modules at registration | 11 | 0 |

This confirms that work was deferred successfully. The browser results show why
that reduction cannot be claimed as an equivalent full-screen loading improvement.
The command was also smoke-tested with identical baseline and candidate files
after restoring eager startup.

## Validation and restoration

The lazy trial passed 36 tests across `test_lazy_page_startup.py`,
`test_layered_shell.py` and `test_fragment_reruns.py`. They cover selected-page-only
construction, a fresh process importing no unselected pages, role-limited routes,
separate sidebar totals, deep links, language/navigation behavior and retained
callbacks after access revocation or account disabling. Browser runs reported no
Streamlit exceptions and retained the existing sidebar isolation.

The trial's main-file diff and new tests were reversed together using the saved
patch. The existing startup source was verified against the accepted baseline and
the development app restarted. Temporary baseline code was removed. No additional
production startup change or second commit is included in this evaluation.
