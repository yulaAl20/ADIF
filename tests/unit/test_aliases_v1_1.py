"""Post-freeze alias correction (D65): v1.1 only removes supplier/vendor role aliases."""

from __future__ import annotations

import yaml

from src.cdm.registry import CdmRegistry
from src.config import load_config

CFG = load_config("config/default.yaml")
V10 = yaml.safe_load(open("cdm/aliases_v1.0.yaml", encoding="utf-8"))
V11 = yaml.safe_load(open("cdm/aliases_v1.1.yaml", encoding="utf-8"))
REMOVED = {"manufacturerName": {"supplier", "vendor"},
           "manufacturerOperatorId": {"supplier code", "vendor code", "supplier gln"}}


def test_v1_1_differs_from_frozen_v1_0_only_by_the_documented_removals():
    assert set(V10) == set(V11)
    for field in V10:
        assert set(V11[field]) <= set(V10[field])                    # nothing added
        assert set(V10[field]) - set(V11[field]) == REMOVED.get(field, set())


def test_frozen_v1_0_is_unchanged_and_still_used_by_default():
    assert "supplier gln" in V10["manufacturerOperatorId"]
    assert str(CFG.paths.alias_vocabulary).endswith("aliases_v1.0.yaml")


def test_v1_1_loads_and_no_longer_maps_a_supplier_gln_to_the_manufacturer():
    reg = CdmRegistry.load(CFG.paths.cdm_schema, "cdm/aliases_v1.1.yaml", CFG.normalisation)
    assert reg.resolve_alias("suppliergln") is None
    assert reg.resolve_alias("gln") == "manufacturerOperatorId"
