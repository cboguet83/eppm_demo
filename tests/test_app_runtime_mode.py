"""Runtime watcher profiles preserve authenticated startup and deployment settings."""

from pathlib import Path
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from app.shared.config.authentication import AuthenticationConfig
from scripts.configure_local_oidc import local_environment
from scripts.run_app import build_streamlit_command, resolve_file_watcher, run


@pytest.mark.parametrize("values,expected", [
    ({}, "none"),
    ({"APP_ENV": "development"}, "auto"),
    ({"APP_ENV": "staging"}, "none"),
    ({"APP_ENV": "production"}, "none"),
    ({"APP_ENV": "development", "APP_RUN_MODE": "auto"}, "auto"),
    ({"APP_ENV": "development", "APP_RUN_MODE": "demo"}, "none"),
    ({"APP_ENV": "development", "APP_RUN_MODE": "production"}, "none"),
    ({"APP_ENV": "production", "APP_RUN_MODE": "development"}, "auto"),
    ({"APP_RUN_MODE": " DEMO "}, "none"),
    ({"APP_ENV": "development", "APP_RUN_MODE": "", "APP_FILE_WATCHER_TYPE": " "}, "auto"),
])
def test_watching_defaults_follow_execution_mode(values, expected):
    before = values.copy()
    assert resolve_file_watcher(values) == expected
    assert values == before


@pytest.mark.parametrize("backend", ["auto", "none", "poll", "watchdog"])
@pytest.mark.parametrize("mode", ["development", "demo", "production"])
def test_explicit_watcher_override_takes_precedence(mode, backend):
    assert resolve_file_watcher({"APP_RUN_MODE": mode, "APP_FILE_WATCHER_TYPE": backend}) == backend


@pytest.mark.parametrize("values,field", [
    ({"APP_RUN_MODE": "unsupported-private-input"}, "APP_RUN_MODE"),
    ({"APP_ENV": "unsupported-private-input"}, "APP_ENV"),
    ({"APP_FILE_WATCHER_TYPE": "unsupported-private-input"}, "APP_FILE_WATCHER_TYPE"),
])
def test_invalid_runtime_settings_fail_with_a_safe_explanation(values, field):
    with pytest.raises(ValueError, match=field) as error:
        resolve_file_watcher(values)
    assert "unsupported-private-input" not in str(error.value)


def test_launcher_retains_authenticated_asgi_entrypoint_and_additional_cli_options():
    command = build_streamlit_command({"APP_RUN_MODE": "demo"}, ("--server.port=8502",))
    assert command[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert Path(command[4]) == Path(__file__).resolve().parents[1] / "asgi_app.py"
    assert command[5:] == ["--server.fileWatcherType=none", "--server.port=8502"]


def test_run_executes_without_a_shell_or_mutating_security_environment(monkeypatch):
    monkeypatch.setenv("APP_RUN_MODE", "demo")
    monkeypatch.delenv("APP_FILE_WATCHER_TYPE", raising=False)
    monkeypatch.setattr(sys, "argv", ["launcher", "--server.port=8502"])
    before = dict(os.environ)
    with patch("scripts.run_app.os.execv") as execute:
        assert run() == 0
    execute.assert_called_once_with(sys.executable, build_streamlit_command(before, ["--server.port=8502"]))
    assert dict(os.environ) == before


def test_invalid_configuration_does_not_start_streamlit(monkeypatch, capsys):
    monkeypatch.setenv("APP_RUN_MODE", "unsupported-private-input")
    with patch("scripts.run_app.os.execv") as execute:
        assert run([]) == 2
    execute.assert_not_called()
    assert "APP_RUN_MODE must be" in capsys.readouterr().err


def test_process_start_failure_is_safe(monkeypatch, capsys):
    monkeypatch.setenv("APP_RUN_MODE", "demo")
    monkeypatch.delenv("APP_FILE_WATCHER_TYPE", raising=False)
    with patch("scripts.run_app.os.execv", side_effect=PermissionError("private-command")):
        assert run([]) == 1
    message = capsys.readouterr().err
    assert "Unable to start Streamlit" in message and "private-command" not in message


def test_demo_mode_does_not_change_oidc_or_allow_insecure_production():
    values = local_environment()
    original = AuthenticationConfig.from_environment(values)
    values["APP_RUN_MODE"] = "demo"
    assert resolve_file_watcher(values) == "none"
    assert AuthenticationConfig.from_environment(values) == original
    values["APP_ENV"] = "production"
    with pytest.raises(ValueError, match="HTTP authentication is allowed only in local development"):
        AuthenticationConfig.from_environment(values)


def test_module_launcher_exposes_streamlit_help_without_initializing_business_data(tmp_path):
    database = tmp_path / "unopened.db"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.run_app", "--help"],
        env={**os.environ, "APP_RUN_MODE": "demo", "APP_FILE_WATCHER_TYPE": "",
             "DB_NAME": str(database), "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fileWatcherType" in result.stdout
    assert not database.exists()
