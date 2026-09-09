"""Local provisioning creates independent secrets and never overwrites existing ones."""

from pathlib import Path

import pytest

from app.shared.config.authentication import AuthenticationConfig
from scripts.configure_local_oidc import local_environment, provision


def test_local_environment_uses_distinct_random_secrets_and_real_oidc():
    first, second = local_environment(), local_environment()
    names = [name for name in first if name.endswith(("SECRET", "PASSWORD"))]
    assert len(names) == 6
    assert len({first[name] for name in names}) == len(names)
    assert all(first[name] != second[name] and len(first[name]) >= 32 for name in names)
    settings = AuthenticationConfig.from_environment(first)
    assert settings.issuer == "http://keycloak.localhost:8080/realms/eppm"
    assert settings.callback_url == "http://localhost:8501/auth/callback"
    assert not settings.secure_cookies


def test_local_provision_refuses_to_replace_existing_configuration(tmp_path: Path):
    destination = tmp_path / "private" / "oidc.env"
    provision(destination)
    initial = destination.read_bytes()
    with pytest.raises(FileExistsError):
        provision(destination)
    assert destination.read_bytes() == initial
    with pytest.raises(ValueError):
        provision(tmp_path / "unsafe.env", "http://public.example.test")
    assert not (tmp_path / "unsafe.env").exists()
