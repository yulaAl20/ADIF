"""M1 ingestion tests — FR-1.x."""

from __future__ import annotations

import json

import pytest

from src.config import load_config
from src.ingestion.errors import (
    EmptyInputError,
    NestedJsonError,
    UnsupportedFormatError,
)
from src.ingestion.loader import detect_encoding, load_tabular, sniff_delimiter

CFG = load_config("config/default.yaml")


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def test_csv_loads_with_comma(tmp_path):
    p = _write(tmp_path, "a.csv", "style,colour\nT100,Navy\n")
    r = load_tabular(p, CFG)
    assert r.source_format == "csv"
    assert r.delimiter == ","
    assert r.column_count == 2


def test_semicolon_delimiter_is_sniffed(tmp_path):
    p = _write(tmp_path, "a.csv", "style;colour;size\nT100;Navy;M\n")
    assert load_tabular(p, CFG).delimiter == ";"


def test_leading_zeros_in_gtin_survive_ingestion(tmp_path):
    """The reason everything is read as text — default inference destroys these."""
    p = _write(tmp_path, "a.csv", "gtin,style\n0012345678905,00742\n")
    frame = load_tabular(p, CFG).frame
    assert frame["gtin"].iloc[0] == "0012345678905"
    assert frame["style"].iloc[0] == "00742"


def test_utf8_bom_is_detected(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes("style,colour\nT100,Navy\n".encode("utf-8-sig"))
    r = load_tabular(p, CFG)
    assert r.encoding in {"utf-8", "utf-8-sig"}
    assert "style" in [c.lstrip("\ufeff") for c in r.frame.columns]


def test_encoding_candidates_are_tried_in_order():
    assert detect_encoding("café".encode("utf-8"), ["utf-8", "latin-1"]) == "utf-8"
    assert detect_encoding(b"\xff\xfe\x00", ["utf-8", "latin-1"]) == "latin-1"


def test_single_column_file_does_not_break_the_sniffer(tmp_path):
    p = _write(tmp_path, "one.csv", "style\nT100\nT200\n")
    assert load_tabular(p, CFG).column_count == 1


def test_flat_json_loads(tmp_path):
    rows = [{"style": "T100", "colour": "Navy"}]
    p = _write(tmp_path, "a.json", json.dumps(rows))
    assert load_tabular(p, CFG).column_count == 2


def test_nested_json_is_rejected_naming_the_scope_limit(tmp_path):
    rows = [{"style": "T100", "composition": {"cotton": 80}}]
    p = _write(tmp_path, "n.json", json.dumps(rows))
    with pytest.raises(NestedJsonError, match="outside the scope"):
        load_tabular(p, CFG)


def test_json_array_of_arrays_is_rejected(tmp_path):
    p = _write(tmp_path, "n.json", json.dumps([["a", "b"]]))
    with pytest.raises(NestedJsonError):
        load_tabular(p, CFG)


def test_header_only_file_is_rejected(tmp_path):
    p = _write(tmp_path, "e.csv", "style,colour\n")
    with pytest.raises(EmptyInputError):
        load_tabular(p, CFG)


def test_unknown_extension_is_rejected(tmp_path):
    p = _write(tmp_path, "a.txt", "style\nT100\n")
    with pytest.raises(UnsupportedFormatError):
        load_tabular(p, CFG)


def test_excel_round_trips(tmp_path):
    import pandas as pd

    p = tmp_path / "a.xlsx"
    pd.DataFrame({"style": ["T100"], "colour": ["Navy"]}).to_excel(p, index=False)
    r = load_tabular(p, CFG)
    assert r.source_format == "xlsx"
    assert r.sheet_name is not None


def test_sniff_delimiter_defaults_when_none_present():
    assert sniff_delimiter("style\nT100\n", [",", ";", "\t", "|"]) == ","


def test_duplicate_csv_headers_survive_to_the_analyser(tmp_path):
    """pandas renames duplicates to name.1 while reading; FR-2.5 handling must
    see the true headers so the rename is reported, not silently absorbed."""
    p = _write(tmp_path, "d.csv", "origin,origin\nLK,Sri Lanka\n")
    assert list(load_tabular(p, CFG).frame.columns) == ["origin", "origin"]
