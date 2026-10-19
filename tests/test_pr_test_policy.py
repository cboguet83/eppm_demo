"""Exercise lane decisions, source identities and false-green merge regressions."""

from pathlib import Path
import json
import subprocess
from typing import Any

import pytest

from scripts import pr_test_policy as policy


BASE = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40


def _event(draft: bool = False, action: str = "synchronize") -> dict[str, Any]:
    """Build dynamic JSON transport fixtures; Any is confined to this boundary."""
    return {"number": 6, "action": action, "pull_request": {
        "draft": draft, "head": {"sha": HEAD}, "base": {"sha": BASE, "ref": "main"},
    }}


def _needs(decision: policy.Decision) -> dict[str, Any]:
    """Build the dynamic Actions transport object for result mutation tests."""
    receipt = {"sha": decision.tested_sha, "decision_digest": decision.digest}
    selected = {"full": "full", "manual": "full", "feedback": "feedback"}.get(decision.lane)
    return {
        "policy": {"result": "success", "outputs": {"decision": decision.encode()}},
        **{name: {"result": "success" if name == selected else "skipped", "outputs": receipt}
           for name in ("full", "feedback")},
    }


@pytest.mark.parametrize("draft,paths,lane", [
    (True, {"app/domain/finance.py"}, "feedback"),
    (False, {"app/domain/finance.py"}, "full"),
    (True, {"README.md"}, "docs"),
    (False, {"docs/decisions/0065-reusable-planning-visualization.md"}, "docs"),
    (False, {"openspec/changes/example/.openspec.yaml", "openspec/changes/example/tasks.md"}, "docs"),
    (False, {"README.md", "unknown/new.file"}, "full"),
    (False, {"docs/archive/sqlite/benchmarks/observer.py"}, "full"),
    (True, {".github/workflows/tests.yml"}, "full"),
    (True, {"scripts/pr_test_policy.py"}, "full"),
    (True, {"tests/suites.json"}, "full"),
    (True, {"docs/development-workflow.md"}, "full"),
    (True, None, "full"), (False, set(), "full"),
])
def test_policy_selects_only_the_allowed_feedback_or_acceptance_lane(
    draft: bool, paths: set[str] | None, lane: str,
) -> None:
    """Unknown/mixed files remain code and unavailable diffs cannot exempt tests."""
    decision = policy.decide(_event(draft), "pull_request", MERGE, paths)
    assert decision.lane == lane
    assert policy.Decision.decode(decision.encode()) == decision


def test_readiness_without_a_new_commit_cannot_reuse_draft_feedback() -> None:
    """Same-SHA feedback never grants acceptance before or after marking ready."""
    paths = {"app/main.py"}
    draft = policy.decide(_event(True), "pull_request", MERGE, paths)
    with pytest.raises(ValueError, match="deferred"):
        policy.accept(_needs(draft), MERGE)
    ready = policy.decide(_event(False, "ready_for_review"), "pull_request", MERGE, paths)
    assert ready.lane == "full"
    stale = _needs(draft)
    stale["policy"] = _needs(ready)["policy"]
    with pytest.raises(ValueError):
        policy.accept(stale, MERGE)
    assert policy.accept(_needs(ready), MERGE) == ready
    converted = policy.decide(_event(True, "converted_to_draft"), "pull_request", MERGE, paths)
    with pytest.raises(ValueError, match="deferred"):
        policy.accept(_needs(converted), MERGE)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", None, "neutral", "timed_out"])
@pytest.mark.parametrize("job", ["policy", "full"])
def test_every_unsuccessful_required_job_blocks_merge(job: str, result: str | None) -> None:
    """All-skipped/cancelled/missing required work can never become a green gate."""
    decision = policy.decide(_event(), "pull_request", MERGE, {"app/main.py"})
    needs = _needs(decision)
    needs[job]["result"] = result
    with pytest.raises(ValueError):
        policy.accept(needs, MERGE)


@pytest.mark.parametrize("field,value", [("sha", HEAD), ("decision_digest", "stale")])
def test_successful_job_without_matching_identity_cannot_pass(field: str, value: str) -> None:
    """A prior revision/base or another decision's receipt is insufficient."""
    decision = policy.decide(_event(), "pull_request", MERGE, {"app/main.py"})
    needs = _needs(decision)
    needs["full"]["outputs"][field] = value
    with pytest.raises(ValueError, match="identity receipt"):
        policy.accept(needs, MERGE)


