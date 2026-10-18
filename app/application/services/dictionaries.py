"""Shared business dictionary administration through injected transactions."""

from collections.abc import Mapping

from app.application.ports.dictionaries import DictionaryEntry, DictionaryGateway
from app.domain.access.models import Permission
from app.domain.dictionaries import dictionary_code, dictionary_edit, entry_id, locale_code


class DictionaryService:
    """Validate list/translation operations before entering persistence."""

    def __init__(self, gateway: DictionaryGateway) -> None:
        """Inject the authorized transaction gateway without opening storage."""
        self._gateway = gateway

    def list_entries(self, code: str, locale: str = 'en') -> list[DictionaryEntry]:
        """Return localized choices for one supported dictionary."""
        selected, language = dictionary_code(code), locale_code(locale)
        return self._gateway.run(lambda store: store.list_entries(selected, language))

    def translations(self, code: str, item_id: int) -> dict[str, str]:
        """Read explicit labels without confusing missing values with fallback."""
        selected, identity = dictionary_code(code), entry_id(item_id)
        return self._gateway.run(lambda store: store.translations(selected, identity))

    def save_entry(
        self, code: str, name: str, item_id: int | None = None,
        translations: Mapping[str, str] | None = None,
    ) -> int:
        """Save name and submitted labels atomically with shared permission."""
        selected = dictionary_code(code)
        identity = None if item_id is None else entry_id(item_id)
        edit = dictionary_edit(name, translations)
        return self._gateway.run(
            lambda store: store.save_entry(selected, edit, identity),
            write=True, permission=Permission.SHARED,
        )

    def delete_entry(self, code: str, item_id: int) -> None:
        """Remove an unused entry under authoritative shared authorization."""
        selected, identity = dictionary_code(code), entry_id(item_id)
        self._gateway.run(
            lambda store: store.delete_entry(selected, identity),
            write=True, permission=Permission.SHARED,
        )
