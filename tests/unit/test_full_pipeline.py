"""Tests for M6, M7, M9, M10, M11, M12, M14."""

from __future__ import annotations

import pytest

from eval.metrics import (
    mapping_f1,
    reciprocal_rank,
    review_burden,
    surviving_stage_hits,
)
from src.cdm.registry import CdmRegistry
from src.config import UnsetTunable, load_config
from src.identity.adid import AdidError, AdidIdentifier, slugify
from src.matching.confidence import Calibrator, expected_calibration_error
from src.matching.models import NO_MAPPING, MappingRecord, Stage
from src.matching.stage4_value import SignatureLibrary, gtin_check_digit_valid
from src.templates.store import TemplateStore
from src.validation.validator import build_context, serialise_jsonld, validate_record

BASE = load_config("config/default.yaml")
REG = CdmRegistry.load(
    "tests/fixtures/cdm_test.schema.json", "tests/fixtures/aliases_test.yaml", BASE.normalisation
)


# --- M6 value-based --------------------------------------------------------

def test_gtin_check_digit():
    assert gtin_check_digit_valid("0012345678905") is True
    assert gtin_check_digit_valid("0012345678904") is False
    assert gtin_check_digit_valid("notanumber") is False


def test_value_signatures_rescue_an_uninformative_header():
    """The whole point of M6: col_7 is invisible to header-based stages."""
    from src.analyser.profile import analyse_frame
    import pandas as pd

    lib = SignatureLibrary.load("cdm/vocabularies/signatures.yaml")
    frame = pd.DataFrame({"col_7": ["LK", "IN", "BD", "VN"]})
    column = analyse_frame(frame, BASE).columns[0]
    top = lib.match(column)[0]
    assert top.cdm_field == "countryOfOrigin"
    assert top.raw_score == 100.0


def test_partial_conformance_scores_partially():
    from src.analyser.profile import analyse_frame
    import pandas as pd

    lib = SignatureLibrary.load("cdm/vocabularies/signatures.yaml")
    frame = pd.DataFrame({"c": ["LK", "IN", "zzz", "qqq"]})
    column = analyse_frame(frame, BASE).columns[0]
    country = next(c for c in lib.match(column) if c.cdm_field == "countryOfOrigin")
    assert country.raw_score == 50.0


# --- M7 confidence ---------------------------------------------------------

def test_unfitted_calibrator_refuses_to_report_confidence():
    """D6: raw scores are never confidence."""
    with pytest.raises(UnsetTunable, match="D6"):
        Calibrator().confidence(Stage.FUZZY, 90.0)


def test_calibrator_learns_from_observations():
    observations = (
        [(Stage.FUZZY, 95.0, True)] * 40
        + [(Stage.FUZZY, 55.0, False)] * 40
    )
    cal = Calibrator().fit(observations, "unit-test")
    assert cal.confidence(Stage.FUZZY, 95.0) > cal.confidence(Stage.FUZZY, 55.0)
    assert 0.0 <= cal.confidence(Stage.FUZZY, 95.0) <= 1.0


def test_calibrator_round_trips(tmp_path):
    cal = Calibrator().fit([(Stage.ALIAS, 100.0, True)] * 10, "unit-test")
    path = tmp_path / "cal.json"
    cal.save(path)
    assert Calibrator.load(path).coefficients == cal.coefficients


def test_perfect_calibration_has_zero_ece():
    pairs = [(0.9, True)] * 9 + [(0.9, False)]
    assert expected_calibration_error(pairs) == pytest.approx(0.0, abs=1e-6)


# --- M9 templates ----------------------------------------------------------

def _record(header, target, position=0):
    return MappingRecord(
        source_position=position, raw_header=header, normalised_header=header,
        target_field=target, deciding_stage=Stage.ALIAS, raw_score=100.0,
    )


def test_template_versions_are_append_only(tmp_path):
    store = TemplateStore(tmp_path / "t.sqlite")
    store.save("mfr", [_record("a", "colour")])
    store.save("mfr", [_record("a", "size")])
    assert store.versions("mfr") == [1, 2]
    assert store.latest("mfr").mappings == {"a": "size"}


def test_drifted_upload_reports_reuse_and_drift_separately(tmp_path):
    """D8: an identical re-upload proves nothing; drift is the real test."""
    store = TemplateStore(tmp_path / "t.sqlite")
    template = store.save(
        "mfr", [_record("colour", "colour", 0), _record("dropped", "size", 1)]
    )
    fresh = [_record("colour", NO_MAPPING, 0), _record("brand_new", NO_MAPPING, 1)]
    outcome = TemplateStore.apply(template, fresh)
    assert outcome.reused == ["colour"]
    assert outcome.drifted_missing == ["dropped"]
    assert outcome.new_columns == ["brand_new"]
    assert outcome.reuse_rate() == 0.5
    assert fresh[0].deciding_stage is Stage.TEMPLATE


# --- M10 / M12 validation and JSON-LD --------------------------------------

