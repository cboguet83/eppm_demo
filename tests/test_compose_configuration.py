"""Validate optional tooling and isolated database configuration without startup."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts.configure_local_oidc import local_environment


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = "docker-compose.postgresql.yml"
TOOLS = "docker-compose.pgadmin.yml"


def _configuration(
    tmp_path: Path, files: list[str], *, tools: bool = False,
    credentials: bool = False, project: str = "compose-contract",
) -> subprocess.CompletedProcess[str]:
    """Resolve Compose using dummy configuration without inherited credentials."""
    empty = tmp_path / "empty.env"
    empty.touch()
    environment = {
        key: value for key, value in os.environ.items()
        if key in {"PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR"}
    }
    environment.update(local_environment())
    environment.update({
        "POSTGRES_PASSWORD": "configuration-only-placeholder",
        "DATABASE_URL": "postgresql://unused@postgres/eppm",
        "DATABASE_CONTEXT_KEY": "configuration-only-placeholder",
    })
    if credentials:
        environment.update(PGADMIN_EMAIL="operator@example.invalid",
                           PGADMIN_PASSWORD="configuration-only-placeholder")
    command = ["docker", "compose", "--project-name", project,
               "--env-file", str(empty)]
    for filename in files:
        command.extend(["-f", filename])
    if tools:
        command.extend(["--profile", "tools"])
    return subprocess.run(
        [*command, "config", "--format", "json"], cwd=ROOT,
        env=environment, capture_output=True, text=True, timeout=30, check=False,
    )


@pytest.mark.parametrize("files,port", [
    ([POSTGRES], "5434"),
    ([POSTGRES, "docker-compose.postgresql-test.yml"], "15432"),
    (["docker-compose.yml", POSTGRES, "docker-compose.oidc.yml"], "5434"),
])
def test_database_startup_needs_no_optional_tools_credentials(
    tmp_path: Path, files: list[str], port: str,
) -> None:
    """Test/app configuration resolves and publishes exactly its intended port."""
    result = _configuration(tmp_path, files)
    assert result.returncode == 0, "Compose configuration did not resolve"
    config = json.loads(result.stdout)
    assert "pgadmin" not in config["services"]
    postgres = config["services"]["postgres"]
    assert [(p["host_ip"], p["published"]) for p in postgres["ports"]] == [
        ("127.0.0.1", port),
    ]
    assert postgres["volumes"][0]["source"] == "postgresql-data"
    assert config["volumes"]["postgresql-data"]["name"] == (
        "compose-contract_postgresql-data"
    )


def test_tools_require_credentials_only_when_overlay_is_selected(tmp_path: Path) -> None:
    """Opting into tools cannot fall back to a public/default password."""
    result = _configuration(tmp_path, [POSTGRES, TOOLS], tools=True)
    assert result.returncode != 0
    assert "PGADMIN_EMAIL" in result.stderr or "PGADMIN_PASSWORD" in result.stderr


def test_tools_volume_and_names_are_scoped_to_the_explicit_project(tmp_path: Path) -> None:
    """Two project configurations keep tool data and container names independent."""
    for project in ("compose-first", "compose-second"):
        result = _configuration(
            tmp_path, [POSTGRES, TOOLS], tools=True,
            credentials=True, project=project,
        )
        assert result.returncode == 0, "Tools configuration did not resolve"
        config = json.loads(result.stdout)
        tool = config["services"]["pgadmin"]
        assert "container_name" not in tool
        assert tool["image"] == "dpage/pgadmin4:9.18"
        assert tool["ports"][0]["published"] == "5050"
        assert tool["ports"][0]["host_ip"] == "127.0.0.1"
        assert tool["volumes"][0]["source"] == "pgadmin_data"
        assert config["volumes"]["pgadmin_data"]["name"] == project + "_pgadmin_data"
