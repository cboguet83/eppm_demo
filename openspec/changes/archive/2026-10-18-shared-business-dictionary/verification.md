# Verification: shared-business-dictionary

## Current verdict

All ten tracked tasks are complete. The complete strict acceptance suite passed
on application revision `1fb7f13`: 3,283 tests and five subtests, no skips, with
97.70% statement coverage. OpenSpec strict validation and all JavaScript component
checks also passed. No critical findings, warnings or unverified checks remain
in this OpenSpec implementation assessment. The change is synced and archived,
ready for PR delivery under the standing workflow.

| Dimension | Evidence |
| --- | --- |
| Completeness | 10/10 tasks complete; all 14 added requirements mapped below |
| Correctness | All 29 scenarios have implementation and test evidence; complete strict acceptance passed |
| Coherence | Shared tables, composite consumer references, injected transactions, existing Settings navigation and scope exclusions match the design |

No implementation requirement was dropped or deferred. This report is an
OpenSpec verify-change assessment; it is not a SonarQube static-analysis report.
Full GitHub CI on the final PR revision and explicit user approval remain merge
requirements. The disposable test databases were the only migration targets.

## Requirement and scenario evidence

Paths below are relative to the repository root. Scenario groups refer to every
scenario under the named requirement in the capability delta.

| Requirement / scenarios | Implementation | Tests |
| --- | --- | --- |
| Dictionary-qualified identities: overlapping IDs; rename/translate identity | Migration 0069 composite keys, immutable entry codes and identity trigger | `test_dictionary_migration.py::test_dictionary_upgrade_preserves_overlapping_ids_and_rolls_back_failures`; `test_dictionaries.py::test_shared_dictionary_translation_edit_fallback_and_reference_lifetime` |
| Bounded scope: unsupported dictionary | `domain/dictionaries.py::dictionary_code`, fixed dictionary definitions | `tests/test_dictionaries.py::test_dictionary_codes_reject_unknown_values`; `test_dictionary_integration.py::test_dictionary_identity_guard_and_excluded_catalogs_remain_independent` |
| Name uniqueness: case-equivalent duplicates; same name across dictionaries | Scoped lowercase unique index and dictionary-qualified store queries | `test_dictionaries.py::test_shared_dictionary_translation_edit_fallback_and_reference_lifetime`; existing collaboration catalog contracts |
| Translation fallback: present/missing locale; canonical rename with retained other labels | `PostgresDictionaryStore.list_entries`, `dictionary_edit`, atomic `save_entry` | `test_dictionaries.py::test_shared_dictionary_translation_edit_fallback_and_reference_lifetime`; `test_collaboration.py` localized catalog contracts |
| Locale editor: add/remove translation; absent versus fallback text | `render_project_catalog`, `_translation_fields`, injected Settings dictionary service | `test_dictionary_ui.py::test_editor_creates_renames_translates_and_removes_explicit_labels`; authenticated `test_dictionary_browser.py` workflow |
| Boundary validation: invalid locale; missing entry | Domain validators; store updates require an existing entry | `tests/test_dictionaries.py` invalid edit/locale/ID cases; `test_dictionaries.py` missing update/translation cases |
| Typed references: other-kind ID; forged discriminator | Generated fixed dictionary columns and restrictive composite foreign keys | `test_dictionary_migration.py::test_runtime_dictionary_membership_permissions_and_immutable_fields` |
| Delete protection: referenced role; unused entry | Native RESTRICT consumer FKs and cascading translation FK | `test_dictionary_migration.py` populated upgrade restriction; `test_dictionary_ui.py::test_editor_used_role_cannot_be_deleted`; `test_dictionaries.py` unused deletion; `test_dictionary_integration.py` referenced event deletion |
| Authorization: project editor cannot administer; scoped translated reads | Shared service permission, runtime RLS/write guards, existing project ownership | `test_dictionaries.py::test_dictionary_service_denies_nonadministrators_without_changing_labels`; migration direct-runtime denials; `test_dictionary_integration.py::test_translated_contacts_and_blockers_follow_commit_revision_and_project_scope`; existing scoped collaboration workflows |
| Atomic edits: translation failure; concurrent rename | Shared store on one connection; `run_business` complete-operation retries | `test_dictionaries.py::test_translation_failure_rolls_back_names_english_and_other_translations`; `test_concurrent_dictionary_edits_replay_complete_translation_commands`; existing collaboration retry/rollback tests |
| Blocking identity: rename; role with same name; initial classified event type | Dictionary-scoped immutable `system_code`, insertion classifier, qualified dashboard joins | `test_dictionary_migration.py::test_dictionary_classification_is_event_only_and_concurrent_safe`; `test_dictionary_integration.py::test_translated_contacts_and_blockers_follow_commit_revision_and_project_scope`; dashboard blocker regressions |
| Cache publication: committed label change; rolled-back edit | Catalog revision triggers on shared entries/translations | Both commit and rollback cases in `test_dictionary_integration.py`; existing `test_revisions.py` source-table contract |
| Upgrade compatibility: populated upgrade; failure rollback | Ordered atomic 0069; original IDs/locales/classifications copied; prior ledger retained | Both parametrized upgrade/rollback cases in `test_dictionary_migration.py`; fresh migration fixtures; rerun and next-ID assertions |
| Operator lifecycle: repeat seed; ordinary flush; full reset | Qualified seed/reset SQL, existing installation markers, sequence high-water repair | `test_seed_catalog.py`, including explicit localized labels; `test_seed_projects_reset.py`; `test_operator_commands.py`; deployed restart/restore acceptance |

