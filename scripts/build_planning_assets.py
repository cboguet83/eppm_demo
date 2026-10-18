"""Assemble one planning browser source for three independent hosts."""

import argparse
import gzip
import hashlib
import io
import json
import logging
from pathlib import Path
import tarfile
import tomllib
from typing import cast

LOGGER = logging.getLogger(__name__)
MANIFEST = "manifest.json"
TARGETS = {
    "eppm": "app/presentation/assets/components/gantt/planning-view",
    "streamlit": (
        "packages/streamlit-planning-view/src/streamlit_planning_view/frontend"
    ),
}


class AssetError(ValueError):
    """Indicate missing, stale, or inconsistent prepared browser resources."""


def source_files(root: Path) -> dict[str, bytes]:
    """Read the canonical browser source and deterministic version manifest.

    Args:
        root: Repository or source-distribution root.

    Returns:
        Relative asset names mapped to their complete bytes.

    Raises:
        AssetError: Required sources or matching package versions are missing.
    """
    source = root / "packages/planning-view"
    required = ["src/index.js", "src/adapters/streamlit.js",
                "src/workspace/styles.css", "package.json", "streamlit.html",
                "README.md"]
    if any(not (source / name).is_file() for name in required):
        raise AssetError("Canonical planning browser sources are missing.")
    with _safe_path(source, "package.json").open(encoding="utf-8") as stream:
        metadata = json.load(stream)
    version = metadata["version"]
    wrapper_path = _safe_path(
        root, "packages/streamlit-planning-view/pyproject.toml",
    )
    with wrapper_path.open(
        "rb",
    ) as stream:
        wrapper = tomllib.load(stream)
    if version != wrapper["project"]["version"]:
        raise AssetError("Browser and Python planning versions disagree.")
    names = sorted(
        path.relative_to(source).as_posix()
        for path in (source / "src").rglob("*")
        if path.is_file() and path.suffix in (".js", ".css")
    )
    files: dict[str, bytes] = {}
    for name in [*names, "package.json", "README.md", "streamlit.html"]:
        path = _safe_path(source, name)
        with path.open("rb") as stream:
            files[name] = stream.read()
    files["index.html"] = files["streamlit.html"]
    with _safe_path(root, "LICENSE").open("rb") as stream:
        files["LICENSE"] = stream.read()
    manifest = {
        "packageName": "planning-view", "packageVersion": version,
        "contractVersion": 1,
        "files": {name: hashlib.sha256(data).hexdigest()
                  for name, data in sorted(files.items())},
    }
    files[MANIFEST] = (
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    ).encode()
    return files


def _existing(directory: Path) -> set[str]:
    return {path.relative_to(directory).as_posix()
            for path in directory.rglob("*") if path.is_file()}


def _safe_path(directory: Path, name: str) -> Path:
    path = directory / name
    if (path.is_symlink()
            or not path.resolve().is_relative_to(directory.resolve())):
        raise AssetError("Invalid planning asset path.")
    return path


def _prepare(directory: Path, files: dict[str, bytes]) -> None:
    if directory.is_symlink():
        raise AssetError("Generated asset directory cannot be a symlink.")
    existing = _existing(directory)
    if existing:
        manifest_path = _safe_path(directory, MANIFEST)
        if not manifest_path.is_file():
            raise AssetError("Refusing to replace unmanaged asset contents.")
        with manifest_path.open(encoding="utf-8") as stream:
            previous = json.load(stream)
        if (not isinstance(previous, dict)
                or not isinstance(previous.get("files"), dict)):
            raise AssetError("Invalid generated planning asset manifest.")
        known = set(previous.get("files", {})) | {MANIFEST}
        if previous.get("packageName") != "planning-view" or existing - known:
            raise AssetError("Generated asset directory has unmanaged files.")
        for name in known - files.keys():
            candidate = _safe_path(directory, name)
            if candidate.is_file():
                candidate.unlink()
    for name, data in files.items():
        path = _safe_path(directory, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.write(data)


def check_assets(root: Path, targets: tuple[str, ...] = ()) -> None:
    """Fail when prepared hosts differ from the canonical source/version.

    Args:
        root: Source root.
        targets: Selected host targets; empty means both hosts.

    Raises:
        AssetError: A resource is missing, extra, or stale.
    """
    files = source_files(root)
    for target in targets or tuple(TARGETS):
        if target not in TARGETS:
            raise AssetError("Unknown planning asset target.")
        directory = root / TARGETS[target]
        if directory.is_symlink():
            raise AssetError("Prepared asset directory cannot be a symlink.")
        if _existing(directory) != files.keys():
            raise AssetError(f"Missing/unexpected planning assets: {target}")
        for name, expected in files.items():
            with _safe_path(directory, name).open("rb") as stream:
                if stream.read() != expected:
                    raise AssetError(f"Stale planning asset: {target}/{name}")


def browser_archive(files: dict[str, bytes], destination: Path) -> None:
    """Write a deterministic browser archive with stable names and metadata.

    Args:
        files: Canonical assembled assets.
        destination: Requested output archive path.
    """
    metadata = json.loads(files[MANIFEST])
    prefix = "planning-view-" + metadata["packageVersion"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        with gzip.GzipFile(
            fileobj=output, mode="wb", filename="", mtime=0,
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, data in sorted(files.items()):
                    info = tarfile.TarInfo(prefix + "/" + name)
                    info.size = len(data)
                    info.mode = 0o644
                    with io.BytesIO(data) as content:
                        archive.addfile(info, content)


def prepare_assets(
    root: Path, targets: tuple[str, ...] = (), archive: Path | None = None,
) -> None:
    """Prepare selected host asset trees from one browser implementation.

    Args:
        root: Repository root.
        targets: Host targets, or both by default.
        archive: Optional deterministic browser artifact path.

    Raises:
        AssetError: Source metadata or an existing target is inconsistent.
    """
    files = source_files(root)
    for target in targets or tuple(TARGETS):
        if target not in TARGETS:
            raise AssetError("Unknown planning asset target.")
        _prepare(root / TARGETS[target], files)
    if archive is not None:
        browser_archive(files, archive)


def main() -> None:
    """Run explicit assembly or read-only asset verification from the CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--target", choices=tuple(TARGETS), action="append")
    parser.add_argument("--browser-archive", type=Path)
    args = parser.parse_args()
    if args.check and args.browser_archive:
        parser.error("--check cannot write a browser archive")
    root = Path(__file__).resolve().parents[1]
    targets = tuple(cast(list[str], args.target or []))
    try:
        if args.check:
            check_assets(root, targets)
        else:
            prepare_assets(root, targets, args.browser_archive)
    except (AssetError, FileNotFoundError) as exc:
        parser.exit(1, f"Planning asset preparation failed: {exc}\n")
    LOGGER.info("Planning browser assets verified" if args.check else
                "Planning browser assets prepared")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
