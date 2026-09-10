"""WBS identities and integer project allocation rules (OTP in French)."""

import re
from typing import TypedDict


class WbsAllocation(TypedDict):
    """A project editor's allocation command, independent of persistence."""

    wbs_id: int
    percentage: int


class WbsOption(TypedDict):
    """Catalog choice with the maximum share available to the edited project."""

    id: int
    code: str
    description: str
    available: int


def normalize_wbs(code: str, description: str) -> tuple[str, str]:
    """Validate a stable code, including an optional fictive marker.

    Raises:
        ValueError: The code or description is malformed.
    """
    if not isinstance(code, str) or not isinstance(description, str):
        raise ValueError("WBS code and description must be text.")
    code = code.strip()
    if not re.fullmatch(r"#?[A-Za-z0-9._-]{1,128}", code):
        raise ValueError("WBS code must contain letters, numbers, dots, dashes or underscores; "
                         "only a fictive WBS may start with #.")
    return code, description.strip()


def normalize_allocations(raw: object) -> list[WbsAllocation]:
    """Validate untrusted assignments without rounding fractional percentages."""
    if not isinstance(raw, list):
        raise ValueError("WBS allocations must be a list.")
    result: list[WbsAllocation] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"wbs_id", "percentage"}:
            raise ValueError("Each WBS allocation needs a code and percentage.")
        identity, percentage = item["wbs_id"], item["percentage"]
        if type(identity) is not int or not 1 <= identity <= 9223372036854775807:
            raise ValueError("Select a valid WBS code.")
        if type(percentage) is not int or not 0 <= percentage <= 100:
            raise ValueError("WBS allocation must be a whole percentage from 0 to 100.")
        if identity in seen:
            raise ValueError("A WBS can be assigned only once to a project.")
        seen.add(identity)
        result.append(WbsAllocation(wbs_id=identity, percentage=percentage))
    return result


def validate_availability(allocations: list[WbsAllocation], options: list[WbsOption]) -> None:
    """Check the fresh global remainder while retaining no other project identities."""
    catalog = {row["id"]: row for row in options}
    for allocation in allocations:
        option = catalog.get(allocation["wbs_id"])
        if option is None:
            raise ValueError("A selected WBS no longer exists. Reopen the project to refresh the list.")
        if allocation["percentage"] > option["available"]:
            raise ValueError(f"WBS {option['code']}: only {option['available']}% is available for this project. "
                             "Total allocation across projects cannot exceed 100%.")
