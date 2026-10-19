"""Select PR feedback and reject incomplete or stale merge acceptance evidence."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import cast

from scripts.test_inventory import ROOT, load_inventory


LOGGER = logging.getLogger(__name__)
SHA = re.compile(r"[0-9a-f]{40}")
POLICY_PATHS = frozenset({
    "AGENTS.md", "pyproject.toml", "tests/conftest.py", "tests/suites.json",
    "docs/development-workflow.md", "tests/test_test_scheduling.py",
    "tests/test_local_test_runner.py", "tests/test_full_test_runner.py",
    "tests/test_pr_test_policy.py",
})


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Expected an object in CI evidence.")
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string in CI evidence.")
    return value


@dataclass(frozen=True)
class Decision:
    """Immutable lane and source identities, without credentials or PR prose."""

    lane: str
    reason: str
    tested_sha: str
    head_sha: str
    base_sha: str
    pr_number: int
    draft: bool

    def __post_init__(self) -> None:
        if self.lane not in {"docs", "feedback", "full", "metadata", "manual"}:
            raise ValueError("Unknown test lane.")
        for sha in (self.tested_sha, self.head_sha):
            if not SHA.fullmatch(sha):
                raise ValueError("Invalid CI revision identity.")
        if type(self.draft) is not bool or type(self.pr_number) is not int:
            raise ValueError("Invalid PR state.")
        if self.lane == "manual":
            if self.pr_number != 0 or self.base_sha or self.draft:
                raise ValueError("Manual diagnostics cannot claim a PR identity.")
        elif self.pr_number < 1 or not SHA.fullmatch(self.base_sha):
            raise ValueError("Missing PR/base identity.")
        if self.lane == "feedback" and not self.draft:
            raise ValueError("Ready code cannot select partial feedback.")

    @property
    def context(self) -> str:
        """Return the only permitted check name for this event's evidence."""
        return {"manual": "manual acceptance", "metadata": "metadata checks"}.get(
            self.lane, "tests",
        )

    def encode(self) -> str:
        """Serialize deterministic, one-line evidence for Actions job outputs."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        """Bind a job's identity receipt to this exact lane/head/base decision."""
        return hashlib.sha256(self.encode().encode()).hexdigest()

    @classmethod
    def decode(cls, source: str) -> "Decision":
        """Validate a JSON decision received across the Actions job boundary."""
        value = _mapping(json.loads(source))
        if set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Incomplete or unknown decision fields.")
        if type(value["draft"]) is not bool or type(value["pr_number"]) is not int:
            raise ValueError("Invalid PR state.")
        return cls(
            *[_string(value[name]) for name in
              ("lane", "reason", "tested_sha", "head_sha", "base_sha")],
            cast(int, value["pr_number"]), cast(bool, value["draft"]),
        )


def _prose(path: str) -> bool:
    if path in POLICY_PATHS:
        return False
    if path == "README.md":
        return True
    parts = PurePosixPath(path).parts
    if len(parts) == 3 and parts[:2] in {
        ("docs", "decisions"), ("docs", "implementation"),
    }:
        return path.endswith(".md")
    if len(parts) >= 4 and parts[:2] == ("openspec", "changes"):
        return path.endswith(".md") or parts[-1] == ".openspec.yaml"
    return False


def _policy_path(path: str) -> bool:
    return (path in POLICY_PATHS or path.startswith((".github/", "scripts/"))
            or path.startswith("tests/test_full_suite"))


