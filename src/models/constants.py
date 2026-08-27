"""Constants and enumeration definitions for PPM Studio Pro."""

# Page Navigation Constants
PAGE_PORTFOLIO: str = "1. Portfolio Overview"
PAGE_PROJECT_MASTER: str = "2. Project Master Data"
PAGE_SCHEMA_DEF: str = "3. Parameters Definition (Schema)"
PAGE_PLANNING: str = "4. Planning & Step Loader"
PAGE_SETTINGS: str = "5. Organization & Settings"
PAGE_BUDGET: str = "6. Budget Tracking"

# Project Status Constants
STATUS_DRAFT: str = "Draft"
STATUS_IN_PROGRESS: str = "In Progress"
STATUS_ON_HOLD: str = "On Hold"
STATUS_COMPLETED: str = "Completed"
STATUS_CANCELLED: str = "Cancelled"
STATUS_LIST: list[str] = [
    STATUS_DRAFT,
    STATUS_IN_PROGRESS,
    STATUS_ON_HOLD,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
]

# Parameter Types
PARAM_TYPE_TEXT: str = "TEXT"
PARAM_TYPE_ENUM: str = "ENUM"
PARAM_TYPE_MULTI_ENUM: str = "MULTI_ENUM"
PARAM_TYPE_TAGS: str = "TAGS"
PARAM_TYPE_URL: str = "URL"
PARAM_TYPES: list[str] = [
    PARAM_TYPE_TEXT,
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_TAGS,
    PARAM_TYPE_URL,
]

# Strategic Priority Constants
PRIORITY_P1_CRITICAL: str = "P1 - Critical"
PRIORITY_P2_HIGH: str = "P2 - High"
PRIORITY_P3_MEDIUM: str = "P3 - Medium"
PRIORITY_P4_LOW: str = "P4 - Low"
PRIORITY_LIST: list[str] = [
    PRIORITY_P1_CRITICAL,
    PRIORITY_P2_HIGH,
    PRIORITY_P3_MEDIUM,
    PRIORITY_P4_LOW,
]

