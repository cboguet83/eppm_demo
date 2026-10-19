"""Validate the explicit partial-suite inventory against repository discovery."""

import json
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def test_path(value: str, root: Path) -> str:
    """Return a normalized existing test path, rejecting traversal and options.

    Args:
        value: Repository-relative file/directory, optionally with a node ID.
        root: Repository root.

    Returns:
        Validated input with its optional node ID retained.

    Raises:
        ValueError: Input is outside tests, missing, or unsafe.
    """
    path = value.split("::", 1)[0]
    parts = PurePosixPath(path)
    if (not value or "\\" in value or parts.is_absolute()
            or ".." in parts.parts or parts.parts[:1] != ("tests",)
            or str(parts) != path):
        raise ValueError("Use existing repository-relative tests paths/node IDs.")
    target = root / path
    if not target.exists() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Use existing repository-relative tests paths/node IDs.")
    return value


def load_inventory(root: Path = ROOT) -> tuple[str, ...]:
    """Audit all test modules and return the selected fast modules.

    Args:
        root: Repository containing tests/suites.json.

    Returns:
        Ordered fast module paths.

    Raises:
        ValueError: The inventory is invalid, stale, or incomplete.
        OSError: An inventory/source file cannot be read.
    """
    with (root / "tests/suites.json").open(encoding="utf-8") as stream:
        inventory = json.load(stream)
    if (not isinstance(inventory, dict) or inventory.get("version") != 1
            or set(inventory) != {"version", "fast", "extended"}):
        raise ValueError("Invalid test inventory schema.")
    groups = [inventory.get(name) for name in ("fast", "extended")]
    if any(not isinstance(group, list) for group in groups):
        raise ValueError("Test inventory groups must be lists.")
    members = [entry for group in groups for entry in group]
    if not members or any(not isinstance(entry, str) for entry in members):
        raise ValueError("Test inventory members must be paths.")
    for entry in members:
        test_path(entry, root)
        if "::" in entry or not Path(entry).name.startswith("test_"):
            raise ValueError("Inventory entries must be complete test modules.")
    discovered = {path.relative_to(root).as_posix()
                  for path in (root / "tests").rglob("test_*.py")}
    if len(set(members)) != len(members) or set(members) != discovered:
        raise ValueError("Test inventory drift: classify every test module exactly once.")
    fast = inventory["fast"]
    if not fast:
        raise ValueError("The fast test selection cannot be empty.")
    return tuple(fast)
