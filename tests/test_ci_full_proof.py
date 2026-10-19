"""Exercise the actual metadata gate against bounded, isolated GitHub evidence.

Any is confined to mutable JSON fixtures used to model the external API boundary.
Every network operation is replaced; these tests need no GitHub credentials.
"""

from dataclasses import asdict, replace
from io import BytesIO
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from zipfile import ZipFile

import pytest

from scripts import ci_full_proof as proof
from scripts import pr_test_policy as policy


BASE, HEAD, MERGE = "a" * 40, "b" * 40, "c" * 40
FULL = policy.Decision("full", "ready-code", MERGE, HEAD, BASE, 6, False)
METADATA = replace(FULL, lane="metadata", reason="metadata-only")
ENV = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "300",
       "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKFLOW_SHA": MERGE,
       "GITHUB_WORKFLOW_REF": f"owner/repo/{proof.WORKFLOW}@refs/pull/6/merge"}


def _zip(value: dict[str, Any], filename: str) -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(filename, json.dumps(value))
    return stream.getvalue()


def _run(number: int, **changes: object) -> dict[str, Any]:
    return {"id": number, "run_number": number, "run_attempt": 1,
            "head_sha": HEAD, "workflow_id": 7, "path": proof.WORKFLOW,
            "event": "pull_request", "status": "completed", "conclusion": "success", **changes}


class FakeAPI(proof.GitHubAPI):
    """Supply only the external API boundary; real receipt/gate validation runs."""

    current: dict[str, Any]
    runs: list[dict[str, Any]]
    artifacts: dict[int, list[dict[str, Any]]]
    content: dict[int, bytes]
    jobs: dict[int, list[dict[str, Any]]]
    calls: list[str]

    def __init__(self) -> None:
        super().__init__("owner/repo", "unit-test-placeholder")
        self.current = {"state": "open", "merged": False, "draft": False,
                        "head": {"sha": HEAD}, "base": {"sha": BASE, "ref": "main"}, "merge_commit_sha": MERGE}
        self.runs = [_run(300), _run(200)]
        self.artifacts, self.content, self.jobs, self.calls = {}, {}, {}, []
        self.add(200, FULL)

    def add(self, number: int, decision: policy.Decision) -> None:
        """Create immutable plan/full fixtures associated with one run attempt."""
        self.artifacts[number] = []
        for index, kind in enumerate(("plan", "attest"), 1):
            identity = number * 10 + index
            receipt = proof.Receipt(1, kind, "owner/repo", number, 1,
                                    ENV["GITHUB_WORKFLOW_REF"], MERGE, decision)
            self.content[identity] = _zip(asdict(receipt), "plan.json" if kind == "plan" else "full.json")
            self.artifacts[number].append({"id": identity, "name": f"eppm-{kind}-{number}-1",
                                           "expired": False, "size_in_bytes": len(self.content[identity]),
                                           "digest": "sha256:" + hashlib.sha256(self.content[identity]).hexdigest()})
        self.jobs[number] = [{"id": number * 100 + index, "name": name, "status": "completed", "conclusion": result}
                             for index, (name, result) in enumerate({
                                 "policy": "success", "full suite and coverage": "success",
                                 "fast draft feedback": "skipped", "tests": "success",
                             }.items())]

    def json(self, path: str) -> dict[str, object]:
        self.calls.append(path)
        if path == "pulls/6":
            return self.current
        assert path == "actions/runs/300"
        return _run(300)

    def pages(self, path: str, member: str) -> list[dict[str, object]]:
        self.calls.append(path)
        if member == "workflow_runs":
            assert path == f"actions/workflows/7/runs?event=pull_request&head_sha={HEAD}"
            return self.runs
        number = int(path.split("/")[2])
        return self.artifacts[number] if member == "artifacts" else self.jobs[number]

    def archive(self, artifact_id: int) -> bytes:
        self.calls.append(f"artifact/{artifact_id}")
        return self.content[artifact_id]


def _needs() -> dict[str, object]:
    return {"policy": {"result": "success", "outputs": {"decision": METADATA.encode()}},
            "full": {"result": "skipped", "outputs": {}},
            "feedback": {"result": "skipped", "outputs": {}}}


