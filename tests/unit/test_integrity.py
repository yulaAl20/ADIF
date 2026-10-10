"""Frozen-artefact integrity check (D30, D58)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.integrity import check_frozen


def _record(tmp_path: Path, name: str, digest: str) -> Path:
    rec = tmp_path / "rec.yaml"
    rec.write_text(f"artefacts:\n  {name}: {digest}\n", encoding="utf-8")
    return rec


def test_real_record_has_no_changed_artefact():
    statuses = {r["file"]: r["status"] for r in check_frozen()}
    assert statuses and all(s in ("match", "match_line_endings") for s in statuses.values())
    assert statuses["config/calibrator.json"] == "match_line_endings"


def test_line_ending_only_difference_is_reported_explicitly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("f.json").write_bytes(b'{\n  "a": 1\n}')
    crlf = hashlib.sha256(b'{\r\n  "a": 1\r\n}').hexdigest()
    row = check_frozen(_record(tmp_path, "f.json", crlf))[0]
    assert row["status"] == "match_line_endings" and "line-ending" in row["note"]


def test_a_real_content_change_is_still_differs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("f.json").write_bytes(b'{\n  "a": 2\n}')
    old = hashlib.sha256(b'{\r\n  "a": 1\r\n}').hexdigest()
    assert check_frozen(_record(tmp_path, "f.json", old))[0]["status"] == "differs"
