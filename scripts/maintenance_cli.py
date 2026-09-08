"""Safe error handling shared by the maintenance command boundaries."""

from collections.abc import Callable
from functools import wraps
import logging

from app.application.exceptions import DatabaseMaintenanceError


def cli_errors[**P](command: Callable[P, None]) -> Callable[P, None]:
    """Report expected validation/storage failures without printing stack traces."""

    @wraps(command)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            command(*args, **kwargs)
        except (DatabaseMaintenanceError, ValueError) as error:
            logging.getLogger(command.__module__).error("%s", error)
            raise SystemExit(1) from None

    return run
