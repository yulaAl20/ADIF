"""Convert a filled worksheet into a frozen gold standard.

    python -m scripts.build_gold_standard goldstandard/manufacturer_b_erpnext.worksheet.csv

Validates every decision against the CDM, then writes the dated JSON the
evaluation harness consumes.

Validation is strict on purpose. A typo'd field name in a gold standard does
not announce itself — it quietly becomes a permanent false negative that the
system can never score against, and the resulting dip looks like an algorithm
problem rather than a spreadsheet problem.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

from src.cdm.registry import CdmRegistry
from src.config import load_config

NO_MAPPING = "NO_MAPPING"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a gold standard from a worksheet")
    parser.add_argument("worksheet", type=Path)
    parser.add_argument("--rater", required=True, help="Your initials, recorded in the file")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    cfg = load_config("config/default.yaml")
    registry = CdmRegistry.load(
        cfg.paths.cdm_schema, cfg.paths.alias_vocabulary, cfg.normalisation
    )
    valid = set(registry.names()) | {NO_MAPPING}

    rows = list(csv.DictReader(args.worksheet.open(encoding="utf-8-sig")))
    errors: list[str] = []
    mappings: dict[str, str] = {}
    rationales: dict[str, str] = {}
    rules: dict[str, str] = {}

    for index, row in enumerate(rows, start=2):
        header = (row.get("raw_header") or "").strip()
        field = (row.get("cdm_field") or "").strip()
        # 'rulebook_rule' and 'what_to_check' are guidance columns on some
        # worksheets. They are read for the record but never treated as a
        # decision — the decision is only ever what is in cdm_field.
        if not header:
            continue
        if not field:
            errors.append(f"line {index}: '{header}' has no decision. Every row needs one — "
                          f"use NO_MAPPING if there is no CDM target (rulebook R2.1).")
            continue
        if field not in valid:
            errors.append(f"line {index}: '{field}' is not a CDM field. "
                          f"See goldstandard/CDM_FIELDS.txt.")
            continue
        mappings[header] = field
        rationales[header] = (row.get("rationale") or "").strip()
        if row.get("rulebook_rule"):
            rules[header] = row["rulebook_rule"].strip()

    claimed = Counter(f for f in mappings.values() if f != NO_MAPPING)
    for field, count in claimed.items():
        if count > 1:
            owners = [h for h, f in mappings.items() if f == field]
            errors.append(f"'{field}' is claimed by {count} columns {owners}. "
                          f"Rulebook R1.2 allows only one.")

    missing_rationale = [h for h, r in rationales.items() if not r]
    if errors:
        print("REFUSED - fix these first:\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    derived = f"{args.worksheet.stem.replace('.worksheet', '')}.json"
    if args.out is None:
        out = Path("goldstandard") / derived
    elif args.out.is_dir():
        # A directory is a reasonable thing to pass; writing to it directly
        # would raise IsADirectoryError and look like a bug in the worksheet.
        out = args.out / derived
    else:
        out = args.out
    out.write_text(json.dumps({
        "schema": out.stem,
        "frozen_at": date.today().isoformat(),
        "rater": args.rater,
        "rulebook_version": "1.0",
        "cdm_schema_sha256": registry.schema_sha256,
        "mappings": mappings,
        "rationales": rationales,
        "rulebook_rules_cited": rules,
    }, indent=2) + "\n", encoding="utf-8")

    mapped = sum(1 for f in mappings.values() if f != NO_MAPPING)
    print(f"Wrote {out}")
    print(f"  {len(mappings)} columns: {mapped} mapped, {len(mappings) - mapped} NO_MAPPING")
    if missing_rationale:
        print(f"\n  {len(missing_rationale)} rows have no rationale: {missing_rationale[:5]}"
              f"{'...' if len(missing_rationale) > 5 else ''}")
        print("  Rulebook R6 asks for one on every row - it is what the second rater "
              "agrees or disagrees with, and what you rely on at the viva.")
    print(f"\n  Commit this now. It must predate any evaluation run (project.md section 11).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
