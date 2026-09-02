"""Tabular ingestion (M1) — FR-1.1 through FR-1.9.

Everything is read as **text**. No dtype inference happens here.

That is deliberate and load-bearing. pandas' default inference silently
destroys the identifiers this project depends on: a GTIN-13 like
``0012345678905`` becomes the integer ``12345678905``, and a style number like
``00742`` becomes ``742``. Both are then unrecoverable. Type inference is a
separate, reversible judgement made by the schema analyser (M2) over sampled
string values, where a wrong guess costs a label rather than the data.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.config import AdifConfig
from src.ingestion.errors import (
    EmptyInputError,
    EncodingUndetectedError,
    FileTooLargeError,
    NestedJsonError,
    RowCapExceededError,
    UnsupportedFormatError,
)

__all__ = ["LoadResult", "detect_encoding", "load_tabular", "sniff_delimiter"]

_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class LoadResult:
    """A loaded table plus how it was loaded, for the run record."""

    frame: pd.DataFrame
    source_format: str
    encoding: str | None
    delimiter: str | None
    sheet_name: str | None
    row_count: int
    column_count: int


def detect_encoding(raw: bytes, candidates: list[str]) -> str:
    """Return the first configured encoding that decodes ``raw`` cleanly.

    Candidates are tried in configured order (FR-1.4). ``utf-8-sig`` must be
    listed before ``latin-1``: latin-1 decodes any byte sequence without error,
    so it would otherwise mask every earlier candidate.

    Args:
        raw: The undecoded file contents.
        candidates: Encoding names, in priority order.

    Returns:
        The name of the first encoding that succeeded.

    Raises:
        EncodingUndetectedError: If no candidate decoded the file.
    """
    for enc in candidates:
        try:
            raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        return enc
    raise EncodingUndetectedError(
        f"None of the configured encodings decoded this file: {candidates}. "
        f"Re-export it as UTF-8."
    )


def sniff_delimiter(text: str, candidates: list[str]) -> str:
    """Infer the CSV delimiter (FR-1.5).

    Tries :mod:`csv`'s own sniffer first, then falls back to counting
    occurrences in the header line. The fallback matters for single-column
    files, where the sniffer raises rather than returning a sensible default.

    Args:
        text: Decoded file contents.
        candidates: Delimiter characters to consider.

    Returns:
        The inferred delimiter, defaulting to the first candidate.
    """
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(candidates)).delimiter
    except csv.Error:
        pass
    header = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: header.count(d) for d in candidates}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else candidates[0]


def _true_headers_csv(text: str, delimiter: str) -> list[str]:
    """Return the header row exactly as written, duplicates and all.

    pandas renames duplicate columns to ``name.1`` while reading. That happens
    before the analyser's FR-2.5 handling can see them, so the duplicate would
    be reported as a normal distinct column and the ``.1`` would leak into the
    normalised form. Reading the header ourselves keeps duplicate detection in
    one place and consistent across all three input formats.
    """
    line = text.splitlines()[0] if text.splitlines() else ""
    return next(csv.reader([line], delimiter=delimiter), [])


def _check_size(path: Path, cfg: AdifConfig) -> None:
    limit = cfg.ingestion.max_file_size_mb * _BYTES_PER_MB
    actual = path.stat().st_size
    if actual > limit:
        raise FileTooLargeError(
            f"File is {actual / _BYTES_PER_MB:.1f} MB; the configured limit is "
            f"{cfg.ingestion.max_file_size_mb} MB."
        )


def _check_shape(frame: pd.DataFrame, cfg: AdifConfig) -> None:
    if frame.shape[1] == 0:
        raise EmptyInputError("The file has no columns.")
    if frame.shape[0] == 0:
        raise EmptyInputError("The file has a header but no data rows.")
    if frame.shape[0] > cfg.ingestion.max_rows:
        raise RowCapExceededError(
            f"File has {frame.shape[0]} rows; the configured cap is "
            f"{cfg.ingestion.max_rows}."
        )


def _load_csv(path: Path, cfg: AdifConfig) -> LoadResult:
    raw = path.read_bytes()
    encoding = detect_encoding(raw, cfg.ingestion.encodings)
    text = raw.decode(encoding)
    delimiter = sniff_delimiter(text, cfg.ingestion.csv_delimiters)
    frame = pd.read_csv(
        path,
        encoding=encoding,
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
    )
    true_headers = _true_headers_csv(text, delimiter)
    if len(true_headers) == frame.shape[1]:
        frame.columns = true_headers
    _check_shape(frame, cfg)
    return LoadResult(
        frame=frame,
        source_format="csv",
        encoding=encoding,
        delimiter=delimiter,
        sheet_name=None,
        row_count=len(frame),
        column_count=frame.shape[1],
    )


def _load_excel(path: Path, cfg: AdifConfig, sheet_name: str | None) -> LoadResult:
    """Read the first sheet by default, or a named sheet if given (FR-1.2)."""
    target: str | int = sheet_name if sheet_name is not None else 0
    frame = pd.read_excel(path, sheet_name=target, dtype=str, engine="openpyxl")
    resolved = sheet_name
    with pd.ExcelFile(path, engine="openpyxl") as book:
        if resolved is None:
            resolved = book.sheet_names[0]
        # Same reason as the CSV path: recover pre-mangling duplicate headers.
        header_row = pd.read_excel(
            path, sheet_name=resolved, engine="openpyxl", header=None, nrows=1
        ).iloc[0].tolist()
    true_headers = ["" if pd.isna(h) else str(h) for h in header_row]
    if len(true_headers) == frame.shape[1]:
        frame.columns = true_headers
    frame = frame.where(frame.notna(), None)
    _check_shape(frame, cfg)
    return LoadResult(
        frame=frame,
        source_format="xlsx",
        encoding=None,
        delimiter=None,
        sheet_name=resolved,
        row_count=len(frame),
        column_count=frame.shape[1],
    )


def _load_json(path: Path, cfg: AdifConfig) -> LoadResult:
    """Read a flat array of objects, rejecting nesting explicitly (FR-1.3, FR-1.6)."""
    raw = path.read_bytes()
    encoding = detect_encoding(raw, cfg.ingestion.encodings)
    payload = json.loads(raw.decode(encoding))

    if not isinstance(payload, list):
        raise NestedJsonError(
            f"the top level is a {type(payload).__name__}, not an array"
        )
    if not payload:
        raise EmptyInputError("The JSON array is empty.")

    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise NestedJsonError(
                f"element {index} is a {type(row).__name__}, not an object"
            )
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                raise NestedJsonError(
                    f"field '{key}' in element {index} contains a "
                    f"{type(value).__name__}"
                )

    frame = pd.DataFrame(payload).astype("object")
    frame = frame.map(lambda v: None if v is None else str(v))
    _check_shape(frame, cfg)
    return LoadResult(
        frame=frame,
        source_format="json",
        encoding=encoding,
        delimiter=None,
        sheet_name=None,
        row_count=len(frame),
        column_count=frame.shape[1],
    )


def load_tabular(
    path: str | Path,
    cfg: AdifConfig,
    sheet_name: str | None = None,
) -> LoadResult:
    """Load a manufacturer file into a string-typed DataFrame.

    Args:
        path: File to read. Format is chosen by extension.
        cfg: Loaded configuration supplying encodings, delimiters and caps.
        sheet_name: Excel sheet to read; the first sheet if omitted.

    Returns:
        A :class:`LoadResult` carrying the frame and the decisions made
        while reading it, for the run record.

    Raises:
        UnsupportedFormatError: On an unrecognised extension.
        IngestionError: Subclasses for encoding, size, shape and nesting.
    """
    path = Path(path)
    _check_size(path, cfg)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(path, cfg)
    if suffix in {".xlsx", ".xlsm"}:
        return _load_excel(path, cfg, sheet_name)
    if suffix == ".json":
        return _load_json(path, cfg)
    raise UnsupportedFormatError(
        f"'{suffix}' is not supported. This prototype accepts .csv, .xlsx "
        f"and flat .json."
    )
