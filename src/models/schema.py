"""Schema domain models for parameter groups, parameters, and options."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SchemaGroup:
    """Represents a logical grouping of dynamic schema parameters.

    Attributes:
        id: Unique numeric group ID (primary key).
        group_name: Unique display name of the schema group.
        display_order: Display sequence index.
    """

    group_name: str
    display_order: int
    id: Optional[int] = None


@dataclass
class SchemaParameter:
    """Represents a dynamic attribute definition.

    Attributes:
        param_id: Unique parameter key (e.g. 'PRM_001').
        param_name: User-facing parameter label.
        param_type: Data type ('TEXT', 'ENUM', 'MULTI_ENUM', 'TAGS', 'URL', 'DATE', 'NUMBER', 'HYPERLINK').
        group_id: Optional reference to parent SchemaGroup ID.
        mandatory: Whether this dynamic parameter is required to save a project (default False).
        alias: Optional alternative name or display alias.
        applies_to_all: Whether this property applies to current and future types.
    """

    param_id: str
    param_name: str
    param_type: str
    group_id: Optional[int] = None
    mandatory: bool = False
    alias: Optional[str] = None
    applies_to_all: bool = True


@dataclass
class SchemaParamOption:
    """Represents a discrete choice value for ENUM, MULTI_ENUM, or TAGS parameters.

    Attributes:
        param_id: Reference to parent parameter ID.
        option_value: The text value of the option.
        display_order: Display sequence index.
        id: Optional unique numeric option ID.
    """

    param_id: str
    option_value: str
    display_order: int = 0
    id: Optional[int] = None