def test_base_change_requires_new_full_proof_even_with_the_same_head() -> None:
    """The decision digest binds the base as well as the source/merge revision."""
    event = _event(action="edited")
    event["changes"] = {"base": {"ref": {"from": "other"}}}
    original = policy.decide(event, "pull_request", MERGE, {"app/main.py"})
    event["pull_request"]["base"]["sha"] = "d" * 40
    revised = policy.decide(event, "pull_request", MERGE, {"app/main.py"})
    assert revised.lane == "full" and revised.digest != original.digest
    stale = _needs(original)
    stale["policy"] = _needs(revised)["policy"]
    with pytest.raises(ValueError):
        policy.accept(stale, MERGE)


def test_metadata_and_manual_runs_never_publish_the_required_pr_context() -> None:
    """A title edit or standalone diagnostic cannot replace PR acceptance."""
    event = _event(action="edited")
    event["changes"] = {"body": {"from": "old body"}}
    metadata = policy.decide(event, "pull_request", MERGE, {"app/main.py"})
    manual = policy.decide({}, "workflow_dispatch", HEAD, None)
    assert metadata.context == "metadata checks"
    assert manual.context == "manual acceptance"
    assert policy.accept(_needs(metadata), MERGE) == metadata
    assert policy.accept(_needs(manual), HEAD) == manual


def test_missing_results_and_stale_policy_are_not_acceptance() -> None:
    """The reducer requires the complete expected graph on its own revision."""
    decision = policy.decide(_event(), "pull_request", MERGE, {"app/main.py"})
    needs = _needs(decision)
    with pytest.raises(ValueError):
        policy.accept(needs, HEAD)
    del needs["full"]
    with pytest.raises(ValueError):
        policy.accept(needs, MERGE)


def test_complete_git_diff_preserves_deleted_and_renamed_code_and_large_changes(tmp_path: Path) -> None:
    """A prose destination cannot hide a code origin or a file past API limits."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, text=True,
                              capture_output=True, check=True).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / "code.py").write_text("unchanged content\n")
    (tmp_path / "deleted.py").write_text("to delete\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "code.py").rename(tmp_path / "README.md")
    (tmp_path / "deleted.py").unlink()
    for index in range(350):
        (tmp_path / f"doc-{index}.md").write_text("new documentation\n")
    git("add", "-A")
    git("commit", "-qm", "change")
    head = git("rev-parse", "HEAD")
    paths = policy.changed_paths(base, head, tmp_path)
    assert {"code.py", "README.md", "deleted.py", "doc-349.md"} <= paths
    assert len(paths) == 353
    assert policy.decide(_event(), "pull_request", MERGE, paths).lane == "full"


def test_actual_checkout_cannot_be_attested_as_a_different_revision() -> None:
    """Attestation checks Git instead of trusting a claimed output string."""
    decision = policy.decide({}, "workflow_dispatch", MERGE, None)
    with pytest.raises(ValueError, match="Stale checkout"):
        policy.verify_checkout(decision)


def test_workflow_wires_required_gate_and_separates_metadata_concurrency() -> None:
    """Selection logic must remain connected to real workflow execution."""
    source = (policy.ROOT / ".github/workflows/tests.yml").read_text()
    assert "paths:" not in source and "paths-ignore:" not in source
    for activity in ("opened", "reopened", "synchronize", "ready_for_review", "converted_to_draft", "edited"):
        assert activity in source
    assert "needs: [policy, full, feedback]\n    if: always()" in source
    assert "EPPM_TEST_NEEDS: ${{ toJSON(needs) }}" in source
    assert "needs.policy.outputs.context || 'tests'" in source
    assert "github.run_id" in source and "'metadata' || 'acceptance'" in source
    full = source.split("  full:\n", 1)[1].split("  tests:\n", 1)[0]
    feedback = source.split("  feedback:\n", 1)[1].split("  full:\n", 1)[0]
    assert "python -m scripts.run_tests full" in full
    assert full.index("scripts.run_tests full") < full.index("scripts.pr_test_policy attest")
    assert "--cov-fail-under" not in source  # The canonical runner owns this flag.
    assert "browser-tests" not in feedback and "docker " not in feedback
    assert "scripts.run_tests fast" in feedback
    assert "pull_request_target" not in source


def test_gate_cli_does_not_turn_bad_json_or_missing_outputs_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual command fails safely when job transport evidence is absent."""
    for evidence in ("", "{}", "[]", "not-json"):
        monkeypatch.setenv("EPPM_TEST_NEEDS", evidence)
        assert policy.main(["gate", "--sha", MERGE]) == 1


