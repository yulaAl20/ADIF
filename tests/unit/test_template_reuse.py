"""Metric 4's definition, pinned (D8; methodology.md §4.2).

These tests fix what "template reuse rate" and "delta-field F1" mean, so a
later edit cannot quietly change the metric Chapter 5 reports.
"""

from __future__ import annotations

from eval.run_template_reuse import score_reuse
from src.matching.models import NO_MAPPING, MappingRecord, Stage


def _rec(header: str, target: str, stage: Stage) -> MappingRecord:
    return MappingRecord(
        source_position=0,
        raw_header=header,
        normalised_header=header.lower(),
        target_field=target,
        deciding_stage=stage,
        raw_score=100.0,
    )


ORIGINAL = {"colour", "size", "brand", "item_code"}

DRIFT_GOLD = {
    "colour": "colour",
    "size": "size",
    "brand": NO_MAPPING,            # unchanged but unmappable: not the template's business
    "itemCode": "productIdentifier",  # renamed: a delta column
    "fibre_mix": "fibreComposition",  # new: a delta column
}


def test_reuse_rate_counts_only_correct_template_decisions_on_unchanged_mappable_columns():
    records = [
        _rec("colour", "colour", Stage.TEMPLATE),        # correct, automatic
        _rec("size", "size", Stage.ALIAS),               # correct, but NOT reused
        _rec("brand", NO_MAPPING, Stage.NONE),
        _rec("itemCode", "productIdentifier", Stage.FUZZY),
        _rec("fibre_mix", "colour", Stage.SEMANTIC),     # wrong
    ]
    s = score_reuse(ORIGINAL, records, DRIFT_GOLD)

    assert s.unchanged_mappable == 2
    assert s.unchanged_unmappable == 1
    assert s.reused_correct == 1
    assert s.reuse_rate == 0.5, "a correct cascade hit on an unchanged column is not reuse"


def test_delta_f1_scores_only_headers_new_in_the_drifted_file():
    records = [
        _rec("colour", "colour", Stage.TEMPLATE),
        _rec("size", "size", Stage.TEMPLATE),
        _rec("brand", NO_MAPPING, Stage.NONE),
        _rec("itemCode", "productIdentifier", Stage.FUZZY),  # TP
        _rec("fibre_mix", "colour", Stage.SEMANTIC),         # FP + FN
    ]
    s = score_reuse(ORIGINAL, records, DRIFT_GOLD)

    assert s.reuse_rate == 1.0
    assert s.delta_columns == 2 and s.delta_mappable == 2
    assert s.delta_precision == 0.5
    assert s.delta_recall == 0.5
    assert s.delta_f1 == 0.5


def test_no_delta_columns_reports_none_rather_than_a_perfect_score():
    records = [_rec("colour", "colour", Stage.TEMPLATE)]
    s = score_reuse({"colour"}, records, {"colour": "colour"})
    assert s.delta_f1 is None, "nothing to re-match must not read as F1 = 1.0"
