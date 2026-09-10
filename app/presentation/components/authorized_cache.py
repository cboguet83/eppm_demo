"""Display caching that reauthorizes before looking up a cached response.

Any is limited to Streamlit's generic decorator and function-argument boundary.
The injected service or workspace owns the trusted, current security revision.
"""

from collections.abc import Callable
from functools import wraps
from inspect import signature
from typing import Any

import streamlit as st

from app.application.services.portfolio import portfolio_revision_token


class _AuthorizedRevision(tuple):
    """Retain the complete revision while hashing it as one compact fingerprint."""


def authorized_cache(**options: Any) -> Callable:
    """Bind every lookup to current server-side access, even for an old callback."""
    def decorate(function: Callable) -> Callable:
        parameters = signature(function)
        hash_funcs = dict(options.get("hash_funcs") or {})
        hash_funcs[_AuthorizedRevision] = portfolio_revision_token
        cached = st.cache_data(**{**options, "hash_funcs": hash_funcs})(function)

        @wraps(function)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            values = parameters.bind(*args, **kwargs)
            owner = values.arguments.get("_workspace") or values.arguments.get("_service")
            if owner is None:
                raise ValueError("Protected caching requires an injected revision owner.")
            current = owner.revision()
            values.arguments["revision"] = _AuthorizedRevision((values.arguments["revision"], current))
            return cached(*values.args, **values.kwargs)

        guarded.clear = cached.clear
        return guarded

    return decorate
