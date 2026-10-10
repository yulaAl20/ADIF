"""Second-rater sampling and agreement measurement (methodology.md, Ground truth).

Two subcommands.

``sample`` draws a reproducible random subset of a schema's columns and writes a
blank worksheet for the second rater::

    python -m scripts.second_rater sample data/dev/manufacturer_a.csv --fraction 0.25

``agree`` compares the second rater's filled worksheet against the primary gold
standard and reports pre-adjudication agreement::

    python -m scripts.second_rater agree goldstandard/manufacturer_a.json \\
        goldstandard/manufacturer_a.rater2.worksheet.csv

**The sample is blank and seeded.** Blank because a rater shown the primary
decisions is not checking them, they are confirming them — people accept around
95% of supplied annotations without re-deriving them, so a pre-filled sheet
measures agreeableness rather than agreement. Seeded because the sample must be
reproducible: an examiner can re-draw exactly the rows you claim were checked.

**What the second rater must NOT receive:** the primary gold standard, the
perturbation log, or any matcher output. Only the rulebook, the CDM schema, and
this worksheet.

Agreement below the ≥90% target is a finding, not a failure. It means the
rulebook under-specifies something, and the fix is a new rule plus a re-check of
decisions that rule touches — recorded in decisions.md, not quietly smoothed over.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from src.analyser.profile import analyse_frame
from src.cdm.registry import CdmRegistry
from src.config import load_config
from src.ingestion.loader import load_tabular


def cmd_sample(args: argparse.Namespace) -> int:
    cfg = load_config("config/default.yaml")
    registry = CdmRegistry.load(
        cfg.paths.cdm_schema, cfg.paths.alias_vocabulary, cfg.normalisation
    )
    analysis = analyse_frame(load_tabular(args.schema, cfg).frame, cfg)

    count = max(1, round(args.fraction * len(analysis.columns)))
    rng = random.Random(args.seed)
    chosen = sorted(rng.sample(range(len(analysis.columns)), count))

    out = args.out / f"{args.schema.stem}.rater2.worksheet.csv"
    args.out.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["raw_header", "datatype", "sample_values", "cdm_field", "rationale"])
        for index in chosen:
            column = analysis.columns[index]
            writer.writerow([
                column.raw_header,
                column.datatype,
                " | ".join(column.sample_values[:3]),
                "",
                "",
            ])

    meta = args.out / f"{args.schema.stem}.rater2.sample.json"
    meta.write_text(json.dumps({
        "schema": args.schema.stem,
        "fraction_requested": args.fraction,
        "columns_total": len(analysis.columns),
        "columns_sampled": count,
        "fraction_actual": round(count / len(analysis.columns), 4),
        "seed": args.seed,
        "sampled_headers": [analysis.columns[i].raw_header for i in chosen],
    }, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {out}")
    print(f"  {count}/{len(analysis.columns)} columns ({count / len(analysis.columns):.0%}), seed {args.seed}")
    print(f"  Sample record: {meta}")
    print(f"\nGive the second rater ONLY:")
    print(f"  - this worksheet")
    print(f"  - goldstandard/RULEBOOK.md")
    print(f"  - goldstandard/CDM_FIELDS.txt and cdm/cdm_v1.0.schema.json")
    print(f"\nDo NOT give them your gold standard, the perturbation log, or any")
    print(f"matcher output. {len(registry.fields)} CDM fields are available to them.")
    return 0


def cmd_agree(args: argparse.Namespace) -> int:
    primary = json.loads(args.gold.read_text(encoding="utf-8"))
    mappings: dict[str, str] = primary["mappings"]

    rows = list(csv.DictReader(args.rater2.open(encoding="utf-8-sig")))
    compared: list[tuple[str, str, str]] = []
    for row in rows:
        header = (row.get("raw_header") or "").strip()
        field = (row.get("cdm_field") or "").strip()
        if not header or not field:
            continue
        if header not in mappings:
            print(f"  note: '{header}' is not in the primary gold standard — skipped")
            continue
        compared.append((header, mappings[header], field))

    if not compared:
        raise SystemExit("No comparable rows. Has the second rater filled the worksheet?")

    agreed = [c for c in compared if c[1] == c[2]]
    rate = len(agreed) / len(compared)
    disagreements = [c for c in compared if c[1] != c[2]]

    print(f"\nPre-adjudication agreement: {len(agreed)}/{len(compared)} = {rate:.1%}")
    print(f"Target (methodology.md): >= 90%")
    print(f"Schema: {primary['schema']}  |  primary rater: {primary.get('rater', '?')}")

    if disagreements:
        print(f"\n{len(disagreements)} disagreement(s) to adjudicate:\n")
        print(f"  {'column':<26}{'primary':<26}second rater")
        print("  " + "-" * 74)
        for header, mine, theirs in disagreements:
            print(f"  {header[:25]:<26}{mine:<26}{theirs}")
        print(
            "\nAdjudicate each one. For every disagreement ask whether the RULEBOOK\n"
            "was ambiguous — if it was, add a rule, then re-check any earlier decision\n"
            "that rule touches. Record the outcome in decisions.md. A disagreement\n"
            "resolved by one rater deferring to the other, with no rule change, is a\n"
            "sign the rulebook is still under-specified."
        )

    out = args.gold.with_suffix(".agreement.json")
    out.write_text(json.dumps({
        "schema": primary["schema"],
        "primary_rater": primary.get("rater"),
        "rulebook_version": primary.get("rulebook_version"),
        "compared": len(compared),
        "agreed": len(agreed),
        "agreement_rate": round(rate, 4),
        "target": 0.90,
        "meets_target": rate >= 0.90,
        "disagreements": [
            {"column": h, "primary": m, "second_rater": t} for h, m, t in disagreements
        ],
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nWritten to {out} — cite this figure in Chapter 3.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Second-rater sampling and agreement")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sample", help="Draw a blank worksheet for the second rater")
    s.add_argument("schema", type=Path)
    s.add_argument("--fraction", type=float, default=0.25)
    s.add_argument("--seed", type=int, default=2026)
    s.add_argument("--out", type=Path, default=Path("goldstandard"))
    s.set_defaults(func=cmd_sample)

    a = sub.add_parser("agree", help="Report agreement against the primary gold standard")
    a.add_argument("gold", type=Path)
    a.add_argument("rater2", type=Path)
    a.set_defaults(func=cmd_agree)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
