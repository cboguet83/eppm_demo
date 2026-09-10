"""Versioned budget snapshots and exact, calendar-bound finance input rules."""

import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal

MAX_ROWS = 10000
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_CENTS = 9223372036854775807
CODE = re.compile(r"#?[A-Za-z0-9._-]{1,128}\Z")
AMOUNT = re.compile(r"[0-9]+(?:[.,][0-9]{1,2})?\Z")
ERRORS = {
    "amount": "Row {row}, year {year}: use a nonnegative euro amount with at most two decimal places.",
    "code": "Row {row}: invalid WBS code. Use letters, numbers, dots, dashes or underscores, with an optional leading #.",
    "duplicate": "Row {row}: WBS code {code} appears more than once.",
    "rows": "Provide no more than 10,000 WBS rows with valid code and amount fields.",
    "years": "Row {row}: only years {first} to {last} can be changed. Past years are read-only.",
    "headers": "CSV headers must be wbs_code, description and every year from {first} to {last}, exactly once.",
    "csv": "Select a valid UTF-8 CSV file no larger than 2 MiB, using comma or semicolon separators.",
    "columns": "Row {row}: the number of cells does not match the CSV header.",
    "name": "Enter a major-version name of 1 to 120 characters without control characters.",
    "missing": "The selected budget snapshot no longer exists or is invalid. Reload Finance.",
    "stale": "This major version has a newer revision. Your changes are retained; reload the latest revision before saving.",
    "year_changed": "The calendar year has changed. Export or copy your changes, then reload Finance before saving.",
    "mode": "Choose a new major version or a revision of the selected major version.",
    "status": "Choose Proposed or Approved for the latest revision; its status must change.",
}


class FinanceError(ValueError):
    """A safe, translatable business validation error with row/column context."""

    def __init__(self, error_code: str, **parameters: object) -> None:
        self.code, self.parameters = error_code, parameters
        super().__init__(ERRORS[error_code].format(**parameters))


@dataclass(frozen=True)
class BudgetRow:
    """A code and sparse absolute-year amounts in integer euro cents."""

    code: str
    amounts: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BudgetVersion:
    """Public immutable snapshot metadata, independent of database rows."""

    id: int
    major: int
    minor: int
    name: str
    status: str
    author: str
    created_at: int
    base_id: int | None


@dataclass(frozen=True)
class BudgetSnapshot:
    """One complete saved budget version, including years outside today's view."""

    version: BudgetVersion
    rows: tuple[BudgetRow, ...]


def parse_amount(value: object, row: int, year: int) -> int | None:
    """Parse plain decimal text exactly, retaining blank separately from zero."""
    if not isinstance(value, str) or len(value) > 24:
        raise FinanceError("amount", row=row, year=year)
    value = value.strip()
    if not value:
        return None
    if not AMOUNT.fullmatch(value):
        raise FinanceError("amount", row=row, year=year)
    cents = int(Decimal(value.replace(",", ".")) * 100)
    if cents > MAX_CENTS:
        raise FinanceError("amount", row=row, year=year)
    return cents


def euro_text(cents: int) -> str:
    """Format stored cents without introducing a binary floating-point value."""
    return f"{cents // 100}.{cents % 100:02d}"


def normalize_rows(raw: object, year: int, *, first_row: int = 1) -> tuple[BudgetRow, ...]:
    """Validate the entire editable grid before any version can be persisted."""
    if not isinstance(raw, list) or len(raw) > MAX_ROWS:
        raise FinanceError("rows")
    result, codes = [], set()
    allowed = {str(value) for value in range(year, year + 15)}
    for number, item in enumerate(raw, first_row):
        if not isinstance(item, dict) or set(item) != {"code", "amounts"}:
            raise FinanceError("rows")
        code, amounts = item["code"], item["amounts"]
        if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
            raise FinanceError("code", row=number)
        code = code.strip()
        if code in codes:
            raise FinanceError("duplicate", row=number, code=code)
        if not isinstance(amounts, dict) or set(amounts) - allowed:
            raise FinanceError("years", row=number, first=year, last=year + 14)
        values = {}
        for key, value in amounts.items():
            parsed = parse_amount(value, number, int(key))
            if parsed is not None:
                values[int(key)] = parsed
        result.append(BudgetRow(code, values))
        codes.add(code)
    return tuple(result)


def preserve_history(base: tuple[BudgetRow, ...], edited: tuple[BudgetRow, ...], year: int) -> tuple[BudgetRow, ...]:
    """Replace the future grid while retaining all saved historical amounts."""
    historical = {row.code: {y: amount for y, amount in row.amounts.items() if y < year} for row in base}
    result = [BudgetRow(row.code, historical.pop(row.code, {}) | row.amounts) for row in edited]
    result.extend(BudgetRow(code, values) for code, values in historical.items() if values)
    if len(result) > MAX_ROWS:
        raise FinanceError("rows")
    return tuple(result)


def version_name(value: object) -> str:
    """Validate the required name shared by every revision of a major version."""
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 120
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise FinanceError("name")
    return value.strip()


def parse_csv(content: object, year: int) -> tuple[BudgetRow, ...]:
    """Read the documented export format, ignoring informational descriptions."""
    if not isinstance(content, str) or len(content) > MAX_CSV_BYTES or "\x00" in content:
        raise FinanceError("csv")
    try:
        if len(content.encode("utf-8")) > MAX_CSV_BYTES:
            raise FinanceError("csv")
        text = content.lstrip("\ufeff")
        header_line = text.splitlines()[0] if text else ""
        delimiter = ";" if ";" in header_line else ","
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        headers = next(reader, [])
        expected = ["wbs_code", "description", *map(str, range(year, year + 15))]
        if len(headers) != len(expected) or set(headers) != set(expected):
            raise FinanceError("headers", first=year, last=year + 14)
        rows = []
        for number, cells in enumerate(reader, 2):
            if len(cells) != len(headers):
                raise FinanceError("columns", row=number)
            values = dict(zip(headers, cells))
            code = values["wbs_code"]
            if code.startswith("'-"):
                code = code[1:]  # Spreadsheet-safe escaping emitted by export_csv.
            rows.append({"code": code, "amounts": {key: values[key] for key in expected[2:]}})
            if len(rows) > MAX_ROWS:
                raise FinanceError("rows")
        return normalize_rows(rows, year, first_row=2)
    except (UnicodeError, csv.Error):
        raise FinanceError("csv") from None


def export_csv(rows: tuple[BudgetRow, ...], catalog: dict[str, str], year: int) -> str:
    """Export all codes and only current/future years, with safe spreadsheet text."""
    def safe(value: str) -> str:
        return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value

    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    years = range(year, year + 15)
    writer.writerow(["wbs_code", "description", *years])
    for row in rows:
        writer.writerow([safe(row.code), safe(catalog.get(row.code, "")),
                         *(euro_text(row.amounts[y]) if y in row.amounts else "" for y in years)])
    return output.getvalue()
