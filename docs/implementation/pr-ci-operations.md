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
changes can pass their policy lane. A manual diagnostic or metadata edit cannot
satisfy the PR gate. Inspect the job summary for the selected lane, pinned
revision, and failed prerequisite before rerunning. A cancelled or stale run
does not count as acceptance; ready code updates need their own full result.

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