def decide(
    event: dict[str, object], event_name: str, tested_sha: str,
    changed: set[str] | None,
) -> Decision:
    """Select work conservatively from complete paths and explicit PR readiness.

    Args:
        event: GitHub event payload, validated at this boundary.
        event_name: pull_request or workflow_dispatch.
        tested_sha: Exact checked-out PR merge revision or diagnostic revision.
        changed: Complete old/new changed paths; None means unavailable.

    Returns:
        Source-bound decision; uncertain diffs require full execution.

    Raises:
        ValueError: Event identities/state are invalid or unsupported.
    """
    if event_name == "workflow_dispatch":
        return Decision("manual", "manual-full", tested_sha, tested_sha, "", 0, False)
    if event_name != "pull_request":
        raise ValueError("Unsupported CI event.")
    pr = _mapping(event.get("pull_request"))
    head, base = _mapping(pr.get("head")), _mapping(pr.get("base"))
    number, draft = event.get("number"), pr.get("draft")
    if type(number) is not int or type(draft) is not bool or base.get("ref") != "main":
        raise ValueError("Invalid PR state or target branch.")
    action = event.get("action")
    if action not in {"opened", "reopened", "synchronize", "ready_for_review",
                       "converted_to_draft", "edited"}:
        raise ValueError("Unsupported PR activity.")
    if (action == "ready_for_review" and draft) or (action == "converted_to_draft" and not draft):
        raise ValueError("Conflicting readiness state.")
    changes = event.get("changes")
    if (action == "edited" and isinstance(changes, dict) and changes
            and set(changes) <= {"title", "body"}):
        lane, reason = "metadata", "metadata-only"
    else:
        lane, reason = _select_lane(changed, cast(bool, draft))
    return Decision(lane, reason, tested_sha, _string(head.get("sha")),
                    _string(base.get("sha")), cast(int, number), cast(bool, draft))


def _select_lane(changed: set[str] | None, draft: bool) -> tuple[str, str]:
    if not changed:
        return "full", "uncertain-diff"
    if any(_policy_path(path) for path in changed):
        return "full", "policy-change"
    if all(_prose(path) for path in changed):
        return "docs", "prose-only"
    return ("feedback", "draft-feedback") if draft else ("full", "ready-code")


def git(arguments: list[str], root: Path = ROOT) -> str:
    """Run a bounded read-only Git command without shell expansion."""
    result = subprocess.run(["git", *arguments], cwd=root, check=True,
                            capture_output=True, text=True, timeout=60)
    return result.stdout


def changed_paths(base: str, head: str, root: Path = ROOT) -> set[str]:
    """Read the complete NUL-delimited diff, retaining both sides of renames.

    Raises:
        ValueError: Revisions or diff records are malformed/ambiguous.
        subprocess.SubprocessError: History cannot establish the complete diff.
    """
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        raise ValueError("Invalid diff revisions.")
    records = git(["diff", "--name-status", "-z", "--find-renames", f"{base}...{head}"], root).split("\0")
    if records[-1] != "":
        raise ValueError("Incomplete Git diff.")
    paths: set[str] = set()
    index = 0
    while index < len(records) - 1:
        status = records[index]
        if not re.fullmatch(r"[AMDT]|[RC][0-9]+", status):
            raise ValueError("Unsupported or conflicted diff record.")
        count = 2 if status[0] in "RC" else 1
        end = index + 1 + count
        if end > len(records) - 1:
            raise ValueError("Truncated Git diff record.")
        for path in records[index + 1:end]:
            parts = PurePosixPath(path)
            if not path or parts.is_absolute() or ".." in parts.parts or str(parts) != path:
                raise ValueError("Invalid changed path.")
            paths.add(path)
        index = end
    return paths


def verify_checkout(decision: Decision, root: Path = ROOT) -> None:
    """Require receipts to describe the actual pinned checkout and PR parents."""
    if git(["rev-parse", "HEAD"], root).strip() != decision.tested_sha:
        raise ValueError("Stale checkout revision.")
    if decision.lane != "manual":
        parents = git(["show", "-s", "--format=%P", "HEAD"], root).split()
        if parents != [decision.base_sha, decision.head_sha]:
            raise ValueError("PR merge parents differ from event head/base.")


def plain_prose_diff(base: str, head: str, root: Path = ROOT) -> bool:
    """Verify both sides are plain UTF-8 blobs, never executable/link/script data.

    Args:
        base: Validated PR base revision.
        head: Validated PR head revision.
        root: Repository used for authoritative modes and blob contents.

    Returns:
        Whether every changed blob is nonexecutable plain document content.

    Raises:
        ValueError: Diff records or text encoding cannot be validated.
        subprocess.SubprocessError: Complete Git evidence is unavailable.
    """
    records = git(["diff", "--raw", "--no-abbrev", "-z", "--find-renames",
                   f"{base}...{head}"], root).split("\0")
    index = 0
    checked: set[str] = set()
    while index < len(records) - 1:
        fields = records[index].split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise ValueError("Malformed document diff evidence.")
        modes = (fields[0][1:], fields[1])
        if not all(_plain_blob(mode, blob, checked, root)
                   for mode, blob in zip(modes, fields[2:4], strict=True)):
            return False
        index += 3 if fields[4][0] in "RC" else 2
    return True


