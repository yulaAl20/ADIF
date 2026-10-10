"""End-to-end complete passport demonstration (D60)."""

from __future__ import annotations

import json

from eval.e2e_passport_demo import mandatory_for, run
from src.registry.registration import coerce_types

SCHEMA = json.load(open("cdm/cdm_v1.0.schema.json", encoding="utf-8"))


def test_every_issued_passport_passes_every_check():
    record = run()
    levels = {p["level"] for p in record["step4_passports"]}
    assert levels == {"family", "variant", "instance"}
    assert record["all_passed"], [p for p in record["step4_passports"] if not p["passed"]]


def test_mandatory_set_depends_on_level():
    assert set(mandatory_for("family", SCHEMA)) == {"productFamily", "manufacturerOperatorId"}
    assert set(mandatory_for("variant", SCHEMA)) == set(SCHEMA["required"])
    assert set(mandatory_for("instance", SCHEMA)) == set(SCHEMA["required"])


def test_numeric_fields_are_coerced_and_bad_numbers_left_for_the_validator():
    out = coerce_types({"carbonFootprint": "4,2", "netWeight": "0.18"}, SCHEMA)
    assert out["carbonFootprint"] == 4.2 and out["netWeight"] == "0.18"   # netWeight is a string field
    assert coerce_types({"carbonFootprint": "n/a"}, SCHEMA)["carbonFootprint"] == "n/a"