Test paths without a prefix in the final column are under `tests/postgresql/`.

## Checks executed

Commands used the existing Python 3.14.7 virtual environment and ignored local
configuration. Credentials are never included here. PostgreSQL fixtures create
random disposable databases with distinct operator/runtime roles; application
databases were not migrated or reset.

| Check | Result |
| --- | --- |
| Domain/service and layer tests | 40 passed; new domain/service code 100% statement coverage |
| Dictionary upgrade/integrity/security tests | 4 passed, including populated upgrade, failure rollback, runtime denials and concurrent classification |
| Shared store and collaboration tests | 26 passed; shared PostgreSQL dictionary adapter 100% statement coverage |
| Dashboard native contracts | 16 passed |
| Lifecycle/operator group | 30 passed; its opt-in recovery case initially skipped, then executed separately successfully |
| Explicit label preservation on repeat seed | Passed in the subsequent 12-test seed run |
| Deployed recovery with isolated dictionary image | 1 passed in 162.22 seconds; authenticated app restart and restored-database parity |
| Translation editor AppTests | 5 passed |
| Authenticated native Settings browser | 1 passed |
| Layer/composition and packaged resources | 17 passed |
| Integration/revision/collaboration group | 49 passed before correcting an obsolete SQL fixture in the next test; unchanged passing groups retained |
| Corrected dashboard/scoped portfolio group | 58 passed |
| JavaScript component checks | 10 passed, no skips |
| `openspec validate shared-business-dictionary --strict` | Passed |
| Staged/final whitespace checks | Passed for each task commit |
| Full `--require-full-suite --cov=app --cov-fail-under=95` run, attempt 1 | Failed at an authenticated access-administration project selection after 2,939 passed and 5 subtests; the exact isolated test then passed in 38.28 seconds, and its full module passed again in 38.92 seconds. |
| Full acceptance, attempt 2 | Failed after 685 passed in 520.59 seconds at `test_finance_curve_uses_selected_project_share[distinct-budget-shares]`: project deselection did not restore the expected 1,000-project view within the assertion timeout. Earlier finance-value assertions passed. |
| Dashboard reproduction | The exact failing case passed in 4.46 seconds; the full two-test dashboard browser module passed in 14.20 seconds. |

Those two full attempts preceded the authorized repairs. Neither satisfies
acceptance; the successful final run below supersedes them. The user explicitly
authorized expanding scope to repair the failures; task 5.2 records that work.

## Authorized browser repairs: task 5.2

The unchanged dashboard case reproduced after 16 successful isolated executions.
A minimally instrumented repeat failed after another 27 successes: the selected
view rerendered without the second selection callback. Repeated activation of one
rendered row produced identical trigger payloads, while its token also changed
with the selected-row paging snapshot. The new JavaScript regressions both fail
against the pre-repair component (missing distinct event identity and wrong token)
and both pass against the repair. Row activations now have unique nonces and use
the revision/active-filter token independently of paging. Every callback still
reauthorizes current filtered projects; stale-filter and inaccessible-ID tests
remain. The original finance-value assertions now run through five cycles.

The native account/project probe reproduced the access failure on iteration 23 in
48.42 seconds. A browser-only diagnostic of the pinned multiselect module and its
outgoing widget state showed empty change events while filtering, followed by an
empty project selection reaching the server. The native widget can also clear its
local query, so waiting for menu unmount, keyboard selection and form batching did
not solve the reproduced failure; those variants are not retained. Named-project
choices now use the existing authorized server search and a bounded, scrollable
native checkbox list. Multiple choices and removal remain supported. Grant access
still performs the same server-side validation and audited mutation.

| Repair validation | Result |
| --- | --- |
| Pre-repair component replay using `node` and the original component from `git show HEAD:...` before the repair commit | Both new event regressions fail for the intended reasons |
| `node tests/test_dashboard_table.cjs` | 2 passed |
| Repeated dashboard interaction probe | 100 cycles passed in 124.61 seconds; permanent browser test retains its original five-second assertions and now repeats five cycles |
| Repeated native account/project probe | 100 repetitions passed in 73.71 seconds |
| `pytest -q -x --tb=short tests/postgresql/test_access_browser.py tests/postgresql/test_access_presentation.py tests/postgresql/test_fragment_reruns.py tests/postgresql/test_dashboard_ui.py tests/postgresql/test_dashboard_browser.py` | 41 passed in 82.84 seconds, including no grant before explicit submission and exact persisted scope |
| `pytest -q -x --tb=short tests/test_oidc_browser_e2e.py tests/postgresql/test_access_presentation.py::test_administrator_can_retain_a_named_project_selection_and_grant_its_scope` | 2 passed in 41.26 seconds; authenticated activation, scoped grant, revocation and multiple-choice/removal checks |
| `node --test tests/test_*.cjs` | 11 component files passed, no skips |