def test_actual_metadata_cli_republishes_only_verified_exact_revision_full_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """The current metadata gate succeeds through its real proof/API call chain."""
    api = FakeAPI()
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("EPPM_TEST_NEEDS", json.dumps(_needs()))
    monkeypatch.setattr(policy, "verify_checkout", lambda decision, root: None)
    monkeypatch.setattr(proof, "GitHubAPI", lambda repository, token: api)
    caplog.set_level("INFO")
    assert policy.main(["gate", "--sha", MERGE]) == 0
    assert "Revalidated full acceptance from run 200 attempt 1" in caplog.text
    assert "tests: metadata" in caplog.text
    assert "actions/runs/200/attempts/1/jobs" in api.calls
    api.artifacts[200] = []
    assert policy.main(["gate", "--sha", MERGE]) == 1


@pytest.mark.parametrize("result", ["failure", "cancelled", "timed_out", "skipped", None])
def test_unsuccessful_latest_full_run_never_replays(result: str | None) -> None:
    api = FakeAPI()
    api.runs[1]["conclusion"] = result
    with pytest.raises(ValueError, match="pending or unsuccessful"):
        proof.verify_metadata(METADATA, ENV, api)


def test_pending_full_fails_promptly_then_the_same_metadata_gate_can_retry() -> None:
    api = FakeAPI()
    api.runs[1].update(status="in_progress", conclusion=None)
    with pytest.raises(ValueError, match="retry this gate after full success"):
        proof.verify_metadata(METADATA, ENV, api)
    api.runs[1].update(status="completed", conclusion="success")
    proof.verify_metadata(METADATA, ENV, api)


def test_newer_failed_acceptance_prevents_fallback_to_an_older_pass() -> None:
    api = FakeAPI()
    api.runs.insert(1, _run(275, conclusion="failure"))
    api.add(275, FULL)
    with pytest.raises(ValueError, match="unsuccessful"):
        proof.verify_metadata(METADATA, ENV, api)
    assert "artifact/2002" not in api.calls


def test_prior_metadata_runs_are_ignored_without_becoming_acceptance_proof() -> None:
    api = FakeAPI()
    api.runs.insert(1, _run(250))
    api.add(250, METADATA)
    proof.verify_metadata(METADATA, ENV, api)
    assert "artifact/2502" not in api.calls


@pytest.mark.parametrize("field,value", [
    ("head_sha", "d" * 40), ("base_sha", "d" * 40),
    ("tested_sha", "d" * 40), ("draft", True), ("pr_number", 7),
])
def test_full_proof_cannot_cross_revision_or_readiness(field: str, value: object) -> None:
    api = FakeAPI()
    api.add(200, replace(FULL, **{field: value}))
    with pytest.raises(ValueError):
        proof.verify_metadata(METADATA, ENV, api)


@pytest.mark.parametrize("field,value", [
    ("merge_commit_sha", "d" * 40), ("draft", True), ("state", "closed"),
    ("merged", True), ("head", {"sha": "d" * 40}), ("base", {"sha": "d" * 40}),
    ("base", {"sha": BASE, "ref": "other"}),
])
def test_live_pr_must_still_match_the_metadata_revision(field: str, value: object) -> None:
    api = FakeAPI()
    api.current[field] = value
    with pytest.raises(ValueError, match="Live PR"):
        proof.verify_metadata(METADATA, ENV, api)


@pytest.mark.parametrize("lane", ["docs", "feedback", "manual"])
def test_partial_or_manual_results_cannot_supply_code_full_proof(lane: str) -> None:
    api = FakeAPI()
    if lane == "manual":
        candidate = policy.Decision("manual", "manual-full", MERGE, HEAD, "", 0, False)
    else:
        candidate = replace(FULL, lane=lane, draft=lane == "feedback")
    api.add(200, candidate)
    with pytest.raises(ValueError):
        proof.verify_metadata(METADATA, ENV, api)


