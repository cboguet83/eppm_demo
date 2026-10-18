"""Stable business dictionary identities and validated translation edits."""

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Literal

type DictionaryCode = Literal['project_role', 'project_event_type']
_LOCALE = re.compile(r'[a-z]{2,3}(?:-[a-z0-9]{2,8}){0,3}\Z')


@dataclass(frozen=True)
class DictionaryEdit:
    """Validated canonical name and explicitly submitted locale changes."""

    name: str
    translations: dict[str, str]


def dictionary_code(value: str) -> DictionaryCode:
    """Validate the supported business list, raising ValueError if unknown."""
    if value == 'project_role':
        return 'project_role'
    if value == 'project_event_type':
        return 'project_event_type'
    raise ValueError('Unknown business dictionary.')


def entry_id(value: int) -> int:
    """Require a positive signed BIGINT reference, excluding boolean values."""
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise ValueError('Entry ID must be a positive integer.')
    return value


def locale_code(value: str) -> str:
    """Normalize a bounded language tag, rejecting malformed identifiers."""
    if not isinstance(value, str):
        raise ValueError('Invalid language code.')
    normalized = value.strip().lower()
    if len(normalized) > 32 or not _LOCALE.fullmatch(normalized):
        raise ValueError('Invalid language code.')
    return normalized


def dictionary_edit(
    name: str, translations: Mapping[str, str] | None = None,
) -> DictionaryEdit:
    """Validate an atomic name/translation edit without changing omitted locales.

    Args:
        name: Required canonical name, also used for the English label.
        translations: Submitted labels; blank non-English labels remove overrides.

    Returns:
        Normalized edit with a separate copy of the submitted labels.

    Raises:
        ValueError: If names, mappings, locales or labels are invalid.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Name is required.')
    if translations is not None and not isinstance(translations, Mapping):
        raise ValueError('Translations must be a language-to-label mapping.')
    labels: dict[str, str] = {}
    for raw_locale, label in (translations or {}).items():
        locale = locale_code(raw_locale)
        if locale in labels or not isinstance(label, str):
            raise ValueError('Invalid or repeated translation.')
        labels[locale] = label.strip()
    if 'en' in labels and labels['en'] != name.strip():
        raise ValueError('Edit the English label through the canonical name.')
    labels['en'] = name.strip()
    return DictionaryEdit(name.strip(), labels)