Python commands above used the same ignored dotenv configuration and Python 3.14
runtime as the original checks. The isolated image was rebuilt for the final
authenticated workflow. No temporary instrumentation, dependency patch, weakened
permission check, relaxed behavioral assertion or coverage exclusion is retained.

The initial authenticated deployment could not mount assets from `/tmp` under
Docker Desktop. The same isolated worktree was moved to the repository's ignored
`.local/worktrees/shared-business-dictionary` directory and Git registration was
repaired. The successful deployment used that location. A separate
`eppm-demo:dictionary` image avoids replacing another task's test image.

The active SQL audit found no retired role/event catalog table references in
application Python. References remain only in the unchanged historical SQL
migrations, the new migration's copy/drop statements and intentional preceding-
schema upgrade tests. Migration files 0001-0068 and checksummed hooks are unchanged.
No external dependency, role/permission relaxation, coverage exclusion or ignored
credential file is included in the Git diff.

## Final integrity correction: task 5.3

The final design review identified that the planned nonblank locale rule was
enforced by application validation but not by SQL. Additive migration 0070
completes that rule without rewriting any existing migration. Its initially
unvalidated check preserves historical blank locale keys while rejecting new
blank or whitespace-only keys. It validates the existing population immediately
when compatible. The upgrade regression now covers both historical blank-key and
ordinary populations, preservation of every row, constraint validation state,
rerun safety and failure rollback. Direct authorized runtime SQL attempts verify
the constraint cannot be bypassed by skipping Python validation.

`pytest -q -x --tb=short tests/postgresql/test_dictionary_migration.py
tests/postgresql/test_dictionaries.py tests/postgresql/test_dictionary_integration.py`
passed all 18 tests in 10.99 seconds using the isolated dotenv configuration.
The first post-repair acceptance attempt was deliberately interrupted after 232
passed in 208.83 seconds to make this correction. It is not acceptance evidence;
the complete strict suite restarted on the corrected committed revision.

## Final acceptance: task 6.1

The unchanged application and test sources at `1fb7f13` passed:

```text
python -m dotenv -f .local/dictionary-tests.env run -- python -m pytest -q --tb=short --require-full-suite --cov=app --cov-fail-under=95 --cov-report=term-missing --cov-report=json:.local/dictionary-coverage.json
3283 passed, 5 subtests passed in 3083.29s (0:51:23)
Required test coverage of 95% reached. Total coverage: 97.70%
```

Both Python executables were the existing Python 3.14.7 virtual environment.
There were no skips. Strict mode required real isolated PostgreSQL and real
authenticated browser participation. Host-process coverage includes native browser
server execution; containerized OIDC behavior is verified separately and is not
claimed as host-process coverage.

| Coverage | Covered / statements | Percentage |
| --- | --- | --- |
| Application | 16,682 / 17,074 | 97.70% |
| New dictionary domain | 40 / 40 | 100% |
| New dictionary application service | 21 / 21 | 100% |
| New shared PostgreSQL adapter | 56 / 56 | 100% |

The final JavaScript invocation passed all 11 component files with no skips.
OpenSpec strict validation passed. The final diff/whitespace audit passed; only
additive migrations 0069 and 0070 differ from the fetched baseline, with 0069
unchanged by the later integrity correction. No secrets, dependency patches,
coverage exclusions or unrelated user changes are included. The expanded browser
scope and its evidence are recorded above and in proposal/design/task artifacts.

A read-only GitHub check confirmed merge commits are available and reported main
as unprotected; squash and rebase methods are also enabled. This workflow still
requires a merge commit after full PR CI and explicit approval. Repository settings
were not changed.

## Task-to-commit evidence

Source: `git log origin/main..HEAD --oneline` on the dedicated branch, based on
fetched main at `0b6ebb0`.

| Task | Commit |
| --- | --- |
| 1.1 Planning | `83e12af` |
| 2.1 Typed service | `91d64fa` |
| 3.1 Migration | `28e8f80` |
| 3.2 Shared store | `5a317b8` |
| 3.3 Lifecycle | `be835f5` |
| 4.1 Translation editor | `0b2595c` |
| 5.1 Integrated contracts | `04342b2` |
| 5.2 Authorized browser repairs | `591acd2` |
| 5.3 Planned SQL locale integrity | `1fb7f13` |
| 6.1 Full acceptance | `20a1587` |

## Sync and archive evidence

The new main specification at `openspec/specs/shared-business-dictionaries/spec.md`
contains all 14 added requirements and 29 scenarios. Its purpose and requirement
bodies match the delta verbatim; only the main-spec title and Requirements header
change. All six main specifications pass `openspec validate --specs --strict`.

All four planning artifacts and all ten tracked tasks were complete before the
change moved to `openspec/changes/archive/2026-10-18-shared-business-dictionary`.
The archive preserves `.openspec.yaml` byte-for-byte. No active copy remains.
This lifecycle update changes planning/specification documentation only; the
application and tests remain at the locally verified revision `1fb7f13`.
