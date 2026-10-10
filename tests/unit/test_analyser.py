"""M2 schema analyser tests — FR-2.x."""

from __future__ import annotations

import pandas as pd

from src.analyser.normalise import normalise_header, split_camel_case
from src.analyser.profile import analyse_frame, infer_datatype
from src.config import load_config

CFG = load_config("config/default.yaml")
NORM = CFG.normalisation


def test_separator_variants_collapse_to_one_alias_key():
    """The point of normalisation: these must all hit the same alias entry."""
    keys = {
        normalise_header(h, NORM).compact
        for h in ["Product_Name", "product-name", "PRODUCT NAME", "productName", "Product.Name"]
    }
    assert keys == {"productname"}


def test_acronym_boundaries_split_correctly():
    assert split_camel_case("GTINCode") == "GTIN Code"
    assert split_camel_case("baseColour") == "base Colour"


def test_abbreviations_expand_per_token():
    cfg = NORM.model_copy(update={"abbreviations": {"qty": "quantity"}})
    assert normalise_header("qty_ordered", cfg).normalised == "quantity ordered"
    assert normalise_header("quantity", cfg).normalised == "quantity"


def test_stopword_removal_never_empties_a_header():
    cfg = NORM.model_copy(update={"stopwords": ["of", "the"]})
    assert normalise_header("of_the", cfg).compact == "ofthe"
    assert normalise_header("unit_of_measure", cfg).normalised == "unit measure"


def test_datatype_inference():
    assert infer_datatype(["1", "2", "3"], CFG) == "integer"
    assert infer_datatype(["1.5", "2.0"], CFG) == "float"
    assert infer_datatype(["2024-01-05", "2023-11-30"], CFG) == "date"
    assert infer_datatype(["yes", "no", "yes"], CFG) == "boolean"
    assert infer_datatype(["Navy", "Red"], CFG) == "string"
    assert infer_datatype([], CFG) == "unknown"


def test_binary_integers_are_not_read_as_boolean():
    assert infer_datatype(["0", "1", "1", "0"], CFG) == "integer"


def test_disagreeing_column_is_labelled_mixed_not_guessed():
    assert infer_datatype(["1", "Navy", "2024-01-05", "true", "x"], CFG) == "mixed"


def test_duplicate_and_empty_headers_are_resolved():
    frame = pd.DataFrame([["a", "b", "c"]], columns=["size", "size", ""])
    analysis = analyse_frame(frame, CFG)
    assert analysis.headers() == ["size", "size_1", "col_2"]
    assert analysis.duplicate_headers_renamed == ["size"]
    assert analysis.empty_headers_named == ["col_2"]


def test_profile_reports_nulls_and_ranges():
    frame = pd.DataFrame({"price": ["10.5", None, "30.0", ""]})
    col = analyse_frame(frame, CFG).columns[0]
    assert col.null_rate == 0.5
    assert col.numeric_min == 10.5
    assert col.numeric_max == 30.0
    assert col.distinct_count == 2


def test_sampling_is_deterministic_and_ordered():
    """NFR-5: same input, same output. Never a random sample."""
    frame = pd.DataFrame({"c": [str(i) for i in range(100)]})
    first = analyse_frame(frame, CFG).columns[0].sample_values
    second = analyse_frame(frame, CFG).columns[0].sample_values
    assert first == second
    assert first == [str(i) for i in range(CFG.ingestion.sample_values_per_column)]


def test_raw_header_is_retained_alongside_normalised():
    frame = pd.DataFrame([["x"]], columns=["Fabric_Composition"])
    col = analyse_frame(frame, CFG).columns[0]
    assert col.raw_header == "Fabric_Composition"
    assert col.normalised_header == "fabric composition"
    assert col.compact_header == "fabriccomposition"
