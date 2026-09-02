"""Ingestion errors (M1).

Each carries a human-readable message. FR-1.6 in particular requires the
nested-JSON rejection to *name the scope limitation*, so a user meets the
research boundary rather than an unexplained parser failure.
"""

from __future__ import annotations

__all__ = [
    "EmptyInputError",
    "EncodingUndetectedError",
    "FileTooLargeError",
    "IngestionError",
    "NestedJsonError",
    "RowCapExceededError",
    "UnsupportedFormatError",
]


class IngestionError(Exception):
    """Base class for all ingestion failures (M1)."""


class UnsupportedFormatError(IngestionError):
    """The file extension is not one of .csv, .xlsx, .json (FR-1.1–1.3)."""


class NestedJsonError(IngestionError):
    """JSON input was not a flat array of objects (FR-1.6).

    Nested and hierarchical JSON is an explicit scope exclusion (project.md
    §2): matching a nested document to a canonical schema is structurally a
    different problem from matching a flat column list, and conflating them
    would weaken the claim this artefact actually supports.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"Nested JSON is outside the scope of this prototype: {detail}. "
            f"This tool accepts a flat array of objects, where every value is "
            f"a scalar. Hierarchical JSON is a structurally different matching "
            f"problem and is documented as a scope exclusion, not a defect. "
            f"Flatten the export, or supply it as CSV or Excel."
        )


class EmptyInputError(IngestionError):
    """The file contained zero data rows or zero columns (FR-1.9)."""


class EncodingUndetectedError(IngestionError):
    """None of the configured encodings decoded the file (FR-1.4)."""


class FileTooLargeError(IngestionError):
    """The file exceeded the configured size limit (FR-1.7)."""


class RowCapExceededError(IngestionError):
    """The file exceeded the configured row cap (FR-1.7)."""
