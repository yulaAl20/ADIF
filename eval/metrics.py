"""Evaluation metrics and the ablation ladder (M14, FR-14.1 to FR-14.8).

The four metrics from methodology.md, plus the ablation runner that measures
each condition with all four on the same schemas (decisions.md D10).

**This module computes. It does not decide.** Two definitional questions are
deliberately left as explicit parameters rather than baked in, because they
belong in methodology.md where an examiner can find them argued:

*Demoted conflicts.* When two columns claim one CDM field, the loser is
demoted to ``NO_MAPPING``. Whether that counts as a false positive or a correct
rejection changes F1, and it is a research decision, not an implementation
detail. ``count_demoted_as_fp`` exposes it. Log the choice as D21.

*Stage attribution.* ``stage_hits`` counts every stage acceptance, including
ones later demoted. :func:`surviving_stage_hits` counts only those that
survived. Report which you used.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.matching.arbitration import MappingResult
from src.matching.confidence import expected_calibration_error, reliability_bins
from src.matching.models import NO_MAPPING, Stage
from src.templates.store import ReuseOutcome

__all__ = [
    "MetricSet",
    "ablation_delta",
    "mandatory_coverage_ceiling",
    "mandatory_match_rate",
    "mapping_f1",
    "reciprocal_rank",
    "review_burden",
    "surviving_stage_hits",
    "write_run_record",
]


@dataclass
class MetricSet:
    """All four metrics for one condition on one schema."""

    schema: str
    condition: str
    precision: float
    recall: float
    f1: float
    mandatory_match_rate: float
    mandatory_coverage_ceiling: float
    ece: float | None
    template_reuse_rate: float | None
    review_burden: float
    mean_reciprocal_rank: float
    mapped: int
    total_columns: int


def mapping_f1(
    result: MappingResult,
    ground_truth: dict[str, str],
    count_demoted_as_fp: bool = False,
) -> tuple[float, float, float]:
    """Metric 1 — precision, recall and F1 at field-mapping level.

    Definitions follow methodology.md: TP is a correct canonical target
    proposed, FP a wrong target proposed, FN a mappable field missed.

    Args:
        result: The cascade output.
        ground_truth: Raw header to correct CDM field. Use ``NO_MAPPING`` for
            headers that legitimately have no target, so distractor columns are
            scored rather than ignored.
        count_demoted_as_fp: Whether a conflict-demoted record counts as a false
            positive. See the module docstring — this is D21's question.

    Returns:
        ``(precision, recall, f1)``, each rounded to six places.
    """
    tp = fp = fn = 0
    for record in result.records:
        expected = ground_truth.get(record.raw_header)
        if expected is None:
            continue
        proposed = record.target_field
        if proposed == NO_MAPPING:
            if expected != NO_MAPPING:
                fn += 1
                if record.conflict_flagged and count_demoted_as_fp:
                    fp += 1
        elif proposed == expected:
            tp += 1
        else:
            fp += 1
            if expected != NO_MAPPING:
                fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return round(precision, 6), round(recall, 6), round(f1, 6)


def mandatory_match_rate(
    result: MappingResult,
    mandatory_fields: list[str],
    ground_truth: dict[str, str] | None = None,
) -> float:
    """Metric 2 — ESPR-mandatory field match rate.

    methodology.md defines this as the proportion of the reference attribute set
    correctly populated, **restricted to fields the source schema actually has
    data for**. That restriction matters: an ERPNext export contains no EORI
    column, and penalising the system for failing to map a field that is not
    present measures the data, not the artefact.

    The gold standard operationalises "has data for" — a mandatory field is in
    the denominator only if the ground truth maps some column to it.

    Args:
        result: The cascade output.
        mandatory_fields: Mandatory CDM field names.
        ground_truth: Raw header to correct CDM field. When omitted the rate is
            computed against ALL mandatory fields, which is the unrestricted
            figure — report it as such, never as Metric 2.

    Returns:
        The restricted rate, or 1.0 when the schema contains none of the
        mandatory fields (there was nothing to find, so nothing was missed).
    """
    if not mandatory_fields:
        return 1.0
    claimed = {r.target_field for r in result.records if r.is_mapped()}

    if ground_truth is None:
        return round(
            sum(1 for f in mandatory_fields if f in claimed) / len(mandatory_fields), 6
        )

    available = [f for f in mandatory_fields if f in set(ground_truth.values())]
    if not available:
        return 1.0

    correct = 0
    for field in available:
        expected_headers = {h for h, v in ground_truth.items() if v == field}
        if any(
            r.target_field == field and r.raw_header in expected_headers
            for r in result.records
        ):
            correct += 1
    return round(correct / len(available), 6)


def mandatory_coverage_ceiling(
    mandatory_fields: list[str], ground_truth: dict[str, str]
) -> float:
    """The highest Metric 2 an unrestricted calculation could reach on this schema.

    Reported alongside the restricted rate because the ceiling is itself a
    finding: if a schema contains only two of four mandatory fields, no system
    can score above 50% on the unrestricted measure, and that says something
    about SME data completeness rather than about the artefact.
    """
    if not mandatory_fields:
        return 1.0
    present = set(ground_truth.values())
    return round(sum(1 for f in mandatory_fields if f in present) / len(mandatory_fields), 6)


def template_reuse_rate(outcome: ReuseOutcome) -> float:
    """Metric 4 — reuse on a *drifted* upload, never an identical one (D8)."""
    return outcome.reuse_rate()


def review_burden(result: MappingResult, threshold: float | None = None) -> float:
    """Fraction of columns routed to manual review (decisions.md D16).

    Args:
        result: The cascade output.
        threshold: Calibrated-confidence acceptance threshold. When given, any
            mapped record below it also counts toward the burden.

    Returns:
        The share of columns a human would have to decide.
    """
    if not result.records:
        return 0.0
    burden = 0
    for record in result.records:
        if record.review_required:
            burden += 1
        elif threshold is not None and record.confidence is not None:
            if record.confidence < threshold:
                burden += 1
    return round(burden / len(result.records), 6)


def reciprocal_rank(result: MappingResult, ground_truth: dict[str, str]) -> float:
    """Mean reciprocal rank of the correct target in the candidate list (FR-14.7).

    Answers a question F1 cannot: when the top choice is wrong, was the right
    answer second, or absent entirely? A reviewer picking from a dropdown cares
    a great deal about the difference.
    """
    scores: list[float] = []
    for record in result.records:
        expected = ground_truth.get(record.raw_header)
        if expected is None or expected == NO_MAPPING:
            continue
        if record.target_field == expected:
            scores.append(1.0)
            continue
        rank = next(
            (i + 2 for i, c in enumerate(record.alternatives) if c.cdm_field == expected),
            None,
        )
        scores.append(1.0 / rank if rank else 0.0)
    return round(sum(scores) / len(scores), 6) if scores else 0.0


def surviving_stage_hits(result: MappingResult) -> dict[str, int]:
    """Per-stage counts of decisions that survived conflict resolution.

    ``result.stage_hits`` counts every acceptance including demoted ones. The
    two differ exactly when a conflict occurred, and the ablation should state
    which it reports.
    """
    counts = {s.value: 0 for s in Stage}
    for record in result.records:
        if record.is_mapped():
            counts[record.deciding_stage.value] += 1
    return {k: v for k, v in counts.items() if v}


def ablation_delta(ladder: list[MetricSet]) -> list[dict[str, Any]]:
    """Report ΔF1 between consecutive ablation rungs (D10).

    Attributes gain to each added stage rather than lumping the whole cascade
    against a single strawman.
    """
    deltas = []
    for previous, current in zip(ladder, ladder[1:]):
        deltas.append(
            {
                "from": previous.condition,
                "to": current.condition,
                "schema": current.schema,
                "delta_f1": round(current.f1 - previous.f1, 6),
                "delta_review_burden": round(
                    current.review_burden - previous.review_burden, 6
                ),
            }
        )
    if len(ladder) >= 2:
        deltas.append(
            {
                "from": ladder[0].condition,
                "to": ladder[-1].condition,
                "schema": ladder[-1].schema,
                "delta_f1": round(ladder[-1].f1 - ladder[0].f1, 6),
                "delta_review_burden": round(
                    ladder[-1].review_burden - ladder[0].review_burden, 6
                ),
            }
        )
    return deltas


def write_run_record(
    directory: str | Path,
    metrics: list[MetricSet],
    provenance: dict[str, Any],
    status: str = "EXPLORATORY",
    calibration_pairs: list[tuple[float, bool]] | None = None,
) -> Path:
    """Persist a run record with full provenance (FR-14.5).

    ``status`` defaults to ``EXPLORATORY``. Only set it to ``EVALUATION`` when
    the run used the frozen CDM, grid-searched thresholds and a fitted
    calibrator — that is, when the numbers are actually citable.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"eval_{stamp}.json"

    payload: dict[str, Any] = {
        "status": status,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metrics": [asdict(m) for m in metrics],
        "ablation_deltas": ablation_delta(metrics),
        "provenance": provenance,
    }
    if calibration_pairs:
        payload["ece"] = expected_calibration_error(calibration_pairs)
        payload["reliability_bins"] = reliability_bins(calibration_pairs)

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
