"""Validate frontend integrity without EPPM sources or Node."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tomllib


def validate_frontend(root: Path) -> None:
    """Validate versions, required resources and manifest checksums.

    Args:
        root: Standalone source-distribution root.

    Raises:
        ValueError: Assets are missing, stale, unsafe, or version-incompatible.
    """
    directory = root / "src/streamlit_planning_view/frontend"
    try:
        with (root / "pyproject.toml").open("rb") as stream:
            version = tomllib.load(stream)["project"]["version"]
        with (directory / "manifest.json").open(encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(
            "Prepared planning frontend is missing or invalid.",
        ) from exc
    if (not isinstance(manifest, dict)
            or manifest.get("packageName") != "planning-view"
            or manifest.get("packageVersion") != version
            or type(manifest.get("contractVersion")) is not int
            or manifest.get("contractVersion") != 1):
        raise ValueError("Prepared planning frontend version is incompatible.")
    files = manifest.get("files")
    required = {"index.html", "src/index.js", "src/adapters/streamlit.js",
                "src/workspace/styles.css"}
    if not isinstance(files, dict) or not required.issubset(files):
        raise ValueError("Prepared planning frontend is incomplete.")
    actual = {path.relative_to(directory).as_posix()
              for path in directory.rglob("*") if path.is_file()}
    if actual != set(files) | {"manifest.json"}:
        raise ValueError("Planning frontend resources are missing/unexpected.")
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise ValueError("Invalid planning frontend manifest entry.")
        relative = PurePosixPath(name)
        path = directory / name
        if (relative.is_absolute() or ".." in relative.parts
                or not path.resolve().is_relative_to(directory.resolve())
                or path.is_symlink()):
            raise ValueError("Invalid planning frontend asset path.")
        with path.open("rb") as stream:
            if hashlib.sha256(stream.read()).hexdigest() != expected:
                raise ValueError("Planning frontend checksum mismatch.")
