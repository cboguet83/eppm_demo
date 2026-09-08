"""Decode uploaded CSV files at the presentation boundary."""

from typing import Protocol


class UploadedCsv(Protocol):
    """Minimal file-like contract implemented by Streamlit uploads and test streams."""

    def read(self) -> str | bytes: ...


def csv_text(uploaded_file: UploadedCsv | None) -> str:
    """Read UTF-8 content without exposing file-system or parser internals."""
    if uploaded_file is None:
        raise ValueError("No file uploaded.")
    try:
        content = uploaded_file.read()
        return content.decode("utf-8-sig") if isinstance(content, bytes) else content
    except (OSError, UnicodeError) as exc:
        raise ValueError("Failed to read CSV file. Upload a UTF-8 CSV file.") from exc
