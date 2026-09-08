# EPPM — Codex Agent Instructions

## 1. Mission

Develop a proof of concept of portfolio project management tool focusing on user interfaces and user experience. 

### Authority hierarchy

When sources conflict:

1. Explicit user instruction in the current task.
2. Existing working code and tests, unless explicitly superseded.
3. Existing repository conventions.
4. General engineering judgment.

Never silently change a locked business or architectural decision.

---

## 2. Architecture

The target architecture is layered:

## 3. Working method

Before changing existing code:

1. Inspect the repository.
4. Inspect the implementation.
5. Inspect affected tests.
6. Identify dependencies and affected layers.
7. Make the smallest coherent change.
8. Add/update tests.
9. Run relevant validation.
10. Inspect the final diff.
11. Update documentation if behavior or architecture changed.

Do not introduce a framework, service, library, abstraction, database technology, or architectural layer without a concrete reason.

If an ambiguity is safely reversible, make the smallest assumption and document it.

If ambiguity materially affects business behavior or architecture, ask before proceeding.

---

## 4. Python baseline

- **Python 3.14.x is the supported project runtime.**
- Project metadata must target Python `>=3.14,<3.15`.
- Docker and CI runtimes must use Python 3.14.x.
- Do not introduce compatibility code for older Python versions unless explicitly required.
- Follow PEP 8.
- Prefer clear, idiomatic Python.
- Use strong type hints.
- Public APIs require explicit parameter and return types.
- New or modified public modules, classes, and functions should have useful Google-style docstrings.
- Prefer native typing syntax where appropriate.
- Avoid `Any` unless a boundary is genuinely dynamic; document its use.
- Avoid mutable default arguments.
- Keep functions focused and cohesive.
- Frontend to use stremalit and custom havascript components when streamlit is not sufficient.
Do not add meaningless annotations merely to satisfy a percentage.

---

## 5. Security and configuration

- Never hardcode credentials, API keys, passwords, OAuth tokens, certificates, or other secrets.
- `.env` and secret-bearing local configuration must be Git-ignored.
- `.env.example` contains variable names and safe placeholders only.
- Keep configuration outside business logic.
- Prefer typed configuration such as `pydantic-settings`.
- Never log secrets, access tokens, passwords, authorization headers, or sensitive payloads.
- Validate external inputs at application boundaries.
- Server-side authorization is authoritative.
- Never weaken security to make tests pass.
- Never disable TLS certificate verification in production code.

For subprocesses:
- Prefer a library/API over subprocesses.
- Never use `shell=True` with constructed or untrusted input.
- Pass arguments as a list.
- Validate/allowlist inputs when appropriate.

---

## 6. Error handling and logging

- Never use bare `except:`.
- Catch the narrowest meaningful exception.
- Do not use `except Exception` as a default strategy.
- `except Exception` is acceptable at deliberate application boundaries when errors are handled, translated, and/or logged appropriately.
- Never silently swallow errors.
- Avoid empty exception handlers.
- Use the project's logging infrastructure.
- Do not use naked `print()` for application diagnostics.
- Preserve exception causes with `raise ... from exc` where useful.
- Never expose internal stack traces or secrets through APIs.

---

## 7. Twelve-Factor and dependency injection

Apply Twelve-Factor principles where relevant:
- configuration outside code
- explicit dependencies
- stateless processes
- reproducible builds
- logs as event streams
- separation of build/release/run

Prefer dependency injection for:
- database sessions
- repositories
- external API clients
- filesystem abstractions
- clocks/time providers
- message publishers/consumers

Avoid hidden global mutable state.

Do not create abstractions without a real architectural or testing benefit.


## 10. i18n

Stable codes are not translated.

User-facing reference data uses translation tables.

Do not create language-specific columns such as:
```text
name_en
name_fr
name_de
```

---

## 11. Testing

Testing is mandatory for code changes.

Use `pytest`.

Use:
- unit tests for domain/business logic
- integration tests for persistence and constraints
- API tests for application boundaries
- end-to-end tests for critical workflows

Mock genuinely external boundaries.

Do not mock away database behavior when testing database integrity.

Use real PostgreSQL integration tests for important:
- constraints
- transactions
- locking
- migrations
- repository behavior

Prefer AAA:
```text
Arrange
Act
Assert
```

Tests must have descriptive names.

Coverage target:
- minimum 99% statement coverage across the codebase
- very high coverage for critical business logic
- aim for 100% coverage where practical for financial calculations, parsers, authorization rules, and critical integrity logic

Do not create low-value tests solely to satisfy coverage.

