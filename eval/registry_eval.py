"""ADID v2 registry evaluation harness (decisions.md D47; ADID v2 = D51, proposed post-freeze).

Evaluates the *registry*, not the matching cascade. The cascade's evaluation
(D34) is frozen and unaffected. Eight properties, as the supervisor's brief
lists them; each is defined here before any number exists, and each run record
carries the definitions with the results.

    E1 uniqueness           minted ADIDs and bound GS1 keys are unique
    E2 resolvability        every ADID / GTIN / SGTIN / alias reaches the right entity,
                            locally and across nodes; HTTP latency
    E3 discovery accuracy   precision / recall of related-product queries against
                            generator ground truth; registry search vs exact-string baseline
    E4 identifier stability attribute corrections and infrastructure changes:
                            ADID v2 paths vs the frozen v1.0 path ADID
    E5 interoperability     JSON-LD expansion (pyld), GS1 Digital Link syntax,
                            CDM schema validity of passports
    E6 scalability          registration throughput, resolve / search latency and
                            storage per entity at increasing registry sizes
    E7 privacy              restricted-field leaks, enumerability, identifier content
    E8 governance           tamper detection rate and false-positive rate

**Data is synthetic** (seeded, reproducible). It is generated with the surface
noise real exports show — "Navy Blue", "NAVY_BLUE", "navyblue" — so discovery is
not measured on clean strings, but it is not manufacturer data and the thesis
must say so. Ground truth comes from the generator, not from the system.

    python -m eval.registry_eval                      # default scale
    python -m eval.registry_eval --models 60 --sizes 1000 10000 50000
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from src.identity.adid import AdidIdentifier, slugify
from src.registry.api import create_app
from src.registry.federation import Federation, RegistryNode, RootIndex
from src.registry.gs1 import normalise_gtin, sgtin_key
from src.registry.ids import parse_adid, to_uri
from src.registry.policy import PUBLIC, AccessPolicy, Principal, Role
from src.registry.registration import register_rows
from src.registry.store import FACET_FIELDS, RegistryStore, normalise_facet
from src.registry.views import AccessDenied, dpp_view, lot_members, record_view
from src.validation.validator import validate_record

CDM_SCHEMA = Path("cdm/cdm_v1.0.schema.json")
CDM_CONTEXT = Path("cdm/cdm_v1.0.context.jsonld")
POLICY_PATH = Path("config/registry.yaml")

COLOURS = ["Navy", "Sand", "Black", "White", "Olive Green", "Sky Blue", "Charcoal Grey", "Maroon"]
SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
CATEGORIES = ["T-shirt", "Polo shirt", "Hoodie", "Dress", "Trousers", "Shorts"]
CORRECTIONS = {"Navy": "Navy Blue", "Sand": "Sand Beige", "Black": "Jet Black", "White": "Off White",
               "Olive Green": "Olive", "Sky Blue": "Light Blue", "Charcoal Grey": "Charcoal",
               "Maroon": "Burgundy"}
SIZE_CORRECTIONS = {"XS": "Extra Small", "S": "Small", "M": "Medium", "L": "Large", "XL": "X-Large", "XXL": "2XL"}
DL_PATTERN = re.compile(r"^https://id\.gs1\.org/01/\d{14}(/21/[\x21-\x7e]{1,20})?$")


# --------------------------------------------------------------------- data
def gtin13(body12: str) -> str:
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body12)))
    return body12 + str((10 - total % 10) % 10)


SPELLING = {"Grey": "Gray"}  # a vocabulary variant surface normalisation cannot fix


def noisy(value: str, rng: random.Random) -> str:
    """One of the forms real exports use for the same value.

    Six are *surface* variants (case, separators) that the registry normaliser is
    designed to absorb — so recall on those is partly by construction. One is a
    *vocabulary* variant (British/American spelling) that it is not designed
    to absorb, kept so the measurement can fail.
    """
    forms = [value, value, value.upper(), value.lower(), value.replace(" ", "-"),
             value.replace(" ", "_").upper(), value.replace(" ", "").lower()]
    out = rng.choice(forms)
    if rng.random() < 0.15:
        for a, b in SPELLING.items():
            out = out.replace(a, b).replace(a.upper(), b.upper()).replace(a.lower(), b.lower())
    return out


def generate(seed: int, registrars: list[str], models: int, serials: int) -> tuple[dict[str, list[dict]], dict]:
    """Rows per registrar plus ground truth keyed by GTIN / serial."""
    rng = random.Random(seed)
    rows: dict[str, list[dict]] = defaultdict(list)
    truth: dict[str, Any] = {"variant": {}, "model_variants": defaultdict(set), "batch_items": defaultdict(set),
                             "model_of_gtin": {}}
    counter = 0
    for r_index, registrar in enumerate(registrars):
        for m in range(models):
            family = f"{registrar[:3].upper()}-{1000 + m}"
            category = rng.choice(CATEGORIES)
            colours = rng.sample(COLOURS, rng.randint(2, 4))
            sizes = rng.sample(SIZES, rng.randint(2, 4))
            batches = [f"{registrar[:2].upper()}{m:03d}-L{b}" for b in range(rng.randint(1, 2))]
            origin = rng.choice(["LK", "LK", "LK", "BD", "IN"])
            for colour in colours:
                for size in sizes:
                    counter += 1
                    g = gtin13(f"594{r_index:02d}{counter:07d}")
                    truth["variant"][g] = {"registrar": registrar, "family": family, "colour": colour,
                                           "size": size, "category": category}
                    truth["model_variants"][(registrar, family)].add(g)
                    base = {
                        "productFamily": family, "productCategory": category, "gtin": g,
                        "colour": noisy(colour, rng), "size": noisy(size, rng),
                        "fibreComposition": rng.choice(["100% Cotton", "95% Cotton 5% Elastane", "100% Polyester"]),
                        "countryOfOrigin": origin, "manufacturerName": f"{registrar} Apparel (Pvt) Ltd",
                        "careInstructions": "Machine wash 30C", "facilityIdentifiers": f"FAC-{registrar}-{m % 3}",
                    }
                    for s in range(serials):
                        batch = rng.choice(batches)
                        serial = f"S{counter:06d}{s:02d}"
                        rows[registrar].append(dict(base, batchNumber=batch, serialNumber=serial,
                                                    purchaseOrderReference=f"PO-{rng.randint(1000, 9999)}"))
                        truth["batch_items"][(registrar, batch)].add((g, serial))
                    if serials == 0:
                        rows[registrar].append(dict(base, batchNumber=rng.choice(batches)))
    return rows, truth


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "tp": tp, "fp": fp, "fn": fn}


# --------------------------------------------------------------- the study
class Study:
    def __init__(self, workdir: Path, seed: int, models: int, serials: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed + 1)
        self.schema = json.loads(CDM_SCHEMA.read_text(encoding="utf-8"))
        raw = json.loads(CDM_CONTEXT.read_text(encoding="utf-8")) if CDM_CONTEXT.is_file() else {}
        self.context = raw.get("@context", raw) or None
        self.policy = AccessPolicy.load(POLICY_PATH)
        self.root = RootIndex(workdir / "root.sqlite")
        self.fed = Federation(self.root)
        self.nodes = {
            "lk-1": self.fed.add(RegistryNode("lk-1", RegistryStore(workdir / "lk1.sqlite", "lk-1"), self.root,
                                              self.policy, "http://lk-1.adir.test", "LK node")),
            "eu-1": self.fed.add(RegistryNode("eu-1", RegistryStore(workdir / "eu1.sqlite", "eu-1"), self.root,
                                              self.policy, "http://eu-1.adir.test", "EU node")),
        }
        self.home = {"colombo-knits": "lk-1", "kandy-garments": "lk-1", "galle-apparel": "lk-1",
                     "brand-eu": "eu-1", "brand-nl": "eu-1"}
        self.rows, self.truth = generate(seed, list(self.home), models, serials)

    # E0: load
    def load(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        reports = {}
        for registrar, rows in self.rows.items():
            node = self.nodes[self.home[registrar]]
            reports[registrar] = register_rows(node, rows, registrar, self.schema).as_dict()
        elapsed = time.perf_counter() - t0
        self.gtin_adid = {}
        for g in self.truth["variant"]:
            self.gtin_adid[g] = self.root.gs1(normalise_gtin(g))
        totals = defaultdict(int)
        for rep in reports.values():
            for k, v in rep["created"].items():
                totals[k] += v
        return {"rows": sum(len(r) for r in self.rows.values()), "entities_created": dict(totals),
                "seconds": round(elapsed, 2),
                "conflicts": sum(len(r["conflicts"]) for r in reports.values()),
                "skipped": sum(len(r["skipped"]) for r in reports.values())}

    def all_adids(self) -> list[tuple[str, str]]:
        return [(nid, a) for nid, n in self.nodes.items() for a in n.store.all_adids()]

    # E1
    def uniqueness(self) -> dict[str, Any]:
        ids = [a for _, a in self.all_adids()]
        gtin_targets = [self.gtin_adid[g] for g in self.truth["variant"]]
        n = len(ids)
        return {
            "adids": n,
            "duplicate_adids": n - len(set(ids)),
            "all_version_4": all(uuid.UUID(a).version == 4 for a in ids),
            "gtins": len(gtin_targets),
            "gtins_bound_to_distinct_variants": len(set(gtin_targets)) == len(gtin_targets),
            "birthday_bound_collision_probability_at_1e12": 1e24 / 2 ** 123,
            "birthday_bound_collision_probability_at_this_n": n * n / 2 ** 123,
        }

    # E2
    def resolvability(self, http_sample: int = 300) -> dict[str, Any]:
        ok = total = 0
        for _, adid in self.all_adids():
            total += 1
            hit = self.fed.resolve(adid)
            ok += hit is not None and hit[1].adid == adid
        gtin_ok = sum(self.root.gs1(normalise_gtin(g)) == self.gtin_adid[g] and self.gtin_adid[g] is not None
                      for g in self.truth["variant"])
        sgtin_ok = sgtin_total = 0
        for items in self.truth["batch_items"].values():
            for g, serial in items:
                sgtin_total += 1
                adid = self.root.gs1(sgtin_key(normalise_gtin(g), serial))
                if adid:
                    hit = self.fed.resolve(adid)
                    sgtin_ok += bool(hit) and self.fed.resolve(adid)[1].metadata.get("serialNumber") == serial
        # HTTP: local and cross-node, including the 307 redirect hop.
        clients = {nid: TestClient(create_app(n)) for nid, n in self.nodes.items()}
        sample = self.rng.sample(self.all_adids(), min(http_sample, len(self.all_adids())))
        local_ms, cross_ms, http_ok = [], [], 0
        for nid, adid in sample:
            entity = self.nodes[nid].store.get(adid)
            path = entity.path
            t = time.perf_counter()
            r = clients[nid].get(path)
            local_ms.append((time.perf_counter() - t) * 1000)
            other = "eu-1" if nid == "lk-1" else "lk-1"
            t = time.perf_counter()
            r1 = clients[other].get(path, follow_redirects=False)
            r2 = clients[nid].get(path) if r1.status_code == 307 else r1
            cross_ms.append((time.perf_counter() - t) * 1000)
            http_ok += r.status_code == 200 and r1.status_code == 307 and r2.status_code == 200 \
                and r1.headers["location"].endswith(path) and r2.json()["adid"] == adid
        return {
            "adid_resolution_rate": round(ok / total, 6), "adids": total,
            "gtin_resolution_rate": round(gtin_ok / len(self.truth["variant"]), 6),
            "sgtin_resolution_rate": round(sgtin_ok / sgtin_total, 6) if sgtin_total else None,
            "http_sample": len(local_ms), "http_local_and_cross_node_ok_rate": round(http_ok / len(local_ms), 6),
            "http_local_ms_p50": round(pct(local_ms, .5), 2), "http_local_ms_p95": round(pct(local_ms, .95), 2),
            "http_cross_node_ms_p50": round(pct(cross_ms, .5), 2),
            "http_cross_node_ms_p95": round(pct(cross_ms, .95), 2),
        }

    # E3
    def discovery(self, attribute_queries: int = 200) -> dict[str, Any]:
        out: dict[str, Any] = {}
        # Q1 structural: variants of each family (public view).
        tp = fp = fn = 0
        for (registrar, family), gtins in self.truth["model_variants"].items():
            node = self.nodes[self.home[registrar]]
            fam = node.store.find("family_code", f"{registrar}:{slugify(family)}")
            found = {v["adid"] for v in record_view(node, fam, PUBLIC)["relations"].get("hasVariant", [])}
            expected = {self.gtin_adid[g] for g in gtins}
            tp += len(found & expected); fp += len(found - expected); fn += len(expected - found)
        out["Q1_variants_of_family"] = prf(tp, fp, fn)
        # Q4 (authority): every serialised item recorded under one lot — the recall query.
        # Batch is CDM data in ADID v2, so this is a restricted facet search, not a relation.
        authority = Principal(Role.AUTHORITY, "customs")
        tp = fp = fn = 0
        for (registrar, batch), items in self.truth["batch_items"].items():
            node = self.nodes[self.home[registrar]]
            found = {m["adid"] for m in lot_members(node, batch, authority, registrar) if m["kind"] == "instance"}
            expected = {node.store.find("sgtin", sgtin_key(normalise_gtin(g), s)) for g, s in items}
            tp += len(found & expected); fp += len(found - expected); fn += len(expected - found)
        out["Q4_items_in_lot_authority"] = prf(tp, fp, fn)

        # Q2/Q3 attribute queries: registry normalised facets vs exact-string baseline.
        variants = self.truth["variant"]
        combos = list({(v["registrar"], v["colour"], v["size"]) for v in variants.values()})
        self.rng.shuffle(combos)
        categories = CATEGORIES
        adir = defaultdict(int); base = defaultdict(int)
        adir3 = defaultdict(int); base3 = defaultdict(int)

        def score(acc, found, expected):
            acc["tp"] += len(found & expected); acc["fp"] += len(found - expected); acc["fn"] += len(expected - found)

        def baseline(node, filters, registrar=None):
            hits = set()
            for a in node.store.all_adids("variant"):
                e = node.store.get(a)
                if registrar and e.registrar != registrar:
                    continue
                meta = dict(e.metadata)
                parent = node.store.related(a, "variantOf")
                if parent:
                    meta = {**node.store.get(parent[0][1]).metadata, **meta}
                if all(str(meta.get(k)) == v for k, v in filters.items()):
                    hits.add(a)
            return hits

        for registrar, colour, size in combos[:attribute_queries]:
            node = self.nodes[self.home[registrar]]
            expected = {self.gtin_adid[g] for g, v in variants.items()
                        if v["registrar"] == registrar and v["colour"] == colour and v["size"] == size}
            found = set(node.store.search({"colour": colour, "size": size}, kinds=["variant"],
                                          registrar=registrar, limit=10_000))
            score(adir, found, expected)
            score(base, baseline(node, {"colour": colour, "size": size}, registrar), expected)
        for category in categories:
            expected = {self.gtin_adid[g] for g, v in variants.items() if v["category"] == category}
            found = set()
            for node in self.nodes.values():  # cross-registrar, cross-node discovery
                found |= set(node.store.search({"productCategory": category}, kinds=["variant"], limit=100_000))
            score(adir3, found, expected)
            bfound = set()
            for node in self.nodes.values():
                bfound |= baseline(node, {"productCategory": category})
            score(base3, bfound, expected)
        out["Q2_colour_size_within_registrar"] = {"registry_search": prf(**adir), "exact_string_baseline": prf(**base),
                                                  "queries": min(attribute_queries, len(combos))}
        out["Q3_category_across_registrars_and_nodes"] = {"registry_search": prf(**adir3), "exact_string_baseline": prf(**base3),
                                                          "queries": len(categories)}
        return out

    # E4
    def stability(self, fraction: float = 0.2, move_fraction: float = 0.1) -> dict[str, Any]:
        """Do printed identifiers survive attribute corrections and infrastructure changes?

        Compares the ADID v2 path (family UUID + issued variant segment +
        instance UUID) with the frozen v1.0 path (style code + live colour/size +
        serial) under the same colour or size corrections.
        """
        gtins = list(self.truth["variant"])
        chosen = set(self.rng.sample(gtins, int(len(gtins) * fraction)))
        fix_colour = {g: self.rng.random() < 0.5 for g in sorted(chosen)}
        # Every printed v2 path for the chosen variants and their instances, before corrections.
        v2_before: dict[str, str] = {}
        for g in chosen:
            var = self.gtin_adid[g]
            node_id, ent = self.fed.resolve(var)
            v2_before[var] = ent.path
            for _, inst in self.nodes[node_id].store.related(var, "instanceOf", "in"):
                v2_before[inst] = self.nodes[node_id].store.get(inst).path
        v1_before, v1_after, v1_variant_before = {}, {}, {}
        corrected_rows: dict[str, list[dict]] = defaultdict(list)
        for registrar, rows in self.rows.items():
            for row in rows:
                g = row["gtin"]
                if g not in chosen:
                    continue
                t = self.truth["variant"][g]
                v1_before[(g, row.get("serialNumber"))] = AdidIdentifier(
                    registrar, t["family"], row["colour"], row["size"], row.get("serialNumber")).uri()
                v1_variant_before.setdefault(g, AdidIdentifier(registrar, t["family"], row["colour"], row["size"]).uri())
                new = dict(row)
                if fix_colour[g]:
                    new["colour"] = CORRECTIONS[t["colour"]]
                else:
                    new["size"] = SIZE_CORRECTIONS[t["size"]]
                v1_after[(g, row.get("serialNumber"))] = AdidIdentifier(
                    registrar, t["family"], new["colour"], new["size"], new.get("serialNumber")).uri()
                corrected_rows[registrar].append(new)
        updated = 0
        for registrar, rows in corrected_rows.items():
            rep = register_rows(self.nodes[self.home[registrar]], rows, registrar, self.schema)
            updated += rep.updated.get("variant", 0)
        v2_after = {a: self.fed.resolve(a)[1].path for a in v2_before}
        v2_stable = sum(v2_before[a] == v2_after[a] for a in v2_before) / len(v2_before)
        v1_stable = sum(v1_before[k] == v1_after[k] for k in v1_before) / len(v1_before)
        # The old printed v2 path still opens the same, corrected record.
        old_label_ok = 0
        for a, p in v2_before.items():
            node_id = self.root.locate(a)
            hit = self.nodes[node_id].store.find_path(p)
            old_label_ok += hit == a
        alias_ok = alias_total = 0
        for g, uri in v1_variant_before.items():
            t = self.truth["variant"][g]
            path = uri.split("/adid/", 1)[1]
            node = self.nodes[self.home[t["registrar"]]]
            alias_total += 1
            alias_ok += node.store.find("alias", f"{t['registrar']}/{path}") == self.gtin_adid[g]
        # Infrastructure change: move a share of lk-1 families (with their subtrees) to eu-1, then re-host lk-1.
        printed = {a: self.fed.resolve(a)[1].path for _, a in self.all_adids() if self.fed.resolve(a)}
        families = [a for a in self.nodes["lk-1"].store.all_adids("family")
                    if self.nodes["lk-1"].store.get(a).status == "active"]
        moved_families = self.rng.sample(families, int(len(families) * move_fraction))
        for a in moved_families:
            self.fed.move(a, "eu-1")
        moved = [a for a in printed if self.root.locate(a) == "eu-1" and self.nodes["lk-1"].store.get(a) is not None]
        self.root.set_node_url("lk-1", "http://lk-1-new-host.adir.test")
        resolvable = sum(bool(self.fed.resolve(a)) for a in printed) / len(printed)
        unchanged = sum(bool(self.fed.resolve(a)) and self.fed.resolve(a)[1].path == p for a, p in printed.items()) / len(printed)
        moved_verify = sum(self.nodes["eu-1"].store.verify(a).ok for a in moved) / max(1, len(moved))
        return {
            "corrected_variants": len(chosen), "variant_records_updated": updated,
            "v2_paths_compared": len(v2_before),
            "v2_path_unchanged_rate": round(v2_stable, 6),
            "v1_path_identifier_unchanged_rate": round(v1_stable, 6),
            "v1_identifiers_compared": len(v1_before),
            "old_v2_path_opens_corrected_record": round(old_label_ok / len(v2_before), 6),
            "old_v1_path_resolves_via_retained_alias": round(alias_ok / alias_total, 6) if alias_total else None,
            "families_moved_between_nodes": len(moved_families), "entities_moved": len(moved),
            "printed_path_unchanged_after_move_and_rehost": round(unchanged, 6),
            "resolvable_after_move_and_rehost": round(resolvable, 6),
            "moved_entities_history_verifies": round(moved_verify, 6),
        }

    # E5
    def interoperability(self, sample: int = 150) -> dict[str, Any]:
        try:
            from pyld import jsonld
        except ImportError:  # pragma: no cover
            jsonld = None
        docs, dl_total, dl_ok, schema_err, expand_err, triples = [], 0, 0, 0, 0, []
        missing_mandatory = 0
        cdm_fields = set(self.schema.get("properties", {}))
        from src.cdm.registry import CdmRegistry  # schema-only use
        for nid, adid in self.rng.sample(self.all_adids(), min(sample, len(self.all_adids()))):
            node = self.nodes[nid]
            ent = node.store.get(adid)
            if ent is None or ent.status != "active":
                continue
            doc = dpp_view(node, adid, PUBLIC, self.context)
            docs.append(doc)
            for link in [s for s in doc.get("sameAs", []) if s.startswith("https://id.gs1.org")]:
                dl_total += 1
                dl_ok += bool(DL_PATTERN.match(link))
            if jsonld is not None:
                try:
                    triples.append(len(jsonld.to_rdf(doc, {"format": "application/n-quads"}).splitlines()))
                except Exception:
                    expand_err += 1
        registry_stub = type("R", (), {"schema": self.schema, "mandatory_names": lambda s: []})()
        for doc in docs:
            record = {k: v for k, v in doc.items() if k in cdm_fields}
            errors = validate_record(record, registry_stub).schema_errors
            schema_err += any("is a required property" not in e for e in errors)
            missing_mandatory += any("is a required property" in e for e in errors)
        return {
            "passports_checked": len(docs),
            "jsonld_processor": "pyld" if jsonld else "not installed",
            "jsonld_to_rdf_errors": expand_err if jsonld else None,
            "rdf_triples_per_passport_median": statistics.median(triples) if triples else None,
            "gs1_digital_links": dl_total, "gs1_digital_link_syntax_ok_rate": round(dl_ok / dl_total, 6) if dl_total else None,
            "cdm_type_or_format_error_rate": round(schema_err / len(docs), 6) if docs else None,
            "passports_missing_a_mandatory_field": round(missing_mandatory / len(docs), 6) if docs else None,
            "mandatory_note": "Synthetic rows carry no manufacturerOperatorId or non-GTIN productIdentifier, "
                              "so this reflects the generator, not the registry.",
            "canonical_form": "urn:uuid (RFC 9562)",
        }

    # E7
    def privacy(self, guesses: int = 10_000) -> dict[str, Any]:
        leaks = checked = 0
        for nid, adid in self.all_adids():
            node = self.nodes[nid]
            ent = node.store.get(adid)
            if ent.status != "active":
                continue
            try:
                doc = dpp_view(node, adid, PUBLIC, self.context)
                rec = record_view(node, adid, PUBLIC)
            except AccessDenied:
                continue
            checked += 1
            fields = set(doc) | {k for sec in rec.get("sections", {}).values() for k in sec}
            leaks += sum(1 for f in fields if f in self.schema.get("properties", {}) and not self.policy.is_public(f))
            rel_kinds = {x.get("kind") for items in rec.get("relations", {}).values() for x in items}
            leaks += bool(rel_kinds & {"instance"})
        clients = {nid: TestClient(create_app(n)) for nid, n in self.nodes.items()}
        enumerated = 0
        for f in ("productFamily", "productCategory", "colour", "countryOfOrigin"):
            r = clients["lk-1"].get("/search", params={f: "x"})
            enumerated += any(x["kind"] == "instance" for x in r.json().get("results", []))
        blocked = clients["lk-1"].get("/search", params={"kind": "instance"}).status_code == 403
        lot_blocked = (clients["lk-1"].get("/lot/X").status_code == 403
                       and clients["lk-1"].get("/search", params={"batchNumber": "X"}).status_code == 403)
        hits = sum(bool(self.fed.resolve(str(uuid.uuid4()))) for _ in range(guesses))
        total = sum(n.store.count() for n in self.nodes.values())
        return {
            "public_views_checked": checked, "restricted_field_or_relation_leaks": leaks,
            "public_lot_queries_blocked": lot_blocked,
            "public_instance_search_blocked": blocked, "public_search_results_exposing_items": enumerated,
            "random_guess_hits": hits, "random_guesses": guesses,
            "guess_success_probability_per_try": total / 2 ** 122,
            "identifier_carries_timestamp_or_attributes": False,
        }

    # E8
    def governance(self, per_type: int = 40, clean_sample: int = 500) -> dict[str, Any]:
        node = self.nodes["eu-1"]
        store = node.store
        active = [a for a in store.all_adids() if store.get(a).status == "active"]
        clean = self.rng.sample(active, min(clean_sample, len(active) // 2))
        false_pos = sum(not store.verify(a).ok for a in clean)
        pool = [a for a in active if a not in set(clean)]
        self.rng.shuffle(pool)
        conn = store._conn
        detected = defaultdict(int); tried = defaultdict(int)
        tampers = {
            "metadata_edit": lambda a: conn.execute(
                "UPDATE entities SET metadata=json_set(metadata,'$.fibreComposition','100% Silk') WHERE adid=?", (a,)),
            "alt_id_rebind": lambda a: conn.execute(
                "INSERT INTO alt_ids VALUES ('sku', ?, ?, 'x')", (f"forged-{a}", a)),
            "relation_removed": lambda a: conn.execute("DELETE FROM relations WHERE subject=?", (a,)),
            "history_rewritten": lambda a: conn.execute(
                "UPDATE history SET snapshot=replace(snapshot,'\"status\":\"active\"','\"status\":\"deprecated\"') WHERE adid=? AND version=1", (a,)),
            "history_row_deleted": lambda a: conn.execute(
                "DELETE FROM history WHERE adid=? AND version=(SELECT MAX(version) FROM history WHERE adid=?)", (a, a)),
        }
        i = 0
        for name, tamper in tampers.items():
            for _ in range(per_type):
                while i < len(pool) and name == "relation_removed" and not store.related(pool[i]):
                    i += 1
                if i >= len(pool):
                    break
                a = pool[i]; i += 1
                tamper(a)
                tried[name] += 1
                detected[name] += not store.verify(a).ok
        return {
            "clean_entities_checked": len(clean), "false_positive_rate": round(false_pos / len(clean), 6),
            "tamper_detection": {k: {"tried": tried[k], "detected": detected[k],
                                     "rate": round(detected[k] / tried[k], 6) if tried[k] else None} for k in tampers},
            "overall_detection_rate": round(sum(detected.values()) / max(1, sum(tried.values())), 6),
            "note": "Detects edits made outside the registry API. Does not prevent an operator with database "
                    "access from rewriting a whole chain consistently; anchoring head hashes externally "
                    "(signed checkpoints, EN 18246 scope) is future work.",
        }


def scalability(sizes: list[int], seed: int) -> list[dict[str, Any]]:
    """Throughput and latency as the registry grows (single node, file-backed)."""
    out = []
    schema = json.loads(CDM_SCHEMA.read_text(encoding="utf-8"))
    policy = AccessPolicy.load(POLICY_PATH)
    for target in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            root = RootIndex(Path(tmp) / "root.sqlite")
            node = RegistryNode("s", RegistryStore(Path(tmp) / "node.sqlite", "s"), root, policy)
            # ~ (1 family + 12 variants) per model with no instances; scale models to target.
            models = max(1, target // 13)
            rows, _ = generate(seed, ["scale-co"], models, serials=0)
            t0 = time.perf_counter()
            register_rows(node, rows["scale-co"], "scale-co", schema)
            reg_s = time.perf_counter() - t0
            n = node.store.count()
            rng = random.Random(seed)
            ids = node.store.all_adids()
            lat = []
            for a in rng.sample(ids, min(1000, len(ids))):
                t = time.perf_counter()
                try:
                    record_view(node, a, PUBLIC)
                except AccessDenied:
                    pass
                lat.append((time.perf_counter() - t) * 1000)
            slat = []
            for _ in range(200):
                t = time.perf_counter()
                node.store.search({"colour": rng.choice(COLOURS), "size": rng.choice(SIZES)}, kinds=["variant"], limit=50)
                slat.append((time.perf_counter() - t) * 1000)
            node.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            size_node = os.path.getsize(Path(tmp) / "node.sqlite")
            size_root = os.path.getsize(Path(tmp) / "root.sqlite")
            out.append({
                "entities": n, "registration_seconds": round(reg_s, 2),
                "registrations_per_second": round(n / reg_s, 1),
                "resolve_ms_p50": round(pct(lat, .5), 3), "resolve_ms_p95": round(pct(lat, .95), 3),
                "search_ms_p50": round(pct(slat, .5), 3), "search_ms_p95": round(pct(slat, .95), 3),
                "node_bytes_per_entity": round(size_node / n), "root_bytes_per_placement": round(size_root / max(1, root.placement_count())),
            })
            node.store.close()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.registry_eval")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--models", type=int, default=20, help="models per registrar (5 registrars, 2 nodes)")
    parser.add_argument("--serials", type=int, default=3, help="serialised items per variant")
    parser.add_argument("--sizes", type=int, nargs="*", default=[1000, 10000],
                        help="registry sizes for the scalability test")
    parser.add_argument("--out", default="runs")
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        study = Study(Path(tmp), args.seed, args.models, args.serials)
        results: dict[str, Any] = {"load": study.load()}
        print(f"Loaded {results['load']}")
        for name, fn in (("E1_uniqueness", study.uniqueness), ("E2_resolvability", study.resolvability),
                         ("E3_discovery", study.discovery), ("E5_interoperability", study.interoperability),
                         ("E7_privacy", study.privacy), ("E4_stability", study.stability),
                         ("E8_governance", study.governance)):
            t = time.perf_counter()
            results[name] = fn()
            print(f"{name} ({time.perf_counter() - t:.1f}s): {json.dumps(results[name], default=str)}")
        for n in study.nodes.values():
            n.store.close()
    results["E6_scalability"] = scalability(args.sizes, args.seed)
    print(f"E6_scalability: {json.dumps(results['E6_scalability'])}")

    record = {
        "status": "REGISTRY-EVALUATION (synthetic data; ADID v2, proposed post-freeze; not the frozen matching evaluation)",
        "started_at": started.isoformat(timespec="seconds"),
        "parameters": vars(args),
        "data": "Synthetic catalogue: 5 registrars on 2 nodes, seeded; surface-noised colour/size values; "
                "ground truth from the generator.",
        "results": results,
    }
    Path(args.out).mkdir(parents=True, exist_ok=True)
    path = Path(args.out) / f"registry_eval_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    print(f"Run record: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
