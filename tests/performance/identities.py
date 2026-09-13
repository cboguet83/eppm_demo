"""Distinct fictional OIDC accounts for the offered reader/editor workload."""

from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class LoadAccount:
    """Describe a fictional user without retaining its password."""

    index: int
    editor: bool

    @property
    def username(self) -> str:
        """Return the same fictional login name for either comparison backend."""
        return f"load.{'editor' if self.editor else 'reader'}.{self.index:03d}"

    @property
    def password_key(self) -> str:
        """Name the deployment's independently generated private password."""
        return f"LOAD_{'EDITOR' if self.editor else 'READER'}_{self.index:03d}_PASSWORD"

    @property
    def role(self) -> str:
        """Grant only the business permission needed by this workload slot."""
        return "project_editor" if self.editor else "project_viewer"


def workload_accounts(readers: int, editors: int) -> tuple[LoadAccount, ...]:
    """Give each workload slot one separate identity on either backend."""
    if type(readers) is not int or type(editors) is not int or readers < 2 or not 1 <= editors <= 10:
        raise ValueError("Require at least two readers and one to ten editors.")
    return tuple(LoadAccount(index, editor) for editor, count in ((False, readers), (True, editors))
                 for index in range(count))


def workload_realm(template: dict, accounts: tuple[LoadAccount, ...]) -> dict:
    """Extend an isolated realm with unique subjects and environment placeholders."""
    realm = deepcopy(template)
    existing = {user["username"] for user in realm["users"]}
    for account in accounts:
        if account.username in existing:
            raise ValueError("Workload identities must be distinct from existing realm users.")
        existing.add(account.username)
        realm["users"].append({
            "id": str(uuid4()), "username": account.username,
            "firstName": "Load", "lastName": account.username,
            "email": account.username + "@example.test", "emailVerified": True, "enabled": True,
            "credentials": [{"type": "password", "value": "${" + account.password_key + "}", "temporary": False}],
        })
    return realm
