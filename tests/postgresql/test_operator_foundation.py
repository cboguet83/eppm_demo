"""Safe local credential creation and explicit role provisioning."""

from pathlib import Path

from dotenv import dotenv_values
import pytest

from scripts.configure_postgresql import configure
from scripts.postgresql_admin import provision_runtime


def test_local_configuration_has_distinct_roles_and_refuses_overwrite(tmp_path: Path):
    destination = tmp_path / ".local" / "postgresql.env"
    configure(destination)
    settings = dotenv_values(destination)
    assert len(settings["POSTGRES_PASSWORD"]) >= 32
    assert settings["POSTGRES_PASSWORD"] != settings["EPPM_RUNTIME_PASSWORD"]
    assert len(bytes.fromhex(settings["DATABASE_CONTEXT_KEY"])) == 32
    assert settings["DATABASE_CONTEXT_KEY"] not in {settings["POSTGRES_PASSWORD"], settings["EPPM_RUNTIME_PASSWORD"]}
    assert "eppm_app:" in settings["DATABASE_URL"]
    assert "eppm_operator:" in settings["DATABASE_OPERATOR_URL"]
    with pytest.raises(FileExistsError):
        configure(destination)
    assert settings == dotenv_values(destination)
    with pytest.raises(ValueError):
        configure(tmp_path / ".env.example")


def test_operator_provisioning_is_idempotent_and_rejects_weak_passwords(pg_database):
    provision_runtime(pg_database.operator_url, "unused-on-existing-role-" * 2)
    provision_runtime(pg_database.operator_url, "unused-on-existing-role-" * 2)
    with pytest.raises(ValueError, match="separate random runtime password"):
        provision_runtime(pg_database.operator_url, "short")