Every bug fix should include a regression test where practical.

---

## 12. Financial and business correctness

Use decimal/numeric arithmetic for authoritative monetary values.
Monetary unit is euro.

Never use binary floating-point for authoritative financial calculations.

Explicitly distinguish:
- budget
- forecast
- actual
- commitment

Approved financial information is historical business truth.

Closed periods are not normally editable.

---



## 14. API and frontend

Keep API contracts separate from persistence models.

Do not expose raw DB models as public API contracts by default.

Validate requests at the boundary.

Business rules belong in application/domain services, not only in route handlers.

API errors must be:
- structured
- predictable
- safe
- free of internal stack traces

Frontend validation is for usability.

Server-side validation and authorization are authoritative.

Do not duplicate critical business rules only in the frontend.

---

## 15. Performance and resources

Avoid N+1 database access.

For large datasets consider:
- pagination
- batching
- streaming
- indexes
- bulk operations

Measure before non-trivial optimization.

---

## 16. Sonar and code quality

When SonarQube tooling is available and the user requests:
- static analysis
- quality gate validation
- vulnerability review
- code-smell review

use it.

Prefer:
- guard clauses
- cohesive functions
- limited nesting
- explicit error handling
- no dead code
- no unnecessary duplication

Target cognitive complexity below 15 per function where practical.

Three-level indentation is a guideline, not an absolute requirement that makes code less readable.

Recursive hierarchy processing must have deliberate termination/cycle handling.

---

## 17. C4 architecture documentation

Use C4 for architecture documentation.

Keep levels distinct:

```text
C1 — System Context
C2 — Containers
C3 — Components
C4 — Code
```

Do not turn every architecture diagram into a giant class diagram.

Never document components that do not exist.

For detailed code maps, accurately represent relevant:
- classes
- methods
- functions
- configuration components
- dependencies

Do not map every local variable.

Mermaid relationships:

```text
Inheritance:           BaseClass <|-- SubClass
Composition:           ClassA *-- ClassB
Injected dependency:   ClassA o-- ClassB
Usage/call:            ClassA --> ClassB
```

Use relationships according to actual code semantics.

Never invent missing types or dependencies.

---

## 18. Git discipline

- Never overwrite unrelated user work.
- Keep changes focused.
- Never commit secrets.
- Inspect Git state before significant changes.
- Review diffs before completion.
- Do not rewrite applied migrations.
- Do not create pull requests unless explicitly requested.

When the user explicitly requests a commit, make a focused commit with a meaningful message.

---

## 19. Terminal/tool use

Use available project tooling.

Complete software development requires legitimate repository operations such as:
- inspecting files
- running tests
- validating migrations
- running application checks
- inspecting Git state
- using project-local tooling

Still:
- avoid destructive commands without clear justification
- never delete/reset user work without authorization
- do not execute untrusted downloaded scripts blindly
- avoid unnecessary external network activity

---

## 20. Decisions

Use `docs/decisions/` for durable Architecture Decision Records.

If implementation conflicts with a locked decision:
1. Explain the conflict.
2. Explain the technical consequence.
3. Present alternatives.
4. Recommend a solution.
5. Obtain the decision.
6. Update the relevant documentation.
7. Update tests.
8. Implement.

Do not silently change the architecture.

---

## 21. Definition of done

A feature is complete when applicable:
- implementation is complete
- business rules are preserved
- API/UI contracts are updated
- migrations are added
- tests are added/updated
- relevant tests pass
- security implications are reviewed
- logging/error handling is appropriate
- documentation is updated
- no secrets are introduced
- no unrelated changes are included

For database changes additionally verify:
- clean database migration success
- migration ordering
- constraints
- transactional behavior

The goal is a coherent, maintainable, production-ready EPPM application, not merely a collection of database tables.

<!-- sonar:begin:codex-secrets-on-read -->
# SonarQube analysis and secrets-scanning protocol

Use the configured SonarCloud MCP server for project analysis, quality-gate
status, and issue retrieval. Use the Sonar CLI only for the deterministic
per-file secrets scan below.

Before reading any file in this workspace, scan it for secrets with the deterministic scanner:

```bash
sonar analyze secrets <path/to/file>
```

If the command reports that the file contains a secret, **do not read the file**. Instead:

1. Inform the user that the file appears to contain a secret or credential and that reading it would expose the value in chat history, logs, and any downstream telemetry.
2. Advise them to rotate the leaked credential at its source of truth and remove it from the file.
3. Do not proceed with the original request until the secret has been removed.
<!-- sonar:end:codex-secrets-on-read -->
