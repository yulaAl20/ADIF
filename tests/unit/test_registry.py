"""ADID v2 registry and resolver (D41, D45-D47, D51-D53)."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from src.registry.api import create_app
from src.registry.federation import Federation, RegistryNode, RootIndex
from src.registry.gs1 import digital_link, normalise_gtin
from src.registry.ids import AdidFormatError, new_adid, parse_adid, to_urn
from src.registry.policy import PUBLIC, AccessPolicy, Principal, Role
from src.registry.registration import register_rows
from src.registry.store import AltIdConflict, RegistryStore, RelationError
from src.registry.views import AccessDenied, dpp_view, lot_members, record_view

SCHEMA = json.load(open("cdm/cdm_v1.0.schema.json", encoding="utf-8"))
POLICY = AccessPolicy.load("config/registry.yaml")
AUTHORITY = Principal(Role.AUTHORITY, "customs")
OWNER = Principal(Role.REGISTRANT, "demoknit")

ROWS = [
    {"productFamily": "TS-1000", "productCategory": "T-shirt", "gtin": "5941234000013", "colour": "White",
     "size": "XS", "fibreComposition": "100% Cotton", "batchNumber": "DL-7700", "serialNumber": "SN001",
     "purchaseOrderReference": "PO-1", "facilityIdentifiers": "FAC-9", "manufacturerName": "Demo Knit"},
    {"productFamily": "TS-1000", "productCategory": "T-shirt", "gtin": "5941234000013", "colour": "White",
     "size": "XS", "fibreComposition": "100% Cotton", "batchNumber": "DL-7700", "serialNumber": "SN002",
     "manufacturerName": "Demo Knit"},
    {"productFamily": "TS-1000", "productCategory": "T-shirt", "gtin": "5941234010029", "colour": "Navy",
     "size": "M", "fibreComposition": "100% Cotton", "batchNumber": "DL-7701", "manufacturerName": "Demo Knit"},
]


def make_node(node_id: str = "lk-1", root: RootIndex | None = None, url: str = "http://node-a") -> RegistryNode:
    return RegistryNode(node_id, RegistryStore(":memory:", node_id), root or RootIndex(":memory:"),
                        POLICY, base_url=url)


@pytest.fixture
def node() -> RegistryNode:
    return make_node()


@pytest.fixture
def loaded(node):
    report = register_rows(node, ROWS, "demoknit", SCHEMA)
    return node, report


def path(node, adid):
    return node.store.get(adid).path


# ------------------------------------------------------------------ identifiers
def test_minted_ids_are_random_v4():
    a = new_adid()
    assert uuid.UUID(a).version == 4
    assert parse_adid(to_urn(a)) == a


@pytest.mark.parametrize("bad", [str(uuid.uuid1()), str(uuid.uuid5(uuid.NAMESPACE_URL, "x")), "ts-1000", ""])
def test_non_v4_identifiers_are_refused(bad):
    with pytest.raises(AdidFormatError):
        parse_adid(bad)


def test_gtin_normalisation_and_digital_link():
    assert normalise_gtin("5941234000013") == "05941234000013"
    assert normalise_gtin("5941234000014") is None
    assert digital_link("05941234000013", "SN1") == "https://id.gs1.org/01/05941234000013/21/SN1"


# -------------------------------------------------------------- v2 hierarchy
def test_registration_issues_three_levels_with_v2_paths(loaded):
    node, report = loaded
    assert dict(report.created) == {"family": 1, "variant": 2, "instance": 2}
    ids = report.row_adids[0]
    fam, var, inst = ids["family"], ids["variant"], ids["instance"]
    assert path(node, fam) == f"/adid/{fam}"
    assert path(node, var) == f"/adid/{fam}/white_xs"
    assert path(node, inst) == f"/adid/{fam}/white_xs/{inst}"
    assert node.store.get(var).metadata["variantId"] == var        # variant UUID exposed as metadata
    assert node.store.related(var, "variantOf") == [("variantOf", fam)]
    assert node.store.related(inst, "instanceOf") == [("instanceOf", var)]


def test_batch_is_data_not_identity(loaded):
    node, report = loaded
    assert node.store.count("batch") == 0
    inst = node.store.get(report.row_adids[0]["instance"])
    assert inst.metadata["batchNumber"] == "DL-7700"
    var = node.store.get(report.row_adids[2]["variant"])
    assert var.metadata["batchNumber"] == ["DL-7701"]                # unserialised: lots listed on the variant
    members = lot_members(node, "DL-7700", AUTHORITY)
    assert {m["kind"] for m in members} == {"instance"} and len(members) == 2
    with pytest.raises(AccessDenied):
        lot_members(node, "DL-7700", PUBLIC)


def test_attribute_correction_keeps_the_issued_path(loaded):
    node, report = loaded
    variant = report.row_adids[0]["variant"]
    before = path(node, variant)
    second = register_rows(node, [dict(ROWS[0], colour="Off White")], "demoknit", SCHEMA)
    assert second.row_adids[0]["variant"] == variant
    after = node.store.get(variant)
    assert after.path == before and after.metadata["colour"] == "Off White" and after.version > 1
    assert node.store.find("alias", "demoknit/ts-1000/white_xs") == variant
    assert node.store.verify(variant).ok


def test_reregistration_is_idempotent(loaded):
    node, _ = loaded
    count = node.store.count()
    again = register_rows(node, ROWS, "demoknit", SCHEMA)
    assert node.store.count() == count and not again.created


def test_path_and_alt_ids_are_unique(node):
    fam = node.register("family", "r1", {"productFamily": "A"}, [("family_code", "r1:a")], path="/adid/{self}")
    with pytest.raises(AltIdConflict):
        node.register("family", "r1", {"productFamily": "B"}, [("family_code", "r1:a")], path="/adid/{self}")
    node.register("variant", "r1", {"colour": "red", "size": "m"}, [], [("variantOf", fam)], path=f"/adid/{fam}/red_m")
    with pytest.raises(AltIdConflict):
        node.register("variant", "r1", {"colour": "red", "size": "m"}, [], [("variantOf", fam)], path=f"/adid/{fam}/red_m")


def test_relation_kind_rules(node):
    fam = node.register("family", "r1", {"productFamily": "A"}, path="/adid/{self}")
    var = node.register("variant", "r1", {}, relations=[("variantOf", fam)], path=f"/adid/{fam}/a_b")
    with pytest.raises(RelationError):
        node.register("variant", "r1", {}, relations=[("variantOf", var)])
    with pytest.raises(RelationError):
        node.register("family", "r1", {}, relations=[("instanceOf", var)])


def test_gs1_keys_go_to_the_root_index(loaded):
    node, report = loaded
    assert node.root.gs1("05941234000013") == report.row_adids[0]["variant"]
    assert node.root.gs1("05941234000013.SN001") == report.row_adids[0]["instance"]


# --------------------------------------------------------------- governance
def test_history_chain_detects_tampering(loaded):
    node, report = loaded
    variant = report.row_adids[0]["variant"]
    assert node.store.verify(variant).ok
    node.store._conn.execute("UPDATE entities SET metadata=json_set(metadata,'$.colour','Red') WHERE adid=?", (variant,))
    assert not node.store.verify(variant).ok


def test_path_is_covered_by_the_hash_chain(loaded):
    node, report = loaded
    fam = report.row_adids[0]["family"]
    node.store._conn.execute("UPDATE entities SET path='/adid/x' WHERE adid=?", (fam,))
    assert not node.store.verify(fam).ok


def test_withdrawal_keeps_a_tombstone(node):
    fam = node.register("family", "r1", {"productFamily": "A"}, path="/adid/{self}")
    node.store.set_status(fam, "withdrawn", "r1")
    assert "tombstone" in record_view(node, fam, PUBLIC)


# ------------------------------------------------------------------- access
def test_public_view_withholds_restricted_sections(loaded):
    node, report = loaded
    inst = report.row_adids[0]["instance"]
    public = dpp_view(node, inst, PUBLIC)
    assert "purchaseOrderReference" not in public and "batchNumber" not in public
    assert public["colour"] == "White" and public["productFamily"] == "TS-1000"     # inherited
    assert public["@id"].endswith(path(node, inst))
    assert dpp_view(node, inst, OWNER)["batchNumber"] == "DL-7700"
    assert "batchNumber" not in dpp_view(node, inst, Principal(Role.REGISTRANT, "someone-else"))
    assert dpp_view(node, inst, AUTHORITY)["purchaseOrderReference"] == "PO-1"


def test_public_relation_lists_hide_instances(loaded):
    node, report = loaded
    rels = record_view(node, report.row_adids[0]["variant"], PUBLIC)["relations"]
    assert "hasInstance" not in rels and "variantOf" in rels
    assert len(record_view(node, report.row_adids[0]["variant"], OWNER)["relations"]["hasInstance"]) == 2


def test_family_dpp_lists_every_variant(loaded):
    node, report = loaded
    assert len(dpp_view(node, report.row_adids[0]["family"], PUBLIC)["adid:hasVariant"]) == 2


def test_search_normalises_surface_forms(loaded):
    node, report = loaded
    assert node.store.search({"colour": "WHITE", "size": "xs"}, kinds=["variant"]) == [report.row_adids[0]["variant"]]
    assert len(node.store.search({"productFamily": "ts 1000"}, kinds=["variant"])) == 2


# ---------------------------------------------------------------------- API
@pytest.fixture
def client(loaded):
    node, report = loaded
    node.store.add_registrar("demoknit", "Demo Knit")
    return TestClient(create_app(node)), node, report


def test_api_resolves_each_level_by_path(client):
    c, node, report = client
    ids = report.row_adids[0]
    for level in ("family", "variant", "instance"):
        r = c.get(path(node, ids[level]))
        assert r.status_code == 200 and r.json()["kind"] == level
    r = c.get(path(node, ids["variant"]), headers={"Accept": "application/ld+json"})
    assert r.headers["content-type"].startswith("application/ld+json")


def test_api_bare_variant_uuid_redirects_to_its_path(client):
    c, node, report = client
    var = report.row_adids[0]["variant"]
    r = c.get(f"/adid/{var}", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == path(node, var)


def test_api_rejects_malformed_paths(client):
    c, *_ = client
    assert c.get("/adid/ts-1000").status_code == 400
    assert c.get(f"/adid/{uuid.uuid4()}/white").status_code == 400


def test_api_gs1_and_alias_redirect_to_paths(client):
    c, node, report = client
    r = c.get("/01/5941234000013", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == path(node, report.row_adids[0]["variant"])
    r = c.get("/01/05941234000013/21/SN002", follow_redirects=False)
    assert r.headers["location"] == path(node, report.row_adids[1]["instance"])
    assert c.get("/alias/demoknit/ts-1000/white_xs", follow_redirects=False).status_code == 303


def test_api_public_search_is_controlled(client):
    c, *_ = client
    assert c.get("/search", params={"kind": "instance"}).status_code == 403
    assert c.get("/search", params={"batchNumber": "DL-7700"}).status_code == 403
    r = c.get("/search", params={"productFamily": "TS-1000"})
    assert {x["kind"] for x in r.json()["results"]} <= {"family", "variant"}


def test_api_lot_query_needs_rights(client):
    c, node, _ = client
    assert c.get("/lot/DL-7700").status_code == 403
    key = node.store.add_registrar("customs", "Customs", Role.AUTHORITY)
    r = c.get("/lot/DL-7700", headers={"X-ADIR-Key": key})
    assert r.status_code == 200 and r.json()["count"] == 2


def test_api_writes_need_the_owners_key(client):
    c, node, report = client
    variant = report.row_adids[0]["variant"]
    assert c.patch(f"/entities/{variant}", json={"changes": {"colour": "Red"}}).status_code == 401
    intruder = node.store.add_registrar("other", "Other")
    assert c.patch(f"/entities/{variant}", json={"changes": {"colour": "Red"}},
                   headers={"X-ADIR-Key": intruder}).status_code == 403


def test_api_create_family_variant_instance(client):
    c, node, _ = client
    key = node.store.add_registrar("maker2", "Maker 2")
    h = {"X-ADIR-Key": key}
    fam = c.post("/entities", json={"kind": "family", "metadata": {"productFamily": "Z"}}, headers=h).json()
    var = c.post("/entities", json={"kind": "variant", "metadata": {"colour": "Red", "size": "L"},
                                    "relations": [["variantOf", fam["adid"]]]}, headers=h).json()
    inst = c.post("/entities", json={"kind": "instance", "metadata": {"serialNumber": "Z1"},
                                     "relations": [["instanceOf", var["adid"]]]}, headers=h).json()
    assert var["path"] == f"/adid/{fam['adid']}/red_l"
    assert inst["path"] == f"{var['path']}/{inst['adid']}"
    c.post(f"/entities/{fam['adid']}/status", json={"status": "withdrawn"}, headers=h)
    assert c.get(fam["path"]).status_code == 410


# --------------------------------------------------------------- federation
def test_cross_node_resolution_and_family_migration():
    root = RootIndex(":memory:")
    a, b = make_node("lk-1", root, "http://node-a"), make_node("eu-1", root, "http://node-b")
    fed = Federation(root)
    fed.add(a), fed.add(b)
    rep = register_rows(b, ROWS, "brand", SCHEMA)
    fam, var, inst = (rep.row_adids[0][k] for k in ("family", "variant", "instance"))
    vpath = b.store.get(var).path
    r = TestClient(create_app(a)).get(vpath, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == f"http://node-b{vpath}"
    fed.move(fam, "lk-1")                                        # the whole family moves together
    for x in (fam, var, inst):
        node_id, entity = fed.resolve(x)
        assert node_id == "lk-1" and a.store.verify(x).ok
    assert a.store.get(var).path == vpath                         # no path changed
    assert TestClient(create_app(a)).get(vpath).status_code == 200


def test_gateway_register_endpoint(monkeypatch):
    import src.api.main as gateway
    node = make_node()
    key = node.store.add_registrar("demoknit", "Demo Knit")
    monkeypatch.setattr(gateway, "get_registry_node", lambda: node)
    c = TestClient(gateway.app)
    up = c.post("/upload?manufacturer_id=demoknit",
                files={"file": ("s.csv", open("demo/demo_knitwear_export_spring.csv", "rb"))}).json()
    assert c.post(f"/register/{up['upload_id']}").status_code == 401
    r = c.post(f"/register/{up['upload_id']}", headers={"X-ADIR-Key": key}).json()
    assert r["created"]["family"] >= 1 and r["created"]["variant"] >= 1


def test_registry_evaluation_harness_runs(tmp_path):
    """The E1-E8 harness runs end to end at toy scale and finds no failures."""
    from eval.registry_eval import Study, scalability
    study = Study(tmp_path, seed=7, models=2, serials=1)
    study.load()
    assert study.uniqueness()["duplicate_adids"] == 0
    assert study.resolvability(http_sample=20)["adid_resolution_rate"] == 1.0
    assert study.privacy(guesses=100)["restricted_field_or_relation_leaks"] == 0
    assert study.stability()["v2_path_unchanged_rate"] == 1.0
    assert study.governance(per_type=3, clean_sample=10)["false_positive_rate"] == 0.0
    assert scalability([100], seed=7)[0]["entities"] > 0
