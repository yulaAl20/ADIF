"""The ablation ladder — Phase 5b Evaluation (D10, FR-14.1 to FR-14.8).

    python -m eval.run_ablation --schemas data/heldout --gold goldstandard --status EVALUATION

Runs every ablation condition against every schema, computes all four metrics
plus review burden and MRR, attributes ΔF1 to each added stage, and writes one
dated run record with full provenance.

**Status is EXPLORATORY unless you assert otherwise.** A run only earns
``EVALUATION`` when it used the frozen CDM, derived thresholds, a fitted
calibrator and a dated gold standard — and the script checks all four before
accepting the claim. The point is that a number in your Chapter 5 should be
traceable to a run record that says, in writing, that it was entitled to be
there.

Conditions come from ``config/ablation/``. Each is a partial overlay toggling
stages on and off, so the ladder measures the *same code* under different
configurations rather than four separate implementations.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.metrics import (
    MetricSet,
    ablation_delta,
    mandatory_coverage_ceiling,
    mandatory_match_rate,
    mapping_f1,
    reciprocal_rank,
    review_burden,
    surviving_stage_hits,
    write_run_record,
)
from eval.runner import (
    build_context,
    discover_schemas,
    load_gold_standard,
    load_overlay,
    run_schema,
)
from src.config import load_config
from src.matching.confidence import Calibrator
from src.matching.models import NO_MAPPING
from src.provenance import capture

LADDER = [
    ("fuzzy_only", "config/ablation/fuzzy_only.yaml"),
    ("alias_fuzzy", "config/ablation/alias_fuzzy.yaml"),
    ("full_cascade", "config/ablation/full_cascade.yaml"),
    ("full_cascade_value", "config/ablation/full_cascade_value.yaml"),
]

# D20 (ratified 2026-10-09): one supplementary condition, run only when named
# with --conditions, and kept OUT of the delta-F1 sequence. It is not a rung —
# putting it in the ladder would attribute a gain to a stage that was never
# "added" to anything.
SUPPLEMENTARY = [
    ("semantic_only", "config/ablation/semantic_only.yaml"),
    # D64: contingency deterministic baseline. Prepared, not run; run only if the
    # supervisor requires it, and report it as added after the main evaluation.
    ("alias_only_baseline", "config/ablation/alias_only_baseline.yaml"),
]
_LADDER_NAMES = {name for name, _ in LADDER}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ablation ladder (D10)")
    parser.add_argument("--schemas", type=Path, default=Path("data/dev"))
    parser.add_argument("--gold", type=Path, default=Path("goldstandard"))
    parser.add_argument("--calibrator", type=Path, default=Path("config/calibrator.json"))
    parser.add_argument("--out", type=Path, default=Path("runs"))
    parser.add_argument("--status", choices=["EXPLORATORY", "EVALUATION"],
                        default="EXPLORATORY")
    parser.add_argument("--confidence-threshold", type=float,
                        help="Acceptance threshold for the review-burden statistic (D16). "
                             "Defaults to confidence.bands.review from the config.")
    parser.add_argument("--conditions", nargs="*",
                        help="Subset of condition names; default is the full ladder")
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--trace-memory", action="store_true")
    args = parser.parse_args()

    base = load_config("config/default.yaml")
    if args.confidence_threshold is None:
        args.confidence_threshold = base.confidence.bands.review
    if args.conditions:
        known = {name for name, _ in LADDER + SUPPLEMENTARY}
        unknown = set(args.conditions) - known
        if unknown:
            raise SystemExit(f"Unknown condition(s) {sorted(unknown)}. Known: {sorted(known)}")
        conditions = [c for c in LADDER + SUPPLEMENTARY if c[0] in args.conditions]
    else:
        conditions = list(LADDER)

    schemas = discover_schemas(args.schemas)

    calibrator = None
    if args.calibrator.is_file():
        calibrator = Calibrator.load(args.calibrator)
        print(f"Calibrator loaded (fitted on: {calibrator.fitted_on})")
    else:
        print(f"No calibrator at {args.calibrator} — confidence and ECE will be absent.")

    # --- EVALUATION status has to be earned, not asserted -------------------
    if args.status == "EVALUATION":
        blockers = []
        if not Path(base.paths.cdm_schema).is_file():
            blockers.append("the frozen CDM schema does not exist (still on the fixture)")
        if base.unset_matching_thresholds():
            blockers.append(
                f"matching thresholds still unset: {base.unset_matching_thresholds()}"
            )
        if calibrator is None:
            blockers.append("no fitted calibrator")
        if blockers:
            raise SystemExit(
                "REFUSED: this run cannot be labelled EVALUATION.\n  - "
                + "\n  - ".join(blockers)
                + "\n\nRun it as EXPLORATORY, or resolve the above first. A run "
                  "record claiming EVALUATION is what a chapter cites."
            )

    metrics: list[MetricSet] = []
    calibration_pairs: list[tuple[float, bool]] = []
    uncalibrated_stages: set[str] = set()
    run_facts: dict[str, dict] = {}

    for name, overlay in conditions:
        cfg = load_overlay(overlay_path=overlay)
        if cfg.unset_matching_thresholds():
            raise SystemExit(
                f"Condition '{name}': {cfg.unset_matching_thresholds()} unset. Run "
                f"eval/grid_search.py and write the values into "
                f"config/default.yaml first (D11)."
            )
        context = build_context(cfg, real_model=args.real_model)

        for schema in schemas:
            gold_path = args.gold / f"{schema.stem}.json"
            if not gold_path.is_file():
                raise SystemExit(f"No gold standard for '{schema.name}' at {gold_path}.")
            gold = load_gold_standard(gold_path)

            result, facts = run_schema(schema, context, trace_memory=args.trace_memory)
            if calibrator is not None:
                skipped = calibrator.apply(result.records, strict=False)
                if skipped:
                    uncalibrated_stages.update(skipped)
                for record in result.records:
                    if record.confidence is not None:
                        expected = gold.mappings.get(record.raw_header)
                        if expected is not None:
                            calibration_pairs.append((
                                record.confidence,
                                record.target_field == expected and expected != NO_MAPPING,
                            ))

            precision, recall, f1 = mapping_f1(result, gold.mappings)
            metrics.append(MetricSet(
                schema=schema.stem,
                condition=name,
                precision=precision,
                recall=recall,
                f1=f1,
                mandatory_match_rate=mandatory_match_rate(
                    result, context.registry.mandatory_names(), gold.mappings),
                mandatory_coverage_ceiling=mandatory_coverage_ceiling(
                    context.registry.mandatory_names(), gold.mappings),
                ece=None,
                template_reuse_rate=None,
                review_burden=review_burden(result, args.confidence_threshold),
                mean_reciprocal_rank=reciprocal_rank(result, gold.mappings),
                mapped=len(result.mapped()),
                total_columns=len(result.records),
            ))
            run_facts[f"{name}/{schema.stem}"] = {
                **facts,
                "surviving_stage_hits": surviving_stage_hits(result),
                "raw_stage_hits": result.stage_hits,
                "gold_frozen_at": gold.frozen_at,
                "gold_rater": gold.rater,
            }
            print(f"  {name:<20} {schema.stem:<22} F1={f1:.4f}  "
                  f"burden={metrics[-1].review_burden:.2f}  "
                  f"{facts['total_seconds']:.2f}s")

    provenance = capture(base).model_dump()
    provenance["run_facts"] = run_facts
    provenance["using_fixture_cdm"] = not Path(base.paths.cdm_schema).is_file()
    provenance["calibrator_fitted_on"] = calibrator.fitted_on if calibrator else None
    provenance["uncalibrated_stages"] = sorted(uncalibrated_stages)

    path = write_run_record(
        args.out, metrics, provenance,
        status=args.status,
        calibration_pairs=calibration_pairs or None,
    )

    print(f"\nRun record: {path}  [{args.status}]")
    print("\nDelta-F1 per added stage:")
    for schema in {m.schema for m in metrics}:
        ladder = [m for m in metrics if m.schema == schema and m.condition in _LADDER_NAMES]
        for delta in ablation_delta(ladder):
            print(f"  {schema:<22} {delta['from']:>18} -> {delta['to']:<20} "
                  f"dF1={delta['delta_f1']:+.4f}  dBurden={delta['delta_review_burden']:+.4f}")

    if uncalibrated_stages:
        print(
            f"\nWARNING: no calibration model for stage(s) "
            f"{sorted(uncalibrated_stages)}. Those mappings carry no confidence, "
            f"so ECE here covers only a subset of decisions — say so wherever "
            f"you report Metric 3. Refit with eval/fit_calibration.py, which "
            f"fits across every ablation condition by default."
        )

    if args.status == "EXPLORATORY":
        print("\nThis run is EXPLORATORY. Do not cite these numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
