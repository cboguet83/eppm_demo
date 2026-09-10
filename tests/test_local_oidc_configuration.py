"""Local provisioning creates independent secrets and never overwrites existing ones."""

from pathlib import Path

import pytest

from app.shared.config.authentication import AuthenticationConfig
from scripts.configure_local_oidc import local_environment, provision


def test_streamlit_discovers_the_asgi_wrapper_instead_of_rendering_an_empty_launcher():
    from streamlit.web.server.app_discovery import discover_asgi_app

    result = discover_asgi_app(Path(__file__).resolve().parents[1] / "asgi_app.py")
    assert result.is_asgi_app
    assert result.import_string == "asgi_app:app"


def test_local_environment_uses_distinct_random_secrets_and_real_oidc():
    first, second = local_environment(), local_environment()
    names = [name for name in first if name.endswith(("SECRET", "PASSWORD"))]
    assert len(names) == 6
    assert len({first[name] for name in names}) == len(names)
    assert all(first[name] != second[name] and len(first[name]) >= 32 for name in names)
    settings = AuthenticationConfig.from_environment(first)
    assert settings.issuer == "http://localhost:8080/realms/eppm"
    assert settings.callback_url == "http://localhost:8501/auth/callback"
    assert not settings.secure_cookies


def test_isolated_local_environment_has_consistent_application_and_provider_ports():
    values = local_environment("http://localhost:8502", provider_port=8082)
    settings = AuthenticationConfig.from_environment(values)
    assert settings.callback_url == "http://localhost:8502/auth/callback"
    assert settings.issuer == "http://localhost:8082/realms/eppm"
    assert values["APP_LOCAL_PORT"] == "8502" and values["OIDC_LOCAL_PORT"] == "8082"


@pytest.mark.parametrize("origin,provider_port", [
    ("http://localhost", 8080), ("http://localhost:8080", 8080),
    ("http://localhost:8501", 80), ("http://localhost:8501", 65536),
    ("http://localhost:8501", True), ("https://localhost:8501", 8080),
    ("http://localhost:8501/path", 8080),
])
def test_local_compose_rejects_ambiguous_or_inconsistent_origins(origin, provider_port):
    with pytest.raises(ValueError):
        local_environment(origin, provider_port=provider_port)


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


@pytest.mark.parametrize("name,value,message", [
    ("OIDC_ISSUER", "https://provider.example.test:invalid/realm", "Invalid authentication URL"),
    ("APP_ORIGIN", "https://application.example.test:65536", "Invalid authentication URL"),
    ("OIDC_ISSUER", "https://[::1/realm", "Invalid authentication URL"),
    ("APP_ENV", "unrecognized", "Unknown application environment"),
])
def test_malformed_authentication_addresses_and_environments_fail_closed(name, value, message):
    values = local_environment()
    values[name] = value
    with pytest.raises(ValueError, match=message):
        AuthenticationConfig.from_environment(values)
