"""Verify the frozen v1.0 artefacts against the D30 record.

    python -m scripts.verify_freeze

Exit code 0 when every artefact matches (exactly, or with identical content
and only a different line-ending convention); 1 otherwise.
"""

from __future__ import annotations

from src.integrity import check_frozen


def main() -> int:
    """Print one line per artefact and return a shell exit code."""
    rows = check_frozen()
    if not rows:
        print("No freeze record found.")
        return 1
    bad = 0
    for row in rows:
        print(f"{row['status']:20} {row['file']}")
        if row.get("note"):
            print(f"{'':20} {row['note']}")
        bad += row["status"] in ("differs", "missing")
    print("\nAll frozen artefacts intact." if not bad else f"\n{bad} artefact(s) changed or missing.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
