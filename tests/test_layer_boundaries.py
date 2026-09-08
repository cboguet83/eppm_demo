"""Enforce dependency rules for migrated modules and explicit legacy bridges."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imports(path: Path) -> set[str]:
    """Collect static imports, including imports inside functions."""
    result: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"Use explicit layer imports in {path}"
            if node.module:
                result.add(node.module)
    return result


def test_domain_and_application_have_only_inward_dependencies() -> None:
    """Core logic cannot acquire a UI, storage, legacy, or configuration dependency."""
    for layer in ("domain", "application"):
        for path in (ROOT / "app" / layer).rglob("*.py"):
            for module in imports(path):
                if module.startswith("app."):
                    permitted = ("app.domain",) if layer == "domain" else ("app.domain", "app.application")
                    assert module.startswith(permitted), (path, module)
                else:
                    assert module.split(".")[0] in sys.stdlib_module_names - {"sqlite3", "tkinter"}, (path, module)


def test_migrated_presentation_cannot_open_storage_or_construct_repositories() -> None:
    """The legacy shell/i18n bridge are the only documented presentation exceptions."""
    for path in (ROOT / "app" / "presentation").rglob("*.py"):
        if path.name == "legacy_shell.py":
            continue
        for module in imports(path):
            if path.name == "i18n.py" and module == "src.i18n":
                continue
            assert not module.startswith(("src", "sqlite3", "app.infrastructure", "app.main", "app.shared")), (path, module)


def test_infrastructure_and_shared_do_not_depend_on_presentation() -> None:
    """External adapters cannot call screens; shared code stays independent."""
    for path in (ROOT / "app" / "infrastructure").rglob("*.py"):
        for module in imports(path):
            assert not module.startswith(("app.presentation", "app.main", "streamlit", "pandas")), (path, module)
            assert not module.startswith("src"), (path, module)
    for path in (ROOT / "app" / "shared").rglob("*.py"):
        for module in imports(path):
            assert module.startswith("app.shared") or module.split(".")[0] in sys.stdlib_module_names, (path, module)


def test_core_imports_work_without_installed_third_party_packages() -> None:
    """Package imports remain side-effect-free even without Streamlit or pandas."""
    result = subprocess.run([
        sys.executable, "-S", "-c",
        "import sys; import app.domain.projects.project_types; "
        "import app.application.services.project_types; import app.application.services.projects; "
        "import app.application.services.portfolio; import app.application.services.schema; "
        "import app.domain.projects.schema; import app.main; "
        "assert not {'streamlit', 'pandas', 'sqlite3', 'src'} & sys.modules.keys()",
    ], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
