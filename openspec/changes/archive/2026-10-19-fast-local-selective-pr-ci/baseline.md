# Measured baseline and planning evidence

Recorded 2026-10-19. Fetched `origin/main` and local `main` both resolve to
`d4a769f12d92fc01d6fc49a1c4d16ca0be41ecee`; divergence was `0 0` before creating
`codex/fast-local-selective-pr-ci`. PR #5 is already merged.

## Measurements

| Observation | Result |
| --- | --- |
| Instrumented full pytest run | 3,489 tests plus five subtests; 1,083.79 seconds (18m04s) |
| Full application statement coverage | 16,705 / 17,097 = 97.7072% |
| Full run summed worker time | setup 612.12s; call 1,393.56s; teardown 149.62s |
| Fast candidate | 783 tests across 70 modules |
| Fast candidate with no service environment | 783 passed in 7.48s |
| Three fast runs, no coverage | 7.284s / 7.434s / 7.434s; median 7.434s |
| Three fast runs, with coverage | median 9.938s; only 40.8785% application coverage |
| Last measured hosted full pytest | 1,334.70s (22m15s); total job 24m31s |
| JavaScript suites in that hosted run | 221 root cases and 117 package cases; approximately one second combined |

Full profiling used revision `9ee483625a316e481ccc506b435205690f302bd9`.
Application, Python tests, package sources, Dockerfile, and CI sources matched
current main; PostgreSQL Compose did not. Docker had four CPUs and roughly
8GB memory. These are measured observations, not a promised runtime or a new
seven-minute acceptance limit. No test has been established as useless.

The diagnostic HTML/JSON/CSV and candidate list remain local under
`docs/diagnostics/integration-test-diagnostic-2026-10-19*`. This planning commit
does not include the large generated reports. This summary is self-contained;
the candidate must be re-audited against the apply revision rather than treated
as a maintained executable manifest. Hosted evidence is available in
[the successful PR #5 run](https://github.com/cboguet83/eppm_demo/actions/runs/39175088237).

## Current implementation and defects

- `.github/workflows/tests.yml` has one full `tests` job on every PR update and
  manual dispatch; no `push` trigger, readiness event, or obsolete-run
  cancellation is configured.
- `tests/conftest.py` already requires exactly two `loadgroup` workers when
  parallel, or serial diagnostics. Preserve its audited heavy grouping and
  worker completion/security protections.
- `--require-full-suite` checks prerequisites, required groups, skips, and
  completion of collected tests. It does not independently prove that an
  arbitrarily selected collection equals the whole repository. The new full
  entry point must prevent selection and retain collection reconciliation.
- Python 3.14 is required. No `unit`/`integration`/`e2e` marker taxonomy currently
  exists; filenames alone do not establish either resource needs or test value.
- `docker-compose.postgresql.yml` now embeds pgAdmin with required
  `PGADMIN_EMAIL` and `PGADMIN_PASSWORD` interpolation, even when the tools
  profile is inactive. PostgreSQL-only config validation fails without these
  variables. `pgadmin_data` is referenced but not declared in the Compose files.
  The credential generator supplies neither variable. Fix these blockers before
  claiming current-main startup or CI acceptance.
- Config-only checks reproduced both failures: PostgreSQL/test composition with
  pgAdmin variables unset fails interpolation, and `--profile tools` with dummy
  values fails for the undefined `pgadmin_data` volume. With tools inactive and
  dummy pgAdmin values supplied, resolved test ports include both 5434 and 15432.
  The test overlay currently appends its port instead of replacing the
  development binding, which can collide with a running development database.
- Read-only GitHub checks found no legacy main protection (HTTP 404) and no
  effective branch rules (`GET /repos/cboguet83/eppm_demo/rules/branches/main`
  returned `[]`). Remote settings are not being changed by this plan.
  Repository settings currently enable merge, squash, and rebase methods;
  automatic merging is already disabled. The repository is public.

## Confirmed user decisions

- Draft PRs receive selective feedback; ready code PRs automatically receive
  full acceptance, including every later ready-PR revision.
- Code merges retain the full suite and at least 95% application statement
  coverage. Partial runs do not replace that evidence.
- Include main protection, the up-to-date requirement, and merge commits only.
- Maintain per-task commits, verify before archive/PR delivery, and wait for
  explicit approval of the concrete PR before merging.

Narrow prose-only exemptions are a documented interpretation of “before code
merges”; unknown or executable content cannot enter that exemption. No current
application database, account, password, or running deployment is changed.
