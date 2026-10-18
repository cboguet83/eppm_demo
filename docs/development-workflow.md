# OpenSpec development workflow

This is the delivery procedure for EPPM changes. AGENTS.md requires agents to
read it when planning, applying, verifying, archiving, or delivering a PR.

## 1. Discover and plan on a feature branch

Inspect Git state and preserve unrelated user work. Use GrillMe to challenge
requirements and resolve decisions that affect scope or business behavior.
Inspect the repository for facts rather than asking the user to repeat them.
Record agreed outcomes in the OpenSpec change, without treating answers to
discovery questions as permission to implement.

Before writing a new plan, start `codex/<change-name>` from current `main`.
Check local/remote divergence and fetch current main when available; if main
cannot be verified current, report it rather than overwriting existing work.
Keep one change on its dedicated branch through archive and PR delivery.

Use the repository-local OpenSpec skills and the CLI's resolved artifact paths.
Create proposals through the proposal workflow and implement only after the
user requests apply. Configure project rules in `openspec/config.yaml`; preserve
generated `.agents/skills/openspec-*/SKILL.md` bodies when customizing policy.
Tooling-only changes may declare `skip_specs: true`; product changes need their
actual capability deltas. Do not invent application requirements for tooling.

## 2. Commit each task

Each numbered checkbox represents one coherent task and one dedicated commit.
Include that task's implementation, relevant tests/docs, and completion marker
in its commit. Verify completion before checking the box. Use a subject such as:

```text
test(project-workflow-setup): complete task 3.1 strict suite verification
```

Planning has its own task/commit. Add a new task and commit for subsequent
corrections; retain completed task history. Use focused staging and inspect the
staged diff before every commit. Record task-to-commit evidence using
`git log main..HEAD --oneline`; do not embed a commit's own hash in its contents.

The standing user authorization covers task commits, publishing the feature
branch, and creating its PR after verification and archive. It does not authorize
merging the PR. Archive and PR steps are plain follow-up bullets in tasks.md,
outside the tracked checklist, so archive does not depend on its own completion.

## 3. Verify before archive

Run relevant tests with each task. For final acceptance, run OpenSpec strict
validation, the verify-change skill, the complete pytest suite with strict mode
and at least 95% application coverage, and all JavaScript component checks.
Use real isolated PostgreSQL and authenticated browser deployments for the full
suite. A partial local run is useful evidence but is not full acceptance.

From an activated Python 3.14 virtual environment with `.[dev,browser-tests]`
installed, Docker available, and Playwright Chromium installed:

```bash
# Prepare canonical browser resources before root package installation/builds.
python -m scripts.build_planning_assets
# First use only: generation refuses to overwrite existing credentials.
python -m scripts.configure_postgresql --output .local/workflow-tests.env
docker compose --project-name eppm-workflow-tests \
  --env-file .local/workflow-tests.env \
  -f docker-compose.postgresql.yml -f docker-compose.postgresql-test.yml \
  up -d --wait postgres
python -m scripts.postgresql_admin --env-file .local/workflow-tests.env \
  --url-variable POSTGRES_TEST_ADMIN_URL provision
docker build -t eppm-demo:local .

POSTGRES_TEST_CLIENT_CONTAINER=eppm-workflow-tests-postgres-1 \
EPPM_RUN_OIDC_E2E=1 \
python -m dotenv -f .local/workflow-tests.env run -- \
  python -m pytest -q -x -p no:cacheprovider --require-full-suite \
    --cov=app --cov-fail-under=95 -n 2 --dist=loadgroup \
    --postgres-test-db-mode=template --max-worker-restart=0
node --test tests/test_*.cjs
node --test packages/planning-view/tests/*.test.js
python -m scripts.build_planning_assets --check
openspec validate <change-name> --strict
```

The verified full-run command uses migrated templates and exactly two workers.
For a serial/fresh diagnostic, replace the worker/template options with
`-n 0 --postgres-test-db-mode=fresh`. Empty-database migration/upgrade tests stay
unmigrated in either mode. Run affected paths locally while editing; full
acceptance still requires the complete command and JavaScript checks.

Reuse the generated environment file on later runs; omit its generation command.
Credentials remain in ignored `.local/` files. Do not display or commit them.
Use the matching container name for a different Compose project. The browser
fixtures create their own disposable application/provider/database deployment.
Never point the test runner at an application database.
The fixture's application data uses a disposable Compose project volume so the
non-root image can write backups regardless of the host runner's user ID.

The native Gantt benchmark defaults to Playwright's installed Chromium. Set
`EPPM_BENCHMARK_BROWSER` to an absolute executable path to select another locally
installed browser. CI selects `/usr/bin/google-chrome`, whose sandbox is supported
by the Ubuntu runner's security profile; no sandbox protections are disabled.

`--require-full-suite` is an opt-in completion gate. It requires both PostgreSQL
test URLs, `EPPM_RUN_OIDC_E2E=1`, collection of PostgreSQL and authenticated browser
tests, and no skips in those required groups. It preserves failing pytest exit
codes. Ordinary local runs without the option retain existing partial-run/skip
behavior. Unrelated conditional skips must still be recorded in evidence.
CI uses pytest `-x` to stop at the first failure. Successful runs still execute
the complete suite and all subsequent gates; an interrupted failing run is never
full acceptance.
Collection-only invocation is rejected in strict mode because it does not
execute tests. Strict failures identify missing variable names or skipped test
identifiers without displaying connection strings or skip reasons.

Coverage includes application code executed by the native browser servers. The
pytest-cov 7 tooling minimum and coverage subprocess patch collect those child
processes; graceful server termination retains their measurements. Keep the 95%
threshold and existing source/exclusion scope. Containerized OIDC execution is
a separate required behavior gate and is not claimed as host-process coverage.

Run the verify-change skill against the proposal, design, task evidence, and any
applicable spec scenarios. Record commands, results, coverage, skips, and the
task-to-commit mapping in the change's `verification.md`. If a required check
fails or cannot execute, keep the acceptance task incomplete, explain the actual
blocker, and resolve it before archive or PR creation. Full GitHub CI after PR
creation is an additional gate on the final revision, not a substitute for the
pre-archive checks.

## 4. Archive, then create the PR

Once every tracked task and required check passes, use the archive skill on
the same feature branch. Sync applicable delta specs according to that skill;
for a change declaring `skip_specs: true`, there are no product deltas to sync.
Inspect the archive, retain its metadata and verification evidence, and create
a separate lifecycle commit for the archive.

Publish the branch and create a PR targeting `main`, describing the outcome,
validation, task commits, and archived change. Attach the PR to the Codex chat.
The full GitHub Actions workflow runs automatically on every PR; manual dispatch
remains available. Revalidate relevant checks after further edits and require
successful full PR CI on the final revision, including archive changes.

## 5. Obtain approval and merge

Present the concrete PR and wait for the user's explicit approval to merge it.
A request to apply, archive, or create a PR is not merge approval. After approval
and passing final checks, use a **merge commit** into `main`, preserving every
task commit. Do not squash or rebase merge.

Recommended GitHub repository settings are PR-required changes to `main`, the
full `tests` job as a required status check, merge commits enabled, squash/rebase
merge methods disabled, and no linear-history rule that prevents merge commits.
Inspect and report settings when accessible; local instructions do not enforce
remote protection. Changing remote administrative settings requires a separate
explicit request. Report missing or unverified protection without claiming it
has been configured.
