"""Per-stage accuracy and every wrong mapping on the scratch schemas.

    python -m eval.diagnose_stages --real-model

Read-only diagnostic: writes nothing to config. Runs the complete cascade with
the thresholds already in ``config/default.yaml`` and reports, per deciding
stage, how many mappings were made and how many were right, then lists each
wrong one with the header, what the system chose, what the gold standard says,
and the raw score. Use it to see *why* a stage's calibrated confidence is low
before deciding whether the cause is the matcher, the alias vocabulary, or the
gold standard.

Refuses the sealed directory, like the other scratch-data tools.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from eval.fit_calibration import _refuse_sealed, _refuse_stub_embedder
from eval.runner import (
    build_context,
    discover_schemas,
    load_gold_standard,
    load_overlay,
    run_schema,
)
from src.config import load_config
from src.matching.models import NO_MAPPING

OVERLAY = "config/ablation/full_cascade_value.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-stage accuracy diagnostic")
    parser.add_argument("--schemas", type=Path, default=Path("data/dev"))
    parser.add_argument("--gold", type=Path, default=Path("goldstandard"))
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--allow-stub", action="store_true")
    args = parser.parse_args()

    _refuse_sealed(args.schemas)
    _refuse_stub_embedder(load_config("config/default.yaml"), args.real_model,
                          args.allow_stub, "a diagnostic")

    cfg = load_overlay(overlay_path=OVERLAY)
    if cfg.unset_matching_thresholds():
        raise SystemExit("Thresholds unset - copy the grid-search values into "
                         "config/default.yaml first.")
    context = build_context(cfg, real_model=args.real_model)

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    wrong = []
    for schema in discover_schemas(args.schemas):
        gold = load_gold_standard(args.gold / f"{schema.stem}.json")
        result, _ = run_schema(schema, context)
        for r in result.records:
            if not r.is_mapped():
                continue
            expected = gold.mappings.get(r.raw_header)
            if expected is None:
                continue
            ok = r.target_field == expected and expected != NO_MAPPING
            stage = r.deciding_stage.value
            totals[stage][0] += 1
            totals[stage][1] += ok
            if not ok:
                wrong.append((stage, schema.name, r.raw_header, r.target_field,
                              expected, r.raw_score))

    print("\nstage      mapped  correct  accuracy")
    for stage, (n, k) in sorted(totals.items()):
        print(f"{stage:<10} {n:>6}  {k:>7}  {k / n:>7.1%}")
    print(f"\n{len(wrong)} wrong mapping(s):")
    for stage, schema, header, got, expected, score in sorted(wrong):
        print(f"  [{stage}] {schema}: '{header}' -> {got}   (gold: {expected}; "
              f"score {score:.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
