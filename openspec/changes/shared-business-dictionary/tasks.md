# Tasks

Each numbered checkbox is one coherent task and one dedicated commit containing
its implementation, applicable tests/docs and completion marker. Use subjects
such as `feat(shared-business-dictionary): complete task 2.1 typed catalog service`.
Keep tasks unchecked until their stated checks pass. Intermediate task commits
are not deployable releases; the new schema and all consumers ship together.

## 1. Planning

- [x] 1.1 Capture the confirmed roles/event-types scope in proposal, design, capability scenarios and this task list on `codex/shared-business-dictionary` from fetched main. Verify all four artifacts exist, `openspec validate shared-business-dictionary --strict` passes and the diff contains planning files only; then commit this planning task.

Planning evidence (2026-10-18): all four artifacts exist; strict OpenSpec
validation and the staged whitespace check passed. The staged diff contains only
this change's metadata and planning artifacts. Application, migration and browser
tests were not run because no implementation changed. The planning commit is
identified by task 1.1 in `git log origin/main..HEAD --oneline`.

## 2. Typed dictionary operations

- [x] 2.1 Add domain dictionary records/validators, typed application ports and an injected application service for the two registered dictionary codes. Define canonical-name/English-label and optional-translation edit commands, missing-entry errors and safe failure contracts. Add useful API docstrings and pytest unit/service tests for valid inputs, unknown codes, malformed locale/ID/name/translation input, omitted versus blank locales, preserved identity and authorization requests. Verify these tests and inward-dependency/core-import checks pass; target complete coverage of new validation logic.

## 3. PostgreSQL storage and consumer migration

- [x] 3.1 Add the next ordered SQL migration creating the three shared tables, composite identities, stable entry-code initialization/guards, scoped name/system-code uniqueness, fixed contact/log discriminators and restrictive composite FKs. Copy all legacy IDs/names/classifications/locales, verify equality, advance the sequence, move the event classifier, install shared RLS/write/column grants and catalog revision triggers, and remove retired catalog objects safely. Add real PostgreSQL tests for clean/upgrade/rerun/failure rollback, overlapping/sparse IDs, post-upgrade allocation, wrong-dictionary references, referenced deletion, classifier concurrency and direct-runtime permission denial. Update the schema inventory and migration operational notes. Verify the new migration/integrity/security tests pass and prior migration bytes/ledger checksums remain unchanged.
- [x] 3.2 Implement the shared PostgreSQL dictionary store/gateway and delegate existing collaboration catalog methods on their current transaction connection. Rewrite contact/event labels and dashboard blocker/issue queries with dictionary-qualified joins while retaining public projections, locale ordering, fallback, project scoping and phone-data protections. Update existing physical-storage fixtures while preserving behavioral assertions; add rollback and complete-retry regressions for combined name/translation saves, missing rows and renamed/translated blockers. Update collaboration persistence documentation. Verify dictionary/collaboration/dashboard contracts, scoped security and retry tests pass.
- [x] 3.3 Convert reference/demo seeding, sequence handling and full-reset catalog operations to shared storage, preserving installation markers, ordinary project-flush behavior and reset boundaries. Add/update PostgreSQL lifecycle tests for fresh seeds, repeat initialization, edited translations, ordinary flush, full reset, backup/restore validation and unrelated catalog preservation. Update the operator/reset documentation and verify lifecycle and deployed-recovery tests pass against disposable databases.

## 4. Settings translation maintenance

- [ ] 4.1 Compose the dictionary service in `app/main.py` and `SettingsWorkspace` and reuse a common editor through the existing lazy role/event-type tabs. Add canonical-name/English editing and optional fr/de/lb/pt translations, explicit absent-label state, blank removal, stable selection, safe errors and deletion confirmation. Add translated interface strings to the five packaged catalogs and user-facing Settings documentation. Add Streamlit and authenticated browser tests for create/rename/translation/removal, fallback versus explicit text, permission denial, used-entry deletion and lazy-tab behavior. Verify these UI tests, composition/layer checks and packaged-resource tests pass.

## 5. Cross-component integration

- [ ] 5.1 Add integration regressions that warm collaboration/dashboard displays, commit or roll back translated edits, and verify revisions, latest labels, blocker identity and project isolation. Cover simultaneous dictionary edits, immutable identity/classification fields, direct runtime SQL bypass attempts and unaffected excluded catalogs. Add the focused shared-dictionary ADR extending ADR 0010 and document the implemented C4 components, authorization and coordinated rollout; retain ADR 0012/0063 decisions. Verify these integration tests and existing revision/dashboard/scoped-contact regressions pass; inspect active callers for retired catalog-table SQL and record justified migration-history references.

## 6. Acceptance

- [ ] 6.1 Run `openspec validate shared-business-dictionary --strict`, the OpenSpec verify-change workflow, the complete authenticated PostgreSQL/browser pytest suite with `--require-full-suite --cov=app --cov-fail-under=95`, and all JavaScript component checks per `docs/development-workflow.md`. Inspect the final diff, confirm no secrets/unrelated changes or rewritten migrations, and record commands/results/coverage/skips, clean-and-upgrade evidence, scenario-to-test mapping and task-to-commit evidence in `verification.md`. Verify every required gate passes before marking this task complete; unavailable or failed checks keep it unchecked.

## Workflow follow-up

- After a separate user request to apply, implement this plan on its dedicated
  branch using one focused commit per numbered task. The planning request does
  not start implementation.
- After acceptance, archive with the repository archive skill, sync the capability
  delta, inspect the archive and create a separate lifecycle commit.
- Publish the feature branch and create/attach a PR to main. Require full PR CI on
  the final revision and present the concrete PR for review.
- Merge only after explicit user approval of that PR, using a merge commit to
  preserve task history.
