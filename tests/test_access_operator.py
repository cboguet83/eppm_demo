"""Deployment bootstrap cannot be reopened by revocation or business data resets."""

from contextlib import closing
import json
from pathlib import Path
import secrets
import time

from app.application.services.access import AccessService, AuthorizationPolicy, SessionLimits
from app.domain.access.models import ProjectScope, VerifiedIdentity
from app.infrastructure.database.connection import get_db
from app.infrastructure.repositories.access import SqliteAccessGateway
from scripts.access_admin import run


def test_operator_migration_inspection_bootstrap_and_recovery_are_targeted(tmp_path: Path, capsys):
    path = str(tmp_path / "operator.db")
    command = ["--database", path]
    assert run([*command, "migrate"]) == 0
    assert run([*command, "migrate"]) == 0
    assert run([*command, "bootstrap-admin", "--user-id", "1"]) == 1
    gateway = SqliteAccessGateway(path)
    now = int(time.time())
    service = AccessService(gateway, AuthorizationPolicy(lambda: now, SessionLimits()),
                           "https://issuer.example.test", lambda: secrets.token_urlsafe(32))
    cookie = service.sign_in(VerifiedIdentity(service.issuer, "verified", "test@example.test", "Test",
                                              now, now + 3600, True))
    user_id = service.actor(cookie).user_id
    assert run([*command, "pending-accounts"]) == 0
    assert [user["id"] for user in json.loads(capsys.readouterr().out)] == [user_id]
    assert run([*command, "bootstrap-admin", "--user-id", str(user_id)]) == 0
    with gateway.transaction() as store:
        assert [item["role"] for item in store.assignments(user_id)] == ["access_admin"]
        assert store.find_user(user_id)["status"] == "active"
    assert run([*command, "bootstrap-admin", "--user-id", str(user_id)]) == 1
    with gateway.transaction(write=True) as store:
        store.set_status(user_id, "disabled", now)
    assert run([*command, "recover-admin", "--user-id", str(user_id), "--reason", ""]) == 1
    assert run([*command, "recover-admin", "--user-id", str(user_id), "--reason", "Approved deployment recovery"]) == 0
    with gateway.transaction() as store:
        assert store.find_user(user_id)["status"] == "active"
        event = next(item for item in store.list_audit() if item["action"] == "access.recover")
        assert event["actor"].startswith("operator:")
        assert "Approved deployment recovery" in event["details_json"]


def test_any_administrator_grant_permanently_closes_initial_setup(tmp_path: Path):
    path = str(tmp_path / "setup.db")
    assert run(["--database", path, "migrate"]) == 0
    gateway = SqliteAccessGateway(path)
    with gateway.transaction(write=True) as store:
        user_id = store.register_user("https://issuer.example.test", "subject", "Test", 1000)
        grant = store.grant(user_id, "access_admin", ProjectScope("all"), 1000, "operator:test")
        store.revoke(grant)
    with gateway.transaction() as store:
        assert store.bootstrap_complete()


def test_operator_missing_unmigrated_or_broken_database_fails_safely(tmp_path: Path):
    path = str(tmp_path / "missing.db")
    assert run(["--database", path, "pending-accounts"]) == 1
    assert not Path(path).exists()
    with closing(get_db(path)):
        pass
    assert run(["--database", path, "pending-accounts"]) == 1
