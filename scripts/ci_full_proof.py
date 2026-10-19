"""Revalidate immutable full-run proof for a metadata-only PR update.

Only GitHub-hosted, same-workflow PR acceptance can qualify. Network access is
read-only; signed download URLs and authorization are never recorded or logged.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from http.client import HTTPMessage
import hashlib
from io import BytesIO
import json
import logging
from pathlib import Path
import re
from time import monotonic
from typing import TYPE_CHECKING, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile

if TYPE_CHECKING:
    from scripts.pr_test_policy import Decision


LOGGER = logging.getLogger(__name__)
API = "https://api.github.com"
WORKFLOW = ".github/workflows/tests.yml"
SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
MAX_ARCHIVE = 65536
MAX_RECEIPT = 8192


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Malformed GitHub proof object.")
    return cast(dict[str, object], value)


def _integer(value: object, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("Malformed GitHub proof counter.")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Malformed GitHub proof string.")
    return value


class _NoRedirect(HTTPRedirectHandler):
    """Keep API authorization out of every redirected download request."""

    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str,
        headers: HTTPMessage, newurl: str,
    ) -> None:
        """Return control to the bounded, explicit HTTPS redirect loop."""
        return None


def _fetch(
    url: str, headers: dict[str, str], limit: int, timeout: float = 20,
) -> tuple[bytes, str | None]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Proof transport requires HTTPS without embedded credentials.")
    try:
        with build_opener(_NoRedirect()).open(Request(url, headers=headers), timeout=timeout) as response:
            content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError("GitHub proof response exceeds its size limit.")
        return content, None
    except HTTPError as error:
        with error:
            if error.code in {301, 302, 303, 307, 308}:
                return b"", error.headers.get("Location") or "invalid-redirect"
        raise ValueError("GitHub proof request failed; retry the metadata gate.") from None
    except (URLError, OSError, TimeoutError):
        raise ValueError("GitHub proof transport unavailable; retry the metadata gate.") from None


class GitHubAPI:
    """Read bounded GitHub JSON and artifacts with an isolated authorization scope.

    Args:
        repository: Validated owner/repository identity.
        token: Actions read token, held only in memory.
    """

    repository: str
    _headers: dict[str, str]
    _deadline: float

    def __init__(self, repository: str, token: str) -> None:
        if not REPOSITORY.fullmatch(repository) or not token.strip():
            raise ValueError("Metadata full proof requires repository and Actions read access.")
        self.repository = repository
        self._deadline = monotonic() + 30
        self._headers = {"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"}

    def _read(self, url: str, headers: dict[str, str], limit: int) -> tuple[bytes, str | None]:
        remaining = self._deadline - monotonic()
        if remaining <= 0:
            raise ValueError("Full proof read budget expired; retry the metadata gate.")
        return _fetch(url, headers, limit, min(20, remaining))

    def json(self, path: str) -> dict[str, object]:
        """Read a repository-relative JSON endpoint, rejecting redirects/errors.

        Args:
            path: Internally constructed repository API path.

        Returns:
            Validated JSON object.

        Raises:
            ValueError: Transport, size or schema validation failed.
        """
        content, redirect = self._read(f"{API}/repos/{self.repository}/{path}", self._headers, 4_194_304)
        if redirect is not None:
            raise ValueError("Unexpected GitHub JSON redirect.")
        return _mapping(json.loads(content))

    def pages(self, path: str, member: str) -> list[dict[str, object]]:
        """Read complete paginated records; an incomplete/ambiguous list fails.

        Args:
            path: Repository API collection path.
            member: JSON member containing the requested records.

        Returns:
            Complete records with unique GitHub identities.

        Raises:
            ValueError: Records are missing, duplicated or exceed safe limits.
        """
        records: list[dict[str, object]] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 11):
            response = self.json(f"{path}{separator}per_page=100&page={page}")
            total = _integer(response.get("total_count"), 0)
            batch = response.get(member)
            if not isinstance(batch, list) or total > 1000 or len(batch) > 100:
                raise ValueError("GitHub proof pagination cannot establish a complete list.")
            records.extend(_mapping(item) for item in batch)
            if len(records) == total:
                identities = [_integer(item.get("id")) for item in records]
                if len(set(identities)) != len(identities):
                    raise ValueError("Duplicated GitHub proof pagination records.")
                return records
            if not batch or len(records) > total:
                break
        raise ValueError("Incomplete GitHub proof pagination.")

    def archive(self, artifact_id: int) -> bytes:
        """Download an artifact without forwarding API authorization on redirects.

        Args:
            artifact_id: Positive GitHub artifact identity.

        Returns:
            Bounded archive bytes for validation without filesystem extraction.

        Raises:
            ValueError: Download access, redirects or resource limits failed.
        """
        url = f"{API}/repos/{self.repository}/actions/artifacts/{_integer(artifact_id)}/zip"
        content, redirect = self._read(url, self._headers, MAX_ARCHIVE)
        for _ in range(3):
            if redirect is None:
                return content
            content, redirect = self._read(redirect, {}, MAX_ARCHIVE)
        if redirect is not None:
            raise ValueError("Too many GitHub artifact redirects.")
        return content


@dataclass(frozen=True)
class Receipt:
    """Versioned, secret-free run identity and the already validated decision."""

    version: int
    kind: str
    repository: str
    run_id: int
    run_attempt: int
    workflow_ref: str
    workflow_sha: str
    decision: Decision


def _context(decision: Decision, environment: Mapping[str, str], kind: str) -> Receipt:
    repository = environment.get("GITHUB_REPOSITORY", "")
    workflow_ref = environment.get("GITHUB_WORKFLOW_REF", "")
    workflow_sha = environment.get("GITHUB_WORKFLOW_SHA", "")
    if (not REPOSITORY.fullmatch(repository) or not SHA.fullmatch(workflow_sha)
            or not workflow_ref.startswith(f"{repository}/{WORKFLOW}@")):
        raise ValueError("Missing or invalid workflow proof identity.")
    return Receipt(1, kind, repository,
                   _integer(int(environment.get("GITHUB_RUN_ID", "0"))),
                   _integer(int(environment.get("GITHUB_RUN_ATTEMPT", "0"))),
                   workflow_ref, workflow_sha, decision)


def record(path: Path, kind: str, decision: Decision, environment: Mapping[str, str]) -> None:
    """Exclusively write a bounded receipt containing only approved public fields.

    Args:
        path: Explicit proof filename uploaded by this workflow step.
        kind: Policy plan or post-execution attestation.
        decision: Validated selection and source identities.
        environment: GitHub-provided execution context; secrets are never copied.

    Raises:
        ValueError: Execution identity or proof kind is invalid.
        OSError: A fresh proof file cannot be created.
    """
    if kind not in {"plan", "attest"}:
        raise ValueError("Unsupported CI proof kind.")
    receipt = _context(decision, environment, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(asdict(receipt), stream, sort_keys=True)


def _decode(archive: bytes, filename: str, reference: Decision) -> Receipt:
    if len(archive) > MAX_ARCHIVE:
        raise ValueError("Oversized full proof archive.")
    try:
        with ZipFile(BytesIO(archive)) as zipped:
            members = zipped.infolist()
            if len(members) != 1 or members[0].filename != filename:
                raise ValueError("Ambiguous full proof archive.")
            if members[0].file_size > MAX_RECEIPT:
                raise ValueError("Oversized full proof receipt.")
            with zipped.open(members[0]) as stream:
                value = _mapping(json.loads(stream.read(MAX_RECEIPT + 1)))
    except (BadZipFile, RuntimeError, NotImplementedError):
        raise ValueError("Unreadable full proof archive.") from None
    if set(value) != set(Receipt.__dataclass_fields__) or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported full proof schema.")
    return Receipt(1, _string(value["kind"]), _string(value["repository"]),
                   _integer(value["run_id"]), _integer(value["run_attempt"]),
                   _string(value["workflow_ref"]), _string(value["workflow_sha"]),
                   reference.decode(json.dumps(value["decision"])))


def _load(
    api: GitHubAPI, artifacts: list[dict[str, object]], run: dict[str, object],
    reference: Decision, kind: str,
) -> Receipt:
    run_id, attempt = _integer(run.get("id")), _integer(run.get("run_attempt"))
    prefix = f"eppm-{kind}-{run_id}-"
    matching: dict[int, dict[str, object]] = {}
    for artifact in artifacts:
        name = _string(artifact.get("name"))
        suffix = name.removeprefix(prefix)
        if not name.startswith(prefix) or not suffix.isdecimal():
            continue
        number = _integer(int(suffix))
        if number in matching or number > attempt:
            raise ValueError("Ambiguous full proof attempt.")
        matching[number] = artifact
    selected = attempt if kind == "attest" else max(matching, default=0)
    artifact = matching.get(selected)
    if artifact is None or artifact.get("expired") is not False:
        raise ValueError("Missing or expired full proof; retry after fresh full acceptance.")
    if _integer(artifact.get("size_in_bytes"), 0) > MAX_ARCHIVE:
        raise ValueError("Oversized full proof artifact.")
    filename = "plan.json" if kind == "plan" else "full.json"
    archive = api.archive(_integer(artifact.get("id")))
    if artifact.get("digest") != "sha256:" + hashlib.sha256(archive).hexdigest():
        raise ValueError("Full proof artifact digest does not match GitHub metadata.")
    receipt = _decode(archive, filename, reference)
    if (receipt.kind != kind or receipt.run_id != run_id or receipt.run_attempt != selected
            or receipt.repository != api.repository or receipt.decision.head_sha != run.get("head_sha")):
        raise ValueError("Full proof does not match its GitHub run.")
    return receipt


def _live_pr(api: GitHubAPI, decision: Decision) -> None:
    current = api.json(f"pulls/{decision.pr_number}")
    if (current.get("state") != "open" or current.get("merged") is not False
            or current.get("draft") is not decision.draft
            or _mapping(current.get("head")).get("sha") != decision.head_sha
            or _mapping(current.get("base")).get("sha") != decision.base_sha
            or _mapping(current.get("base")).get("ref") != "main"
            or current.get("merge_commit_sha") != decision.tested_sha):
        raise ValueError("Live PR differs from this metadata revision.")


def _full_jobs(api: GitHubAPI, run: dict[str, object]) -> None:
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("Latest full acceptance is pending or unsuccessful; retry this gate after full success.")
    path = f"actions/runs/{_integer(run.get('id'))}/attempts/{_integer(run.get('run_attempt'))}/jobs"
    jobs = api.pages(path, "jobs")
    expected = {"policy": "success", "full suite and coverage": "success",
                "fast draft feedback": "skipped", "tests": "success"}
    actual = {_string(job.get("name")): job.get("conclusion") for job in jobs}
    if len(actual) != len(jobs) or actual != expected or any(job.get("status") != "completed" for job in jobs):
        raise ValueError("Full proof lacks the complete successful acceptance job graph.")


def _qualify(
    api: GitHubAPI, run: dict[str, object], artifacts: list[dict[str, object]],
    plan: Receipt, current: Receipt,
) -> None:
    if plan.decision.lane != "full":
        raise ValueError("Latest acceptance did not execute the full suite.")
    _full_jobs(api, run)
    accepted = _load(api, artifacts, run, current.decision, "attest")
    if (accepted.decision != plan.decision
            or accepted.workflow_ref != current.workflow_ref
            or accepted.workflow_sha != current.workflow_sha
            or plan.workflow_ref != accepted.workflow_ref or plan.workflow_sha != accepted.workflow_sha):
        raise ValueError("Metadata requires matching PR full proof from the same workflow source.")
    original, revision = accepted.decision, current.decision
    if (original.pr_number, original.head_sha, original.base_sha, original.tested_sha, original.draft) != (
        revision.pr_number, revision.head_sha, revision.base_sha, revision.tested_sha, revision.draft,
    ):
        raise ValueError("Full proof belongs to a different PR revision or readiness state.")
    LOGGER.info("Revalidated full acceptance from run %s attempt %s for this exact PR revision.",
                accepted.run_id, accepted.run_attempt)


def verify_metadata(
    decision: Decision, environment: Mapping[str, str], api: GitHubAPI | None = None,
) -> None:
    """Authorize metadata only from the latest exact-revision full PR acceptance.

    Args:
        decision: Current validated metadata selection.
        environment: GitHub run identity and read token.
        api: Optional read client for isolated boundary tests.

    Raises:
        ValueError: Complete current full proof cannot be established.
    """
    if decision.lane != "metadata":
        raise ValueError("Full proof replay is only for metadata updates.")
    current = _context(decision, environment, "plan")
    api = api or GitHubAPI(current.repository, environment.get("GH_TOKEN", ""))
    _live_pr(api, decision)
    execution = api.json(f"actions/runs/{current.run_id}")
    if (execution.get("event") != "pull_request" or execution.get("head_sha") != decision.head_sha
            or execution.get("path") != WORKFLOW or api.repository != current.repository):
        raise ValueError("Metadata run has an invalid workflow identity.")
    workflow = _integer(execution.get("workflow_id"))
    runs = api.pages(f"actions/workflows/{workflow}/runs?event=pull_request&head_sha={decision.head_sha}", "workflow_runs")
    numbers = [_integer(run.get("run_number")) for run in runs]
    if len(set(numbers)) != len(numbers):
        raise ValueError("Ambiguous full acceptance run ordering.")
    for run in sorted(runs, key=lambda item: _integer(item.get("run_number")), reverse=True):
        if run.get("id") == current.run_id:
            continue
        if (run.get("event") != "pull_request" or run.get("head_sha") != decision.head_sha
                or run.get("workflow_id") != workflow or run.get("path") != WORKFLOW):
            raise ValueError("Unexpected workflow in full acceptance history.")
        artifacts = api.pages(f"actions/runs/{_integer(run.get('id'))}/artifacts", "artifacts")
        plan = _load(api, artifacts, run, decision, "plan")
        if plan.decision.pr_number != decision.pr_number or plan.decision.lane == "metadata":
            continue
        _qualify(api, run, artifacts, plan, current)
        return
    raise ValueError("No exact-revision PR full proof; retry after full acceptance succeeds.")
