# Proposal

## Why

The complete integration-heavy suite takes about 18 minutes locally and 22
minutes in the last measured hosted run, while an audited candidate subset of
783 tests passes without database or browser services in about 7.5 seconds.
Developers need that fast feedback during editing and draft PRs, with complete
verification retained before merging code; PostgreSQL-only startup also needs
to stop requiring optional pgAdmin credentials.

## What Changes

- Provide maintained `fast`, explicit-path `targeted`, and `full` local test
  commands. Fast/targeted results are partial feedback and never claim the full
  95% application coverage gate.
- Run selective feedback on draft code PRs. Automatically run the full suite
  when a code PR is opened ready for review, marked ready, reopened ready, or
  updated while ready. Later revisions require fresh full acceptance.
- Allow only narrowly allowlisted prose/documentation changes to omit runtime
  tests. Treat mixed, unknown, executable, test, configuration, and asset changes
  as code; inability to establish the complete diff requires full checks.
- Keep a stable required `tests` merge gate, bound to the current PR revision
  and base. It must never accept selective draft feedback as code acceptance,
  or accept failed, skipped, missing, or cancelled required jobs. Retain manual
  full diagnostics and cancel obsolete runs for the same PR.
- Preserve complete pytest discovery, real isolated PostgreSQL and authenticated
  browser checks, migrated templates, two audited workers, subprocess coverage,
  `--require-full-suite`, the unchanged 95% coverage scope/threshold, both
  JavaScript suites, generated-asset checks, and existing SonarCloud integration.
- Move pgAdmin into an explicitly selected development Compose overlay, declare
  its volume, and test startup configuration with and without optional tools.
  Preserve the existing PostgreSQL volume and loopback ports 5434 and 5050.
  Make the isolated test overlay replace the development port with 15432,
  allowing tests to start alongside the application.
- Configure and read back main's required PR/check and up-to-date protections,
  with merge commits enabled and squash/rebase merging disabled. This scope was
  explicitly selected by the user during planning; no settings change occurs
  during planning.
- Update developer instructions and record reproducible feedback timings and
  full acceptance evidence. Keep one commit per task and explicit user approval
  of the concrete PR before merging with a merge commit.

## Capabilities

### New Capabilities

None. This is development tooling, CI policy, and optional operator tooling.
The change declares `skip_specs: true` rather than inventing product behavior.

### Modified Capabilities

None. Existing business, authorization, persistence, and UI requirements remain
unchanged.

## Impact

Expected implementation areas are `scripts/`, test-suite inventory and runner
regressions under `tests/`, `.github/workflows/tests.yml`, PostgreSQL/pgAdmin
Compose files, README and development/deployment guides, plus GitHub repository
merge/protection settings. No new application library, schema migration,
migration squash, test deletion, weaker assertion, higher worker count, or
business behavior change is planned.

The branch is `codex/fast-local-selective-pr-ci`, created from fetched main
`d4a769f12d92fc01d6fc49a1c4d16ca0be41ecee`. Measurements and limitations are in
[baseline.md](baseline.md). The user selected automatic full CI on readiness
and subsequent ready-PR updates, and included remote protection setup.
There are no unresolved user policy choices. Exact GitHub settings payloads
must be previewed and their permissions verified before application.

This proposal authorizes planning only. Implementation, external settings
changes, acceptance, archive, and PR delivery follow a later apply request.

## Approved rollout correction — 2026-10-19

The original implementation was verified, archived and published as PR #6.
Hosted full acceptance passed 3,581 tests and five subtests with 97.71%
application coverage; both JavaScript suites, assets and SonarCloud passed.
GitHub's live merge box nevertheless shows required `tests` as Expected after
a later metadata-only run omits that check. Main and the tested revision did
not change. The API's older passing check alone does not establish native merge
readiness.

The user approved reopening this change to let code-PR metadata updates publish
the stable `tests` gate only after validating already-successful full acceptance
for the exact PR, head, base, tested merge revision and workflow source. Preserve
the prose-only exemption through a fresh audited diff, and keep manual diagnostic
results separate. Missing, stale, failed, cancelled or incomplete full proof and
draft feedback never qualify. Pending proof fails quickly; retrying that cheap
gate after full completion must not rerun the expensive suite. Add focused
regressions and separate task commits, repeat full acceptance, re-archive, update
PR #6, and verify the native merge box after a genuine evidence-only edit. No
merge or weakening of the approved branch protection is authorized.
