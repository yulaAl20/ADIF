"""Summarise evaluation run records for the write-up (read-only).

    python -m eval.summarise_run runs/eval_*.json runs/template_reuse_*.json

Reads run records and prints, per condition, the macro-averaged metrics, the
per-schema delta-F1 for each added stage, ECE with its reliability bins, and
the template-reuse tables.

**Why this exists.** The ``ablation_deltas`` list stored inside an ablation
record pairs consecutive entries of the whole metrics list, so it compares
different schemas (for example ``fuzzy_only -> fuzzy_only``). The console
printed the correct per-schema deltas, but the stored list is not safe to cite.
This script recomputes deltas from ``metrics`` per schema, in ladder order.
It is analysis code, outside the frozen system, and changes nothing.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

LADDER = ["fuzzy_only", "alias_fuzzy", "full_cascade", "full_cascade_value"]


def mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def fmt(value: float | None) -> str:
    return "  n/a " if value is None else f"{value:6.3f}"


def ablation(record: dict) -> None:
    metrics = record["metrics"]
    by_condition: dict[str, list[dict]] = defaultdict(list)
    by_schema: dict[str, dict[str, dict]] = defaultdict(dict)
    for m in metrics:
        by_condition[m["condition"]].append(m)
        by_schema[m["schema"]][m["condition"]] = m

    print(f"  {record['status']}  written {record['written_at']}  "
          f"commit {record['provenance']['git_commit'][:7]}")
    print("\n  Macro-average over schemas (each schema counts once)")
    print(f"  {'condition':<22}{'F1':>7}{'P':>7}{'R':>7}{'MRR':>7}{'mand.':>7}{'burden':>8}")
    for cond, rows in by_condition.items():
        print(f"  {cond:<22}{fmt(mean([r['f1'] for r in rows]))}{fmt(mean([r['precision'] for r in rows]))}"
              f"{fmt(mean([r['recall'] for r in rows]))}{fmt(mean([r['mean_reciprocal_rank'] for r in rows]))}"
              f"{fmt(mean([r['mandatory_match_rate'] for r in rows]))}{fmt(mean([r['review_burden'] for r in rows])):>8}")

    present = [c for c in LADDER if c in by_condition]
    if len(present) >= 2:
        print("\n  Delta-F1 per added stage, per schema (recomputed from metrics)")
        for schema, conds in by_schema.items():
            steps = [(a, b) for a, b in zip(present, present[1:]) if a in conds and b in conds]
            parts = [f"{a}->{b} {conds[b]['f1'] - conds[a]['f1']:+.3f}" for a, b in steps]
            print(f"  {schema:<28}" + "  ".join(parts))

    print(f"\n  ECE (pooled over conditions and schemas): {record.get('ece')}")
    for b in record.get("reliability_bins", []):
        print(f"    bin {b['bin_lower']:.1f}-{b['bin_upper']:.1f}  n={b['count']:<4} "
              f"mean confidence {b['mean_confidence']:.3f}  accuracy {b['accuracy']:.3f}")
    print("    Caveat: the same column is counted once per condition that maps it, so the")
    print("    pooled pairs are not independent and the effective sample is smaller.")


def reuse(record: dict) -> None:
    print(f"  {record['status']}  template from: {record['template_from']}  "
          f"commit {record['provenance']['git_commit'][:7]}")
    print(f"  {'condition':<20}{'schema':<24}{'reuse':>12}{'delta cols':>12}{'dF1':>8}")
    for s in record["scores"]:
        reused = f"{s['reused_correct']}/{s['unchanged_mappable']}"
        print(f"  {s['condition']:<20}{s['schema']:<24}{reused:>12}{s['delta_mappable']:>12}{s['delta_f1']:>8.3f}")
    if record["template_from"] == "gold":
        print("  (reuse is 100% by construction with a reviewer-corrected template)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarise evaluation run records")
    parser.add_argument("records", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.records:
        record = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n=== {path.name} ===")
        if "metrics" in record:
            ablation(record)
        elif "scores" in record:
            reuse(record)
        else:
            print("  unrecognised record format")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