def _plain_blob(mode: str, blob: str, checked: set[str], root: Path) -> bool:
    if mode == "000000":
        return True
    if mode != "100644" or not SHA.fullmatch(blob):
        return False
    if blob in checked:
        return True
    content = git(["cat-file", "blob", blob], root)
    plain = "\0" not in content and not content.lstrip("\ufeff").startswith("#!")
    if plain:
        checked.add(blob)
    return plain


def accept(needs: dict[str, object], tested_sha: str) -> Decision:
    """Require every selected job, matching identity, and complete code acceptance.

    Raises:
        ValueError: Any expected result/proof is absent, unsuccessful, or stale.
    """
    if set(needs) != {"policy", "full", "feedback"}:
        raise ValueError("Incomplete CI job evidence.")
    policy = _mapping(needs["policy"])
    if policy.get("result") != "success":
        raise ValueError("PR policy did not succeed.")
    decision = Decision.decode(_string(_mapping(policy.get("outputs")).get("decision")))
    if decision.tested_sha != tested_sha:
        raise ValueError("Stale policy revision.")
    selected = {"full": "full", "manual": "full", "feedback": "feedback"}.get(decision.lane)
    for name in ("full", "feedback"):
        job = _mapping(needs[name])
        expected = "success" if name == selected else "skipped"
        if job.get("result") != expected:
            raise ValueError("A job result differs from the selected policy.")
        if name == selected:
            outputs = _mapping(job.get("outputs"))
            if outputs.get("sha") != tested_sha or outputs.get("decision_digest") != decision.digest:
                raise ValueError("Missing or stale execution identity receipt.")
    if decision.lane == "feedback":
        raise ValueError("Full acceptance deferred until the code PR is ready for review.")
    return decision


def _outputs(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as stream:
            for name, value in values.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("Invalid multiline job output.")
                stream.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    """Plan work, attest successful job identity, or evaluate the merge gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "attest", "gate"))
    parser.add_argument("--event", type=Path)
    parser.add_argument("--event-name")
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if arguments.operation == "plan":
            decision = _plan(arguments.event, arguments.event_name, arguments.sha)
            _outputs({"decision": decision.encode(), "lane": decision.lane,
                      "context": decision.context})
        elif arguments.operation == "attest":
            decision = Decision.decode(os.environ.get("EPPM_TEST_DECISION", ""))
            verify_checkout(decision, ROOT)
            _outputs({"sha": decision.tested_sha, "decision_digest": decision.digest})
        else:
            needs = _mapping(json.loads(os.environ.get("EPPM_TEST_NEEDS", "")))
            decision = accept(needs, arguments.sha)
        LOGGER.info("%s: %s (%s)", decision.context, decision.lane, decision.reason)
        return 0
    except ValueError as error:
        LOGGER.error("CI proof rejected: %s", error)
        return 1
    except (OSError, subprocess.SubprocessError):
        LOGGER.error("CI proof rejected; no complete current acceptance was established.")
        return 1


def _plan(event_path: Path | None, event_name: str, sha: str) -> Decision:
    if event_path is None:
        raise ValueError("Missing event payload.")
    with event_path.open(encoding="utf-8") as stream:
        event = _mapping(json.load(stream))
    load_inventory(ROOT)
    # Validate event identities before they become Git arguments.
    preliminary = decide(event, event_name, sha, None)
    verify_checkout(preliminary, ROOT)
    changed = None
    if event_name == "pull_request":
        try:
            changed = changed_paths(preliminary.base_sha, preliminary.head_sha, ROOT)
        except (ValueError, subprocess.SubprocessError):
            LOGGER.warning("Complete diff unavailable; requiring full acceptance.")
    decision = decide(event, event_name, sha, changed)
    if decision.lane == "docs":
        try:
            if plain_prose_diff(decision.base_sha, decision.head_sha, ROOT):
                return decision
        except (ValueError, subprocess.SubprocessError):
            LOGGER.warning("Plain document evidence unavailable; requiring full acceptance.")
        return decide(event, event_name, sha, None)
    return decision


if __name__ == "__main__":
    raise SystemExit(main())
