"""Derive a drift schema's gold standard from its parent (D8, Metric 4).

    python -m scripts.derive_drift_gold manufacturer_b_erpnext

A drifted schema is its parent with some headers renamed, some dropped and
some added. **Renaming a header does not change what the column contains**, so
a renamed column maps to the same CDM field it did before. No new judgement is
required, and inventing one would risk contradicting the parent.

So this derives the drift gold standard mechanically: parent decision + the
perturbation log's rename map. Anything it cannot account for — a genuinely new
column, a header matching nothing — is reported and left for you to decide by
hand.

**Why using the perturbation log is legitimate here.** You generated the
perturbation; you already know what changed. The independence that matters is
the *second rater's*, and `goldstandard/RULEBOOK.md` forbids showing them the
log precisely so their check stays independent. The primary rater deriving the
mechanical consequence of their own perturbation is not circular.

The output records that it was derived and from which parent hash, so the
provenance is visible rather than implied.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from src.provenance import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive a drift gold standard")
    parser.add_argument("parent", help="Parent schema stem, e.g. manufacturer_b_erpnext")
    parser.add_argument("--gold", type=Path, default=Path("goldstandard"))
    parser.add_argument("--data", type=Path, default=Path("data/dev"))
    args = parser.parse_args()

    parent_gold = args.gold / f"{args.parent}.json"
    if not parent_gold.is_file():
        raise SystemExit(
            f"{parent_gold} does not exist.\n"
            f"Write the PARENT gold standard first — this script derives the "
            f"drift version from it and cannot invent the judgement."
        )

    log_path = args.data / f"{args.parent}_drift.perturbation_log.json"
    if not log_path.is_file():
        raise SystemExit(f"{log_path} not found. Was the drift variant generated?")

    sheet = args.gold / f"{args.parent}_drift.worksheet.csv"
    if not sheet.is_file():
        raise SystemExit(
            f"{sheet} not found. Generate it first:\n"
            f"  python -m scripts.make_gold_worksheet "
            f"{args.data}/{args.parent}_drift.csv"
        )

    parent = json.loads(parent_gold.read_text(encoding="utf-8"))
    mappings: dict[str, str] = parent["mappings"]
    rationales: dict[str, str] = parent.get("rationales", {})

    log = json.loads(log_path.read_text(encoding="utf-8"))
    renames = {r["new"]: r["original"] for r in log.get("headers_renamed", [])}

    import csv

    headers = [
        (row.get("raw_header") or "").strip()
        for row in csv.DictReader(sheet.open(encoding="utf-8-sig"))
    ]
    headers = [h for h in headers if h]

    derived: dict[str, str] = {}
    derived_rationales: dict[str, str] = {}
    unresolved: list[str] = []

    for header in headers:
        if header in mappings:
            derived[header] = mappings[header]
            derived_rationales[header] = (
                f"Unchanged from parent {args.parent}. " + rationales.get(header, "")
            ).strip()
        elif header in renames and renames[header] in mappings:
            original = renames[header]
            derived[header] = mappings[original]
            derived_rationales[header] = (
                f"Renamed from '{original}' by the perturbation; a header rename "
                f"does not change column contents, so the parent decision stands. "
                + rationales.get(original, "")
            ).strip()
        else:
            unresolved.append(header)

    if unresolved:
        print(f"\n{len(unresolved)} column(s) could not be derived — decide these by hand:")
        for header in unresolved:
            print(f"  - {header}")
        print(
            f"\nFill them in {sheet}, then run "
            f"scripts/build_gold_standard.py on it instead of using this script."
        )
        return 1

    out = args.gold / f"{args.parent}_drift.json"
    out.write_text(json.dumps({
        "schema": f"{args.parent}_drift",
        "frozen_at": date.today().isoformat(),
        "rater": parent.get("rater", "unrecorded"),
        "rulebook_version": parent.get("rulebook_version", "1.0"),
        "derived_from": args.parent,
        "derived_from_sha256": file_sha256(parent_gold),
        "derivation": (
            "Mechanically derived: parent decisions carried across, renamed "
            "headers resolved via the perturbation log. No new judgement."
        ),
        "cdm_schema_sha256": parent.get("cdm_schema_sha256"),
        "mappings": derived,
        "rationales": derived_rationales,
    }, indent=2) + "\n", encoding="utf-8")

    carried = sum(1 for h in headers if h in mappings)
    print(f"\nWrote {out}")
    print(f"  {len(derived)} columns: {carried} unchanged, {len(derived) - carried} renamed")
    print(f"  dropped by the perturbation: {log.get('headers_dropped') or 'none'}")
    print(f"\n  Derived from {parent_gold} — commit both together.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
