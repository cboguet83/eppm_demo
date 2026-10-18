"""Typed projections and transactional storage for shared business catalogs."""

from collections.abc import Callable
from typing import Protocol, TypedDict

from app.domain.access.models import Permission
from app.domain.dictionaries import DictionaryCode, DictionaryEdit


class DictionaryEntry(TypedDict):
    """Compatible catalog identity, canonical name and resolved label."""

    id: int
    name: str
    label: str


class DictionaryStore(Protocol):
    """Dictionary operations sharing one authorized connection."""

    def list_entries(self, code: DictionaryCode, locale: str) -> list[DictionaryEntry]: ...
    def translations(self, code: DictionaryCode, item_id: int) -> dict[str, str]: ...
    def save_entry(self, code: DictionaryCode, edit: DictionaryEdit, item_id: int | None) -> int: ...
    def delete_entry(self, code: DictionaryCode, item_id: int) -> None: ...


class DictionaryGateway(Protocol):
    """Replay an entire dictionary operation inside an authorized transaction."""

    def run[Result](
        self, operation: Callable[[DictionaryStore], Result], *, write: bool = False,
        permission: Permission | None = None,
    ) -> Result: ...
