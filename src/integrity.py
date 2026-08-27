"""Check the frozen research artefacts against the D30 freeze record.

Used by the website's admin page and by ``python -m scripts.verify_freeze``.

A plain SHA-256 comparison cannot tell a changed file from the same file
checked out with different line endings. That distinction matters: D30 hashed
the Windows working tree, where ``config/calibrator.json`` had been written by
Python with CRLF endings, while the repository (and every clone or ZIP of it)
holds LF. The coefficients are byte-for-byte identical; only ``\\r`` differs.
Reporting that as "differs" would overstate the problem, and silently
normalising would hide it. So the check reports a third, explicit status.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

__all__ = ["check_frozen", "FREEZE_RECORD"]

FREEZE_RECORD = Path("config/freeze_record_v1.0.yaml")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_frozen(record: Path = FREEZE_RECORD) -> list[dict[str, Any]]:
    """Return one row per frozen artefact.

    ``status`` is one of:

    * ``match`` — identical bytes.
    * ``match_line_endings`` — identical content; the recorded hash is of the
      same file with the other line-ending convention (CRLF vs LF).
    * ``differs`` — the content has changed. Investigate and record the cause.
    * ``missing`` — the file is absent.
    """
    if not record.is_file():
        return []
    raw = yaml.safe_load(record.read_text(encoding="utf-8")) or {}
    rows: list[dict[str, Any]] = []
    for name, expected in (raw.get("artefacts") or {}).items():
        path = Path(name)
        if not path.is_file():
            rows.append({"file": name, "expected": expected, "actual": None, "status": "missing"})
            continue
        data = path.read_bytes()
        actual = _sha(data)
        status = "match" if actual == expected else "differs"
        note = ""
        if status == "differs":
            lf = data.replace(b"\r\n", b"\n")
            if expected in (_sha(lf), _sha(lf.replace(b"\n", b"\r\n"))):
                status = "match_line_endings"
                note = ("Same content. The recorded hash is of this file with the other "
                        "line-ending convention (CRLF on the Windows machine that froze it).")
        rows.append({"file": name, "expected": expected, "actual": actual, "status": status, "note": note})
    return rows
