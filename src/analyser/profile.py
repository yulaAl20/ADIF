"""Schema analysis (M2) — FR-2.1 through FR-2.7.

Produces the record every matching stage consumes: ordered headers in raw and
normalised form, deterministic sample values, an inferred datatype, and a
column profile.

Sampling is *first-N in row order*, never random. NFR-5 requires identical
input and config to yield identical output, and a random sample would make the
value-based stage (M6) non-reproducible across runs of the same file.
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.analyser.normalise import normalise_header
from src.config import AdifConfig

__all__ = ["ColumnProfile", "SchemaAnalysis", "analyse_frame", "infer_datatype"]

_INTEGER = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


class ColumnProfile(BaseModel):
    """One column's analysis record (FR-2.1–2.4, FR-2.7)."""

    model_config = ConfigDict(extra="forbid")

    position: int
    raw_header: str
    normalised_header: str
    compact_header: str
    tokens: list[str]
    datatype: str
    sample_values: list[str]
    null_rate: float
    distinct_count: int
    min_length: int | None
    max_length: int | None
    numeric_min: float | None
    numeric_max: float | None


class SchemaAnalysis(BaseModel):
    """The full analysis of one uploaded file."""

    model_config = ConfigDict(extra="forbid")

    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    duplicate_headers_renamed: list[str]
    empty_headers_named: list[str]

    def headers(self) -> list[str]:
        """Return raw headers in file order (FR-2.1)."""
        return [c.raw_header for c in self.columns]


def _is_date(value: str, formats: list[str]) -> bool:
    for fmt in formats:
        try:
            datetime.strptime(value, fmt)
        except ValueError:
            continue
        return True
    return False


def infer_datatype(values: list[str], cfg: AdifConfig) -> str:
    """Classify a column from its sampled string values (FR-2.3).

    Every value is classified independently; the column takes a type only when
    at least ``analysis.type_inference_agreement`` of the sample agrees.
    Otherwise it is reported as ``mixed`` — an honest label that tells the
    value-based stage not to trust this column's shape, rather than a guess
    that quietly misleads it.

    Booleans deliberately exclude ``0``/``1``, which would otherwise swallow
    every integer column.

    Args:
        values: Non-null sampled values, as strings.
        cfg: Loaded configuration.

    Returns:
        One of ``string``, ``integer``, ``float``, ``date``, ``boolean``,
        ``mixed`` or ``unknown``.
    """
    if not values:
        return "unknown"

    truthy = {v.lower() for v in cfg.analysis.boolean_true}
    falsy = {v.lower() for v in cfg.analysis.boolean_false}
    booleans = truthy | falsy

    tally: dict[str, int] = {}
    for value in values:
        text = value.strip()
        if text.lower() in booleans:
            kind = "boolean"
        elif _INTEGER.match(text):
            kind = "integer"
        elif _FLOAT.match(text):
            kind = "float"
        elif _is_date(text, cfg.analysis.date_formats):
            kind = "date"
        else:
            kind = "string"
        tally[kind] = tally.get(kind, 0) + 1

    winner = max(tally, key=lambda k: tally[k])
    if tally[winner] / len(values) >= cfg.analysis.type_inference_agreement:
        return winner
    if tally.get("integer", 0) + tally.get("float", 0) == len(values):
        return "float"
    return "mixed"


def _resolve_headers(
    raw_headers: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Suffix duplicates and name empty headers (FR-2.5)."""
    resolved: list[str] = []
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    empties: list[str] = []

    for index, header in enumerate(raw_headers):
        name = str(header).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"col_{index}"
            empties.append(name)
        if name in seen:
            seen[name] += 1
            duplicates.append(name)
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        resolved.append(name)

    return resolved, duplicates, empties


def analyse_frame(frame: pd.DataFrame, cfg: AdifConfig) -> SchemaAnalysis:
    """Profile every column of a loaded frame.

    Args:
        frame: A string-typed frame from :func:`src.ingestion.loader.load_tabular`.
        cfg: Loaded configuration.

    Returns:
        A :class:`SchemaAnalysis` ready for the matching cascade.
    """
    resolved, duplicates, empties = _resolve_headers(list(frame.columns))
    sample_size = cfg.ingestion.sample_values_per_column
    profiles: list[ColumnProfile] = []

    for position, header in enumerate(resolved):
        # Positional selection, not frame[label]: duplicate headers are legal
        # in manufacturer exports, and label selection would return a DataFrame
        # rather than a Series for every duplicated name.
        series = frame.iloc[:, position]
        non_null = [
            str(v) for v in series.tolist() if v is not None and not pd.isna(v)
        ]
        non_null = [v for v in non_null if v != ""]
        samples = non_null[:sample_size]

        lengths = [len(v) for v in non_null] or None
        numeric: list[float] = []
        for value in non_null:
            try:
                numeric.append(float(value))
            except ValueError:
                continue

        normalised = normalise_header(header, cfg.normalisation)
        profiles.append(
            ColumnProfile(
                position=position,
                raw_header=header,
                normalised_header=normalised.normalised,
                compact_header=normalised.compact,
                tokens=normalised.tokens,
                datatype=infer_datatype(samples, cfg),
                sample_values=samples,
                null_rate=round(1 - (len(non_null) / len(series)), 4)
                if len(series)
                else 1.0,
                distinct_count=len(set(non_null)),
                min_length=min(lengths) if lengths else None,
                max_length=max(lengths) if lengths else None,
                numeric_min=min(numeric) if numeric else None,
                numeric_max=max(numeric) if numeric else None,
            )
        )

    return SchemaAnalysis(
        row_count=len(frame),
        column_count=len(profiles),
        columns=profiles,
        duplicate_headers_renamed=duplicates,
        empty_headers_named=empties,
    )