@pytest.mark.parametrize("change", ["expired", "missing", "duplicate", "size", "attempt", "corrupt", "filename", "schema", "source", "digest"])
def test_unusable_full_artifact_never_qualifies(change: str) -> None:
    api = FakeAPI()
    artifact = api.artifacts[200][1]
    if change == "expired":
        artifact["expired"] = True
    elif change == "missing":
        api.artifacts[200].pop()
    elif change == "duplicate":
        api.artifacts[200].append(dict(artifact))
    elif change == "size":
        artifact["size_in_bytes"] = proof.MAX_ARCHIVE + 1
    elif change == "attempt":
        api.runs[1]["run_attempt"] = 2
    elif change == "corrupt":
        api.content[2002] = b"invalid zip"
    else:
        receipt = asdict(proof.Receipt(1, "attest", "owner/repo", 200, 1,
                                       ENV["GITHUB_WORKFLOW_REF"], MERGE, FULL))
        if change == "schema":
            receipt["version"] = True
        if change == "source":
            receipt["workflow_sha"] = "d" * 40
        api.content[2002] = _zip(receipt, "../full.json" if change == "filename" else "full.json")
    artifact["digest"] = "sha256:" + hashlib.sha256(api.content[2002]).hexdigest()
    if change == "digest":
        artifact["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        proof.verify_metadata(METADATA, ENV, api)


@pytest.mark.parametrize("job,result", [("policy", "failure"), ("full suite and coverage", "skipped"),
                                        ("tests", "failure"), ("fast draft feedback", "success")])
def test_full_job_graph_must_be_complete_and_successful(job: str, result: str) -> None:
    api = FakeAPI()
    for record in api.jobs[200]:
        if record["name"] == job:
            record["conclusion"] = result
    with pytest.raises(ValueError, match="job graph"):
        proof.verify_metadata(METADATA, ENV, api)


def test_pagination_cannot_hide_later_records_or_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    api = proof.GitHubAPI("owner/repo", "unit-test-placeholder")
    monkeypatch.setattr(api, "json", lambda path: {"total_count": 2, "jobs": [{"id": 1 if "&page=1" in path else 2}]})
    assert api.pages("jobs", "jobs") == [{"id": 1}, {"id": 2}]
    monkeypatch.setattr(api, "json", lambda path: {"total_count": 2, "jobs": [{"id": 1}]})
    with pytest.raises(ValueError, match="Duplicated"):
        api.pages("jobs", "jobs")
    monkeypatch.setattr(api, "json", lambda path: {"total_count": 1001, "jobs": []})
    with pytest.raises(ValueError, match="complete list"):
        api.pages("jobs", "jobs")


def test_signed_artifact_downloads_never_receive_api_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fetch(url: str, headers: dict[str, str], limit: int, timeout: float) -> tuple[bytes, str | None]:
        calls.append((url, dict(headers)))
        return (b"", "https://artifact.example.invalid/signed") if len(calls) == 1 else (b"ZIP", None)

    monkeypatch.setattr(proof, "_fetch", fetch)
    assert proof.GitHubAPI("owner/repo", "unit-test-placeholder").archive(9) == b"ZIP"
    assert "Authorization" in calls[0][1] and not calls[1][1]


def test_network_proof_has_a_total_read_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proof, "monotonic", lambda: 0)
    api = proof.GitHubAPI("owner/repo", "unit-test-placeholder")
    monkeypatch.setattr(proof, "monotonic", lambda: 31)
    with pytest.raises(ValueError, match="read budget expired"):
        api.json("actions/runs/1")


def test_transport_rejects_http_and_redacts_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        proof._fetch("http://example.invalid", {}, 10)

    class Unavailable:
        def open(self, request: object, timeout: int) -> None:
            raise URLError("sensitive-signed-query")

    monkeypatch.setattr(proof, "build_opener", lambda handler: Unavailable())
    with pytest.raises(ValueError, match="unavailable") as error:
        proof._fetch("https://example.invalid", {}, 10)
    assert "sensitive-signed-query" not in str(error.value)


def test_record_contains_only_public_identity_and_refuses_stale_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    proof.record(path, "plan", METADATA, {**ENV, "GH_TOKEN": "sensitive-placeholder"})
    assert "sensitive-placeholder" not in path.read_text()
    with pytest.raises(FileExistsError):
        proof.record(path, "plan", METADATA, ENV)


def test_missing_policy_or_job_proof_cannot_fall_back_to_an_older_pass() -> None:
    api = FakeAPI()
    api.runs.insert(1, _run(275))
    api.add(275, FULL)
    api.artifacts[275] = []
    with pytest.raises(ValueError, match="Missing"):
        proof.verify_metadata(METADATA, ENV, api)
    api.add(275, FULL)
    api.jobs[275].pop()
    with pytest.raises(ValueError, match="job graph"):
        proof.verify_metadata(METADATA, ENV, api)


def test_archive_cannot_hide_extra_or_oversized_receipt_members() -> None:
    stream = BytesIO()
    with ZipFile(stream, "w") as zipped:
        zipped.writestr("full.json", "{}")
        zipped.writestr("extra.json", "{}")
    with pytest.raises(ValueError, match="Ambiguous"):
        proof._decode(stream.getvalue(), "full.json", METADATA)
    stream = BytesIO()
    with ZipFile(stream, "w") as zipped:
        zipped.writestr("full.json", " " * (proof.MAX_RECEIPT + 1))
    with pytest.raises(ValueError, match="Oversized"):
        proof._decode(stream.getvalue(), "full.json", METADATA)
