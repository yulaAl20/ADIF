"""Fit the confidence calibrator (D6, FR-7.6).

    python -m eval.fit_calibration --schemas data/dev --gold goldstandard --out config/calibrator.json

Runs the cascade over scratch schemas whose ground truth is known, collects
(stage, raw score, was-correct) observations, and fits one logistic model per
stage. Until this runs, the system reports no confidence at all — by design.

**Fitted on scratch data, never the evaluation set.** A calibrator fitted on
the schemas it is later measured against would report near-perfect ECE and mean
nothing. The same refusal as the grid search applies.

A warning rather than a failure is issued when a stage has very few
observations: a logistic fit on a handful of points is unstable, and a
confidence curve derived from six data points should be reported with that
caveat rather than quietly trusted.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml

from eval.runner import (
    build_context,
    discover_schemas,
    load_gold_standard,
    load_overlay,
    run_schema,
)
from src.config import load_config
from src.matching.confidence import (
    Calibrator,
    derive_review_threshold,
    expected_calibration_error,
)
from src.matching.models import NO_MAPPING

MIN_OBSERVATIONS_PER_STAGE = 30


def _refuse_sealed(path: Path) -> None:
    sealed = Path(load_config("config/default.yaml").paths.heldout_dir).resolve()
    resolved = path.resolve()
    if sealed == resolved or sealed in resolved.parents:
        raise SystemExit(
            f"REFUSED: '{path}' is the sealed evaluation directory.\n"
            f"A calibrator fitted on the data it is later scored against would "
            f"report an excellent ECE that means nothing (D6)."
        )



def _refuse_stub_embedder(cfg, real_model: bool, allow_stub: bool, what: str) -> None:
    """Refuse to derive real values from the stub embedder.

    The stub produces deterministic hash-derived vectors. Its similarities are
    meaningless by construction — it exists to exercise plumbing, not to rank
    anything. A threshold or calibration curve fitted on those numbers looks
    entirely plausible, writes itself into config, and silently corrupts every
    downstream result. Nothing in the output would reveal it.

    So this is a refusal, not a warning.
    """
    if not cfg.matching.stages.semantic.enabled or real_model or allow_stub:
        return
    raise SystemExit(
        f"REFUSED: the semantic stage is enabled but no real embedder is loaded.\n"
        f"The stub embedder's similarities are hash-derived noise, so {what} "
        f"derived from them would be meaningless while looking perfectly "
        f"reasonable in your config file.\n\n"
        f"Either:\n"
        f"  - cache the model (python -m scripts.fetch_model) and pass --real-model\n"
        f"  - or disable the semantic stage for this run\n"
        f"  - or pass --allow-stub if you are deliberately smoke-testing the "
        f"pipeline and will discard the output."
    )

def main() -> int:
    parser = argparse.ArgumentParser(description="Fit the confidence calibrator (D6)")
    parser.add_argument("--schemas", type=Path, default=Path("data/dev"))
    parser.add_argument("--gold", type=Path, default=Path("goldstandard"))
    parser.add_argument("--out", type=Path, default=Path("config/calibrator.json"))
    parser.add_argument("--fuzzy-threshold", type=float)
    parser.add_argument("--semantic-threshold", type=float)
    parser.add_argument("--value-threshold", type=float)
    parser.add_argument(
        "--review-accuracy", type=float, default=0.90,
        help="Accuracy the auto-accepted mappings must reach on the scratch "
             "data; the lowest confidence achieving it becomes the review "
             "threshold (default 0.90).",
    )
    parser.add_argument("--review-out", type=Path, default=Path("config/review_threshold.yaml"))
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument(
        "--allow-stub", action="store_true",
        help="Proceed with the stub embedder. Smoke-testing only — the "
             "output is meaningless and must be discarded.",
    )
    parser.add_argument(
        "--conditions", nargs="*", default=None,
        help="Ablation overlays to fit across. Default: the full ladder, so "
             "every stage any condition will use gets observations.",
    )
    args = parser.parse_args()

    _refuse_sealed(args.schemas)
    _refuse_stub_embedder(
        load_config('config/default.yaml'), args.real_model,
        args.allow_stub, 'a calibration curve',
    )

    cfg = load_overlay(
        fuzzy_threshold=args.fuzzy_threshold,
        semantic_threshold=args.semantic_threshold,
        value_threshold=args.value_threshold,
    )
    if cfg.unset_matching_thresholds():
        raise SystemExit(
            "Thresholds are unset. Run eval/grid_search.py first, write the "
            "derived values into config/default.yaml, or pass them explicitly "
            "with --fuzzy-threshold / --semantic-threshold / --value-threshold (D11)."
        )

    schemas = discover_schemas(args.schemas)

    # Fit across every ablation condition, not just the full cascade.
    # In the full cascade the alias stage absorbs most columns, so a fit done
    # there alone yields no fuzzy or semantic observations — and the resulting
    # calibrator cannot score the fuzzy_only condition at all. The calibrator
    # must cover every stage any condition will actually use.
    overlays: list[tuple[str, str | None]] = (
        [(c, f"config/ablation/{c}.yaml") for c in args.conditions]
        if args.conditions
        else [
            ("fuzzy_only", "config/ablation/fuzzy_only.yaml"),
            ("alias_fuzzy", "config/ablation/alias_fuzzy.yaml"),
            ("full_cascade", "config/ablation/full_cascade.yaml"),
            ("full_cascade_value", "config/ablation/full_cascade_value.yaml"),
        ]
    )

    observations = []
    sources = []
    for condition, overlay in overlays:
        if not Path(overlay).is_file():
            print(f"  skipping '{condition}' — {overlay} not found")
            continue
        cond_cfg = load_overlay(
            overlay_path=overlay,
            fuzzy_threshold=args.fuzzy_threshold,
            semantic_threshold=args.semantic_threshold,
            value_threshold=args.value_threshold,
        )
        if cond_cfg.unset_matching_thresholds():
            continue
        context = build_context(cond_cfg, real_model=args.real_model)
        for schema in schemas:
            gold_path = args.gold / f"{schema.stem}.json"
            if not gold_path.is_file():
                raise SystemExit(f"No gold standard for '{schema.name}' at {gold_path}.")
            gold = load_gold_standard(gold_path)
            sources.append(f"{condition}:{schema.name}@{gold.frozen_at}")
            result, _ = run_schema(schema, context)
            for record in result.records:
                if not record.is_mapped():
                    continue
                expected = gold.mappings.get(record.raw_header)
                if expected is None:
                    continue
                correct = record.target_field == expected and expected != NO_MAPPING
                observations.append((record.deciding_stage, record.raw_score, correct))

    if not observations:
        raise SystemExit(
            "No mapped records to calibrate on. Check that the gold standard "
            "headers match the schema headers exactly."
        )

    counts = Counter(stage.value for stage, _, _ in observations)
    print(f"Collected {len(observations)} observations: {dict(counts)}")
    for stage, n in counts.items():
        if n < MIN_OBSERVATIONS_PER_STAGE:
            print(
                f"  WARNING: only {n} observations for stage '{stage}'. A "
                f"logistic fit on this few points is unstable — report the "
                f"confidence curve for this stage with that caveat, or gather "
                f"more scratch data."
            )

    calibrator = Calibrator().fit(observations, source_label="; ".join(sources))
    calibrator.save(args.out)

    pairs = [
        (calibrator.confidence(stage, score), correct)
        for stage, score, correct in observations
    ]
    in_sample_ece = expected_calibration_error(pairs)

    print(f"\nFitted per-stage coefficients: {calibrator.coefficients}")
    print(f"Written to {args.out}")
    print(f"\nIn-sample ECE: {in_sample_ece:.4f}")
    review = derive_review_threshold(pairs, args.review_accuracy)
    if review is None:
        print(
            f"\nREVIEW THRESHOLD: no confidence level reaches "
            f"{args.review_accuracy:.0%} accuracy on the scratch data, so no "
            f"threshold was written. Report that finding; do not lower the target "
            f"to make a number appear."
        )
    else:
        args.review_out.parent.mkdir(parents=True, exist_ok=True)
        args.review_out.write_text(yaml.safe_dump({
            "_derived_by": "eval/fit_calibration.py",
            "_rule": f"lowest calibrated confidence at which accuracy >= "
                     f"{args.review_accuracy:.0%} on scratch data (in-sample)",
            "_accuracy_at_threshold": review["accuracy"],
            "_accepted": f"{review['accepted']}/{review['total']}",
            "confidence": {"bands": {"review": review["threshold"]}},
        }, sort_keys=False), encoding="utf-8")
        print(
            f"\nREVIEW THRESHOLD: {review['threshold']:.4f} — mappings below this "
            f"confidence go to a human. At or above it, {review['accepted']} of "
            f"{review['total']} scratch mappings are auto-accepted at "
            f"{review['accuracy']:.1%} accuracy (target {args.review_accuracy:.0%}).\n"
            f"Written to {args.review_out}. Copy it into config/default.yaml as "
            f"confidence.bands.review. (In-sample, like the ECE above.)"
        )
    print(
        "That is an IN-SAMPLE figure on the data the model was fitted to — it "
        "is not Metric 3 and must not be reported as such. Metric 3 is computed "
        "on the held-out schemas during the ablation run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