@pytest.mark.parametrize("changes", [None, {}, {"unknown": {}}, {"base": {}, "body": {}}])
def test_ambiguous_edits_cannot_claim_the_metadata_context(changes: object) -> None:
    """Only known title/body-only edits can suppress another expensive run."""
    event = _event(action="edited")
    event["changes"] = changes
    decision = policy.decide(event, "pull_request", MERGE, {"app/main.py"})
    assert decision.lane == "full" and decision.context == "tests"


@pytest.mark.parametrize("mutation", [
    {"draft": "false"}, {"draft": None}, {"base": {"ref": "other", "sha": BASE}},
    {"head": {"sha": "option-injection"}},
])
def test_malformed_event_state_fails_before_selecting_work(mutation: dict[str, object]) -> None:
    """Malformed identity/readiness data must fail closed at the boundary."""
    event = _event()
    event["pull_request"].update(mutation)
    with pytest.raises(ValueError):
        policy.decide(event, "pull_request", MERGE, {"README.md"})


@pytest.mark.parametrize("filename,content,kind,lane", [
    ("app.py", "# source change\n", "regular", "feedback"),
    ("README.md", "# Plain documentation\n", "regular", "docs"),
    ("README.md", "# Executable content\n", "executable", "full"),
    ("README.md", "#!/bin/sh\nexit 0\n", "regular", "full"),
    ("README.md", "binary\0content", "regular", "full"),
    ("README.md", "", "symlink", "full"),
    ("README.md", "", "invalid-utf8", "full"),
    ("README.md", "", "deleted-executable", "full"),
])
def test_policy_cli_uses_real_merge_parents_and_json_job_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    filename: str, content: str, kind: str, lane: str,
) -> None:
    """A real Git graph connects planning, identity receipts and the gate CLI."""
    def git(*arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=tmp_path, text=True,
                              capture_output=True, check=True).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_case.py").write_text("def test_case(): assert True\n")
    (tmp_path / "tests/suites.json").write_text(json.dumps({
        "version": 1, "fast": ["tests/test_case.py"], "extended": [],
    }))
    if kind == "deleted-executable":
        (tmp_path / "README.md").write_text("#!/bin/sh\n")
        (tmp_path / "README.md").chmod(0o755)
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-qb", "feature")
    source = tmp_path / filename
    if kind == "deleted-executable":
        source.unlink()
    elif kind == "invalid-utf8":
        source.write_bytes(b"\xff")
    elif kind == "symlink":
        source.symlink_to("tests/test_case.py")
    else:
        source.write_text(content)
    if kind == "executable":
        source.chmod(0o755)
    git("add", ".")
    git("commit", "-qm", "feature")
    head = git("rev-parse", "HEAD")
    git("checkout", "-qb", "merge", base)
    git("merge", "--no-ff", "-qm", "PR merge", "feature")
    merged = git("rev-parse", "HEAD")
    event = _event(True)
    event["pull_request"]["base"]["sha"] = base
    event["pull_request"]["head"]["sha"] = head
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps(event))
    output = tmp_path / "outputs"
    monkeypatch.setattr(policy, "ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert policy.main(["plan", "--event", str(payload), "--event-name", "pull_request", "--sha", merged]) == 0
    decision = policy.Decision.decode(output.read_text().splitlines()[0].split("=", 1)[1])
    assert decision.lane == lane
    monkeypatch.setenv("EPPM_TEST_DECISION", decision.encode())
    assert policy.main(["attest"]) == 0
    assert f"sha={merged}" in output.read_text()
    monkeypatch.setenv("EPPM_TEST_NEEDS", json.dumps(_needs(decision)))
    assert policy.main(["gate", "--sha", merged]) == (1 if lane == "feedback" else 0)
