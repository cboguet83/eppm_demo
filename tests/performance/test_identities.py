"""A fifty-user workload must not silently reuse two accounts or grant admin roles."""

from copy import deepcopy

import pytest

from tests.performance.deployment import grant_accounts
from tests.performance.identities import LoadAccount, workload_accounts, workload_realm


def test_fifty_workload_slots_have_distinct_users_subjects_and_password_placeholders() -> None:
    template = {"realm": "eppm", "users": [{"username": "alex.admin", "id": "setup-user"}],
                "clients": [{"clientId": "eppm", "secret": "${OIDC_CLIENT_SECRET}"}]}
    original = deepcopy(template)
    accounts = workload_accounts(40, 10)
    realm = workload_realm(template, accounts)
    assert template == original
    assert len(accounts) == len({account.username for account in accounts}) == 50
    assert len({account.password_key for account in accounts}) == 50
    assert sum(account.role == "project_viewer" for account in accounts) == 40
    assert sum(account.role == "project_editor" for account in accounts) == 10
    assert len(realm["users"]) == len({user["id"] for user in realm["users"]}) == 51
    assert {user["username"] for user in realm["users"][1:]} == {account.username for account in accounts}
    assert {user["credentials"][0]["value"] for user in realm["users"][1:]} == {
        "${" + account.password_key + "}" for account in accounts}
    assert realm["clients"] == template["clients"]


@pytest.mark.parametrize("counts", [(1, 10), (40, 0), (40, 11), (True, 1), (2, True)])
def test_invalid_workload_counts_cannot_prepare_an_unrepresentative_realm(counts) -> None:
    with pytest.raises(ValueError):
        workload_accounts(*counts)


def test_duplicate_generated_or_existing_identity_is_rejected() -> None:
    account = LoadAccount(0, True)
    with pytest.raises(ValueError):
        workload_realm({"users": []}, (account, account))
    with pytest.raises(ValueError):
        workload_realm({"users": [{"username": account.username}]}, (account,))


@pytest.mark.parametrize("accounts", [[], [(1, "project_editor"), (1, "project_viewer")],
                                      [(0, "project_viewer")], [(1, "business_admin")]])
def test_duplicate_or_privileged_workload_accounts_are_rejected_before_operator_access(accounts) -> None:
    with pytest.raises(ValueError):
        grant_accounts(None, "postgresql", "unused", accounts)