def test_validation_collects_every_problem_in_one_pass():
    report = validate_record({"colour": "Navy"}, REG, "cdm/vocabularies/signatures.yaml")
    assert report.is_valid is False
    assert set(report.missing_mandatory) == {"productFamily", "productIdentifier", "fibreComposition"}


def test_vocabulary_violation_is_reported():
    report = validate_record(
        {"productFamily": "F", "productIdentifier": "1", "fibreComposition": "x", "countryOfOrigin": "ZZZ"},
        REG, "cdm/vocabularies/signatures.yaml",
    )
    assert any("countryOfOrigin" in e for e in report.vocabulary_errors)


def test_context_is_generated_from_the_cdm_so_it_cannot_drift():
    context = build_context(REG, "https://x/ns#")
    assert set(REG.names()).issubset(context)


def test_jsonld_carries_adid_identity_and_cdm_data_separately():
    identifier = AdidIdentifier("acme", "Top A", "Navy", "M")
    doc = serialise_jsonld({"colour": "Navy", "size": "M"}, identifier, REG)
    assert doc["@id"] == "https://dpp.acme/adid/top-a/navy_m"
    assert doc["adid:level"] == "variant"
    assert doc["adid:parent"].endswith("/adid/top-a")
    assert doc["colour"] == "Navy"


# --- M11 ADID --------------------------------------------------------------

def test_adid_levels_by_depth():
    assert AdidIdentifier("m", "F").level == "family"
    assert AdidIdentifier("m", "F", "Navy", "M").level == "variant"
    assert AdidIdentifier("m", "F", "Navy", "M", "SN1").level == "instance"


def test_hyphenated_colour_survives_the_composite_variant_segment():
    """Underscore joins the two dimensions precisely so this splits correctly."""
    a = AdidIdentifier("m", "Top A", "Navy Blue", "XL")
    assert a.variant_key == "navy-blue_xl"
    assert AdidIdentifier.parse(a.path()).colour == "navy-blue"


def test_half_specified_variant_is_rejected():
    with pytest.raises(AdidError, match="Supply both or neither"):
        AdidIdentifier("m", "F", "Navy", None)


def test_instance_without_a_variant_is_rejected():
    with pytest.raises(AdidError, match="instance-level"):
        AdidIdentifier("m", "F", None, None, "SN1")


def test_unparseable_segment_is_rejected():
    with pytest.raises(AdidError):
        slugify("!!!")


def test_adid_round_trips():
    original = AdidIdentifier("m", "Top A", "Navy", "M", "SN-1")
    parsed = AdidIdentifier.parse(original.path(), "m")
    assert parsed.path() == original.path()


# --- M14 metrics -----------------------------------------------------------

class _Result:
    def __init__(self, records):
        self.records = records


def test_f1_scores_distractors_and_misses():
    records = [
        _record("a", "colour", 0),
        _record("b", "size", 1),
        _record("c", NO_MAPPING, 2),
    ]
    truth = {"a": "colour", "b": "countryOfOrigin", "c": "carbonFootprint"}
    precision, recall, f1 = mapping_f1(_Result(records), truth)
    assert precision == pytest.approx(0.5)
    assert recall == pytest.approx(1 / 3)
    assert 0 < f1 < 1


def test_review_burden_counts_low_confidence_as_burden():
    high = _record("a", "colour"); high.confidence = 0.95
    low = _record("b", "size"); low.confidence = 0.20
    assert review_burden(_Result([high, low]), threshold=0.8) == 0.5


def test_surviving_hits_exclude_demoted_records():
    kept = _record("a", "colour")
    demoted = _record("b", NO_MAPPING); demoted.conflict_flagged = True
    assert surviving_stage_hits(_Result([kept, demoted])) == {"alias": 1}


def test_mrr_rewards_a_correct_second_choice():
    from src.matching.models import Candidate

    record = _record("a", "size")
    record.alternatives = [Candidate(cdm_field="colour", raw_score=80, stage=Stage.FUZZY)]
    assert reciprocal_rank(_Result([record]), {"a": "colour"}) == pytest.approx(0.5)


def test_family_must_not_be_derived_from_a_gtin():
    """D9: a GTIN identifies one colour+size combination, never a design.

    Using it as the family would make every variant its own family and collapse
    the very hierarchy ADID exists to supply.
    """
    import io
    from fastapi.testclient import TestClient
    import src.api.main as api

    cfg = api.get_config()
    cfg.matching.stages.fuzzy.threshold = 85.0
    cfg.matching.stages.semantic.threshold = 99.0
    client = TestClient(api.app)

    csv = b"GTIN,baseColour,SIZE,composition\n0012345678905,Navy,M,80% Cotton\n"
    up = client.post("/upload", files={"file": ("a.csv", io.BytesIO(csv), "text/csv")}).json()
    r = client.post(f"/dpp/{up['upload_id']}?row=0")
    assert r.status_code == 422
    assert "D9" in r.json()["detail"]
