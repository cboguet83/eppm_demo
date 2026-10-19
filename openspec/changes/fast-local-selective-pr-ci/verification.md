# Verification evidence

## Planning only — 2026-10-19

Status: task 1.1 complete; all six implementation/acceptance tasks remain open.
The proposal, baseline, design, and tasks are ready for review. No runner, test,
workflow, Compose, application, database, or GitHub setting was modified.

| Check | Observed result |
| --- | --- |
| `openspec list --json` and `openspec context --json` | Resolved this repository's existing OpenSpec root; no active change to duplicate |
| `git fetch origin main` and `git rev-list --left-right --count main...origin/main` | Fetched main `d4a769f12d92fc01d6fc49a1c4d16ca0be41ecee`; divergence `0 0` |
| Dedicated branch | Created `codex/fast-local-selective-pr-ci` from that main before authoring artifacts |
| GrillMe decisions | User chose automatic full CI on readiness/later ready revisions and inclusion of main protection setup |
| `openspec validate fast-local-selective-pr-ci --strict` | Passed; zero product deltas intentionally accepted via `skip_specs: true` |
| `openspec status --change fast-local-selective-pr-ci --json` | Planning complete: proposal/design/tasks done, specs skipped |
| Artifact/task audit | All internal artifact links resolve; seven unique task IDs; no product delta directory; implementation tasks unstarted |
| `git diff --cached --check` and staged diff review | Clean planning-only changes scoped to this change directory |

Read-only configuration probes confirmed the startup defects without starting
or changing services: missing pgAdmin variables fail PostgreSQL-only Compose
interpolation, the active tools profile with dummy values fails for an undefined
volume, and the resolved test overlay retains the development port alongside
15432. No secret-bearing rendered configuration was printed.

Read-only GitHub inspection returned no legacy main protection (404), no
effective branch rules (`[]`), and merge/squash/rebase all enabled. Automatic
merging is disabled and the repository is public. These are observations,
not newly applied settings. The exact future settings update/read-back belongs
to task 4.2 after apply authorization and local gate verification.

The large generated diagnostic reports remain untracked under
`docs/diagnostics/`; they are preserved and excluded from the planning commit.
The self-contained baseline records the relevant measured findings and their
revision limitations. Prior diagnostic test results are not acceptance for
the proposed implementation. Full integration/coverage/hosted checks will run
under the remaining tasks; no new hosted workflow was triggered for planning.

## Task-to-commit evidence

Task 1.1 has its dedicated planning commit with subject
`docs(fast-local-selective-pr-ci): complete task 1.1 planning`.
Resolve its hash with `git log main..HEAD --oneline`; do not embed the commit's
own hash inside its contents. Later apply work must record every subsequent
task's commit and actual validation evidence here.

## Implementation acceptance

Pending a subsequent user request to apply. This change has not been archived,
published as a PR, or approved for merging. The planned final acceptance retains
full tests and at least 95% unchanged application coverage, effective remote
protection, one commit per task, and explicit approval of the concrete PR before
a merge commit into main.
