# Tasks

Each numbered checkbox is one dedicated commit containing its changes, relevant tests/docs, and completion marker. Commit subjects identify `project-workflow-setup` and the task ID. Archive and PR operations are follow-up steps rather than tracked prerequisites for archive.

## 1. Planning and bootstrap

- [x] 1.1 Capture the agreed setup proposal and design on `codex/project-workflow-setup`, explicitly skip product specs for this tooling-only change, and verify all required planning artifacts with `openspec status --change project-workflow-setup` and `openspec validate project-workflow-setup --strict`.
- [ ] 1.2 Review and version the user-generated `.agents/skills/openspec-*/` files and initial `openspec/config.yaml` without rewriting generated skill bodies; verify the file inventory contains only intended bootstrap inputs, no credentials/local state, and OpenSpec resolves this repository's root.

## 2. Delivery policy

- [ ] 2.1 Add the agreed standing authorization and workflow pointer to AGENTS.md, create `docs/development-workflow.md`, and configure OpenSpec artifact rules and operation guidance for branch-before-planning, GrillMe discovery, per-task commits, explicit verification, archive-before-PR, human merge approval and merge commits; verify supported configuration with OpenSpec instructions/status/validation, check documentation links, and confirm this change follows the documented sequence. Keep the full-check command aligned with the strict option introduced by task 3.1.

## 3. Full verification and automatic PR checks

- [ ] 3.1 Add opt-in `--require-full-suite` pytest hooks and isolated pytester regression tests for prerequisite validation, required-group collection, collection/setup/runtime skips, accepted full runs, failure propagation, and unchanged ordinary local runs; document its use in the contributor guide and verify the focused regressions pass without connecting to external services.
- [ ] 3.2 Add an unfiltered `pull_request` trigger alongside manual dispatch in `.github/workflows/tests.yml`, enable strict mode in its existing full pytest command, and correct README's manual-only CI description; verify the diff retains Python 3.14, isolated PostgreSQL with separate roles, browser opt-in, Docker image build, 95% coverage, Node checks and read-only permissions, and validate workflow syntax using available tooling.

## 4. Integrated acceptance

- [ ] 4.1 Run OpenSpec strict validation and the verify-change skill, full pytest with strict mode and at least 95% coverage using isolated PostgreSQL/OIDC, and `node --test tests/test_*.cjs`; review the final diff and task-to-commit history and record actual commands/results in `verification.md`. Keep this task incomplete if any required gate cannot execute or fails; distinguish partial results from full acceptance.

## Workflow follow-up

- After every tracked task is complete and verification succeeds, archive this change on the same branch; product spec sync is inapplicable because `skip_specs: true`. Inspect the archived artifacts and commit the archive/evidence in a dedicated lifecycle commit.
- Publish the branch and create a PR targeting `main` only after archive. Include task-to-commit evidence and verification outcomes, attach the PR to this chat, and require the full CI run on its final revision to pass.
- Inspect GitHub protection and merge settings if accessible; report their verified state or limitations. Changing remote administrative settings is outside this plan.
- Wait for the user's explicit approval of the concrete PR, then merge using a merge commit that preserves each task commit. Do not squash or rebase merge.
