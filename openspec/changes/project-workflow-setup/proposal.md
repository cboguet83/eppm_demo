# Proposal

## Why

EPPM has substantial regression coverage but no recorded OpenSpec delivery lifecycle, and its GitHub Actions checks run only on manual dispatch. Establish a repeatable process that preserves task commits and requires complete verification and human approval before merging into main.

## What Changes

- Retain the user-initialized repository-local OpenSpec configuration and Codex skills, reviewing generated files before committing them.
- Record the agreed workflow in AGENTS.md and a linked contributor guide: GrillMe requirements discovery, one dedicated feature branch per change before planning, one focused commit per numbered task, complete verification, archive, PR, and explicit user approval before merging.
- Add project-specific OpenSpec artifact rules and apply/archive guidance without editing generated skill bodies.
- Enable the existing full GitHub Actions suite on every PR, retaining manual dispatch and Python 3.14, isolated PostgreSQL, authenticated browser coverage, JavaScript checks, and the 95% application coverage threshold.
- Add a strict full-suite mode that fails when required PostgreSQL or authenticated browser tests skip, while preserving convenient partial local runs.
- Correct pre-existing JavaScript assertions for the existing one-decimal FTE display so the required full check reflects current UI behavior; leave application formatting unchanged (approved during apply).
- Repair baseline Python fixtures and assertions for current dashboard labels, bounded-key migration scope, planning edit-mode interactions, employee-function relationships, and shared-filter selectors. Preserve security and data-integrity assertions (approved during apply).
- Restore free-text project tags in the scoped shared filter catalog and harden the WBS constraint helper through a new migration, preserving the existing function body and all applied migration checksums (approved during apply).
- Document task-to-commit evidence, archive/PR sequencing, and merge commits that preserve task history. PR creation is authorized by this standing workflow; merging always requires the user's explicit approval of the concrete PR.

## Capabilities

### New Capabilities

- `shared-project-filtering`: Scoped dictionary and free-text project tag choices and Any/All matching.
- `protected-database-helpers`: Explicit safe search paths for privileged WBS integrity helpers, including upgrades without rewriting applied migrations.

The original tooling-only proposal skipped specs. The explicitly approved
application regression repairs now require these two focused capability deltas;
this does not attempt to specify the entire existing application.

### Modified Capabilities

None. No existing durable specs are present.

## Impact

Implementation targets AGENTS.md, README.md, openspec/config.yaml, a contributor workflow guide, .github/workflows/tests.yml, and focused pytest infrastructure/regressions for strict suite enforcement. Generated .agents/skills files and initial OpenSpec configuration become versioned bootstrap inputs. Approved baseline repairs also affect scoped dashboard tag reads and a new function-hardening migration. Application business rules, runtime dependencies, and architecture remain unchanged; applied migrations are preserved.

GitHub branch-protection and merge-method settings are a separate remote administrative concern: document required settings and report whether they are verified; local instructions alone do not enforce server-side protection. Dependency locking, general static-analysis rollout, and retroactively specifying the entire application are outside this change.
