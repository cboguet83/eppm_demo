# PR test gate operations

The delivery policy is in [the development workflow](../development-workflow.md).
Main requires PRs and the GitHub Actions `tests` check, with the branch up to
date. Protection applies to administrators and blocks force pushes and deletion.
Merge commits are the only enabled merge method; automatic merging is disabled.
There is no linear-history requirement. GitHub's required review count is zero
so a sole owner can operate the repository. The agent must still obtain the
user's explicit approval of the concrete PR before merging it.

## Inspect the effective settings

With an authenticated repository administrator, read:

```bash
gh api repos/cboguet83/eppm_demo/branches/main/protection
gh api repos/cboguet83/eppm_demo/rules/branches/main
gh api repos/cboguet83/eppm_demo \
  --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge,allow_auto_merge}'
```

The legacy protection response must require `tests` from GitHub Actions app
15368 with `strict: true`. Confirm administrator enforcement, PR requirements,
and disabled force pushes/deletion. The rules endpoint reports rulesets; an
empty array does not remove the separately returned legacy branch protection.
Do not overwrite existing protection when maintaining settings: inspect and
preserve unrelated checks/rules first. Administrative credentials belong in the
operator's authenticated session, never in the test workflow.

## Interpret checks and recover failures

Draft code changes receive `feedback`; their required `tests` gate intentionally
stays unsuccessful until full acceptance. Mark the PR ready to trigger the full
suite. Policy changes run full checks even while draft. Allowlisted prose-only
changes can pass their policy lane. A manual diagnostic cannot satisfy the PR
gate. Metadata code edits retain the `tests` name and must revalidate the latest
successful complete PR full attempt for the identical head/base/tested merge,
readiness and workflow source. Immutable, attempt-specific policy/full artifacts
expire after seven days. Missing, expired, malformed, stale or unsuccessful
evidence blocks replay; no fallback to an older pass after a newer failed full
attempt is allowed. Only the exact named JSON files are uploaded, never `.local/`
or a credentials directory. Inspect the job log for the selected lane, pinned
revision, and failed prerequisite before rerunning. A cancelled or stale run
does not count as acceptance; ready code updates need their own full result.

If a metadata edit occurs during full execution, the metadata gate fails quickly
rather than consuming runner minutes waiting. After full succeeds, rerun only
that metadata gate (GitHub's failed-job rerun, or `gh run rerun --job <gate-job-id>`).
This revalidates existing full proof and does not rerun the suite. If proof is
missing/expired or the latest acceptance was a partial rerun without a complete
full attempt, run fresh full acceptance. Verify the native merge box recognizes
passing `tests`; an older green check in the API alone is insufficient. Keep
manual diagnostics in their separate check context. Never attempt a merge just
to test whether protection is working.

If the selective rollout fails, restore full-on-every-PR execution through a
reviewed fix while preserving the required `tests` context, complete collection,
real PostgreSQL/OIDC checks, both JavaScript suites, asset consistency and 95%
application coverage. Keep branch protection and explicit merge approval. Do
not recover by removing required checks, lowering coverage, or accepting local,
partial or stale proof. A settings correction requires separate explicit
authorization after inspecting its concrete payload.

The optional pgAdmin overlay can be reverted independently if necessary. Keep
the documented Compose project identity and existing data volumes; do not
reset a database or remove a volume as part of a CI rollback.
