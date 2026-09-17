"""Allocation conflicts retained as actionable pool restoration diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PoolRestoreWarning:
    """One pool kept deleted and the reasons its restoration was blocked."""

    pool_id: int
    pool_name: str
    reasons: tuple[str, ...]


class PoolRestorationError(ValueError):
    """A restoration rejected without changing the retained pool or mappings."""

    def __init__(self, warning: PoolRestoreWarning) -> None:
        self.warning = warning
        super().__init__(f'Cannot restore {warning.pool_name}. ' + ' '.join(warning.reasons))
