"""Calibrated confidence (M7, FR-7.6, FR-7.7).

D6 is the whole point of this module: a raw cascade score is **not** a
confidence and must never be reported as one. Stage 1 alias hits score a
constant 100, fuzzy scores are Levenshtein-derived ratios, and semantic scores
are rescaled cosines. Those three live on incommensurable scales. Averaging or
displaying them side by side as "confidence" would produce a number that looks
meaningful, calibrates terribly, and cannot be falsified — the exact failure
the ECE metric exists to catch.

Instead, confidence is *learned*: a logistic model maps (raw score, deciding
stage) onto the empirical probability that the mapping is correct, fitted on
held-out scratch schemas whose ground truth is known. A confidence of 0.8 then
carries a testable claim — roughly eight in ten such mappings should be right —
and Metric 3 measures whether that holds.

Until it is fitted, every confidence read raises. There is no default.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from src.config import UnsetTunable
from src.matching.models import MappingRecord, Stage

__all__ = [
    "Calibrator",
    "derive_review_threshold",
    "expected_calibration_error",
    "reliability_bins",
]


@dataclass
class Calibrator:
    """Per-stage Platt scaling: ``P(correct) = sigmoid(a * score + b)``.

    One model per stage, because the relationship between score and correctness
    genuinely differs between them. A fuzzy score of 90 and a semantic score of
    90 do not carry the same evidential weight, and a single pooled model would
    average that difference away.
    """

    coefficients: dict[str, tuple[float, float]] = field(default_factory=dict)
    fitted_on: str | None = None
    sample_size: int = 0

    @property
    def is_fitted(self) -> bool:
        return bool(self.coefficients)

    def fit(
        self,
        observations: list[tuple[Stage, float, bool]],
        source_label: str,
        iterations: int = 2000,
        learning_rate: float = 0.01,
    ) -> Calibrator:
        """Fit one logistic model per stage by gradient descent.

        Args:
            observations: ``(stage, raw_score, was_correct)`` triples from
                scratch schemas — never from the held-out evaluation set.
            source_label: What the fit was performed on, recorded for the run
                record so a calibrator can never be used without provenance.
            iterations: Gradient descent steps.
            learning_rate: Step size.

        Returns:
            ``self``, fitted.

        Raises:
            ValueError: If no observations are supplied.
        """
        if not observations:
            raise ValueError("Cannot fit a calibrator on zero observations.")

        by_stage: dict[str, list[tuple[float, bool]]] = {}
        for stage, score, correct in observations:
            by_stage.setdefault(stage.value, []).append((score / 100.0, correct))

        for stage_name, points in by_stage.items():
            a, b = 0.0, 0.0
            for _ in range(iterations):
                grad_a = grad_b = 0.0
                for x, y in points:
                    prediction = 1.0 / (1.0 + math.exp(-(a * x + b)))
                    error = prediction - (1.0 if y else 0.0)
                    grad_a += error * x
                    grad_b += error
                a -= learning_rate * grad_a / len(points)
                b -= learning_rate * grad_b / len(points)
            self.coefficients[stage_name] = (a, b)

        self.fitted_on = source_label
        self.sample_size = len(observations)
        return self

    def confidence(self, stage: Stage, raw_score: float) -> float:
        """Return calibrated P(correct) in [0, 1].

        Raises:
            UnsetTunable: If the calibrator has not been fitted, or has no
                model for this stage. Never falls back to the raw score.
        """
        if not self.is_fitted:
            raise UnsetTunable(
                "The confidence calibrator has not been fitted. Per decisions.md "
                "D6, raw cascade scores must not be reported as confidence. Fit "
                "on scratch schemas first — see eval/fit_calibration.py."
            )
        if stage.value not in self.coefficients:
            raise UnsetTunable(
                f"No calibration model for stage '{stage.value}'. Fit on data "
                f"that includes decisions from that stage."
            )
        a, b = self.coefficients[stage.value]
        return round(1.0 / (1.0 + math.exp(-(a * (raw_score / 100.0) + b))), 6)

    def covered_stages(self) -> set[str]:
        """Stages this calibrator actually has a model for."""
        return set(self.coefficients)

    def apply(self, records: list[MappingRecord], strict: bool = True) -> set[str]:
        """Attach calibrated confidence to each mapped record, in place.

        Args:
            records: Mapping records to annotate.
            strict: Raise when a record's deciding stage has no fitted model.
                Set ``False`` during an ablation run, where a condition may use
                a stage the calibrator never observed — those records keep
                ``confidence = None``, which is honest, rather than borrowing
                another stage's curve, which would not be.

        Returns:
            The set of stage names skipped for want of a model. A non-empty
            result means ECE was computed on a subset, and the report must say so.
        """
        skipped: set[str] = set()
        for record in records:
            if not record.is_mapped():
                continue
            if record.deciding_stage.value not in self.coefficients:
                if strict:
                    raise UnsetTunable(
                        f"No calibration model for stage "
                        f"'{record.deciding_stage.value}'. Fit on data that "
                        f"includes decisions from that stage — see "
                        f"eval/fit_calibration.py --conditions."
                    )
                skipped.add(record.deciding_stage.value)
                continue
            record.confidence = self.confidence(
                record.deciding_stage, record.raw_score
            )
        return skipped

    def save(self, path: str | Path) -> None:
        """Persist the fitted model so a run can be reproduced exactly."""
        Path(path).write_text(
            json.dumps(
                {
                    "coefficients": {k: list(v) for k, v in self.coefficients.items()},
                    "fitted_on": self.fitted_on,
                    "sample_size": self.sample_size,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> Calibrator:
        """Load a previously fitted calibrator."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            coefficients={k: tuple(v) for k, v in data["coefficients"].items()},
            fitted_on=data.get("fitted_on"),
            sample_size=data.get("sample_size", 0),
        )


