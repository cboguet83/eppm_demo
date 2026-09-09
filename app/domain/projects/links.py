"""Validation for user-managed project links."""

from typing import TypedDict
from urllib.parse import urlsplit


class LinkValues(TypedDict):
    """A navigable web URL and its user-defined display alias."""

    url: str
    alias: str


def normalize_link(url: str, alias: str) -> LinkValues:
    """Require a named HTTP(S) link without embedded credentials.

    Args:
        url: Absolute web URL supplied by the user.
        alias: Text displayed in place of the URL.

    Returns:
        Trimmed values suitable for storage and safe navigation.

    Raises:
        ValueError: Either field is missing or the URL is not navigable.
    """
    if not isinstance(url, str) or not isinstance(alias, str) or not alias.strip():
        raise ValueError("A URL and display alias are required.")
    url = url.strip()
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                 and not parsed.username and not parsed.password)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTP or HTTPS URL.") from exc
    if not valid or any(char.isspace() or ord(char) < 32 for char in url):
        raise ValueError("Enter a valid HTTP or HTTPS URL.")
    return LinkValues(url=url, alias=alias.strip())