def reliability_bins(
    pairs: list[tuple[float, bool]], bins: int = 5
) -> list[dict[str, float]]:
    """Bin (confidence, correct) pairs for a reliability diagram.

    Args:
        pairs: Calibrated confidence and whether the mapping was correct.
        bins: Number of equal-width bins. methodology.md specifies 5, pooled
            across schemas — per-schema bins would be too sparse to mean
            anything.

    Returns:
        One dict per non-empty bin, with mean confidence, empirical accuracy,
        and count.
    """
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for confidence, correct in pairs:
        index = min(int(confidence * bins), bins - 1)
        buckets[index].append((confidence, correct))

    report = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        report.append(
            {
                "bin_lower": index / bins,
                "bin_upper": (index + 1) / bins,
                "count": len(bucket),
                "mean_confidence": round(sum(c for c, _ in bucket) / len(bucket), 6),
                "accuracy": round(sum(1 for _, y in bucket if y) / len(bucket), 6),
            }
        )
    return report


def expected_calibration_error(
    pairs: list[tuple[float, bool]], bins: int = 5
) -> float:
    """Compute ECE — Metric 3. Target ≤ 0.10.

    The count-weighted mean gap between stated confidence and observed accuracy.
    Zero means the stated probabilities are exactly borne out.
    """
    if not pairs:
        return 0.0
    total = len(pairs)
    return round(
        sum(
            (bucket["count"] / total)
            * abs(bucket["mean_confidence"] - bucket["accuracy"])
            for bucket in reliability_bins(pairs, bins)
        ),
        6,
    )


def derive_review_threshold(
    pairs: list[tuple[float, bool]], target_accuracy: float = 0.90
) -> dict[str, float | int] | None:
    """Lowest calibrated confidence at which accuracy reaches the target.

    The review rule (decisions.md): a mapping whose calibrated confidence is
    below the returned threshold goes to a human; at or above it, the system's
    own accuracy on the practice data is at least ``target_accuracy``.

    Args:
        pairs: ``(calibrated confidence, was correct)`` for every mapped record
            on the scratch schemas.
        target_accuracy: Accuracy that the auto-accepted set must reach.

    Returns:
        ``{"threshold", "accuracy", "accepted", "total"}`` for the lowest
        candidate threshold whose accepted set (confidence >= threshold) meets
        the target, or ``None`` if no threshold does. ``None`` means the
        cascade never reaches the target on this data, and the honest outcome
        is that everything needs review — not a lowered target.
    """
    if not pairs:
        return None
    total = len(pairs)
    for candidate in sorted({c for c, _ in pairs}):
        accepted = [ok for c, ok in pairs if c >= candidate]
        accuracy = sum(accepted) / len(accepted)
        if accuracy >= target_accuracy:
            return {
                "threshold": candidate,
                "accuracy": round(accuracy, 6),
                "accepted": len(accepted),
                "total": total,
            }
    return None
