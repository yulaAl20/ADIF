"""End-to-end passport demonstration with one complete, invented record (D60).

    python -m eval.e2e_passport_demo

This is **not** the registry performance evaluation (``eval/registry_eval.py``),
whose synthetic records are deliberately incomplete. That evaluation reported
``passports_missing_a_mandatory_field: 1.0``, so it cannot show that the
pipeline produces a complete, CDM-valid passport. This script shows it with
one invented apparel product, from start to finish, and records an explicit
pass or fail for every check on every identifier it issues:

1. **Map.** The file goes through the gateway with the evaluated configuration
   (four-stage strict cascade; the semantic stage is off unless the real
   model is cached). The proposed mapping is compared with the intended one.
2. **Review.** The intended mapping is applied, as a reviewer would confirm it
   in the portal. Accuracy is measured in step 1, not assumed here.
3. **Register.** One family, its variants and their instances are registered
   on an in-memory node.
4. **Check** every passport (family, each variant, each instance):
   * the JSON-LD resolves over HTTP at its ADID path, with ``@id`` equal to
     that ADID;
   * no CDM type or format errors (JSON Schema, Draft 2020-12);
   * controlled vocabularies (country, size, colour) are respected;
   * every mandatory CDM field **applicable at that level** is present (see
     below);
   * the document converts to RDF with pyld (when installed);
   * GS1 Digital Links are well-formed;
   * the links to the parent level point to the right ADID.

**Mandatory fields by level.** The four mandatory fields (productFamily,
manufacturerOperatorId, productIdentifier, fibreComposition) are a
research-defined minimum, not a legal list. Two sit at family level and two
at variant level (``x-adif.granularity``). A family passport therefore cannot
carry productIdentifier or fibreComposition: a family has several variants, and
each has its own. Variant and instance passports must carry all four. Checking
family passports against all four would report a missing field by
construction, which is part of why the registry evaluation's figure is 1.0.

Everything in the input file is invented. The GTINs use GS1's documentation
example company prefix 0614141.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from eval.runner import build_context, load_overlay, run_schema
from src.registry.api import create_app
from src.registry.federation import RegistryNode, RootIndex
from src.registry.policy import PUBLIC, AccessPolicy
from src.registry.registration import register_rows
from src.registry.store import RegistryStore
from src.registry.views import dpp_view
from src.validation.validator import _load_vocabularies

INPUT = Path("demo/e2e_complete_record.csv")
SCHEMA_PATH = Path("cdm/cdm_v1.0.schema.json")
CONTEXT_PATH = Path("cdm/cdm_v1.0.context.jsonld")
VOCAB_PATH = Path("cdm/vocabularies/signatures.yaml")
OVERLAY = "config/ablation/full_cascade_value.yaml"
DL_PATTERN = re.compile(r"^https://id\.gs1\.org/01/\d{14}(/21/[\x21-\x7e]{1,20})?$")

#: The mapping a reviewer confirms for the demonstration file.
INTENDED = {
    "Design Code": "productFamily", "Product Category": "productCategory",
    "Manufacturer": "manufacturerName", "Manufacturer ID": "manufacturerOperatorId",
    "Facility ID": "facilityIdentifiers", "Country of Origin": "countryOfOrigin",
    "Fabric Composition": "fibreComposition", "Care Instructions": "careInstructions",
    "HS Code": "commodityCode", "Declaration of Conformity": "declarationOfConformity",
    "Safety Information": "safetyInformation", "Recycled Content": "recycledContent",
    "Carbon Footprint": "carbonFootprint", "GTIN": "gtin", "Style No": "productIdentifier",
    "Colour": "colour", "Size": "size", "Batch": "batchNumber",
    "Serial Number": "serialNumber", "Production Date": "productionDate",
}

LEVEL_ORDER = {"family": 0, "variant": 1, "batch": 1, "instance": 2}


def mandatory_for(level: str, schema: dict[str, Any]) -> list[str]:
    """Mandatory CDM fields whose granularity is at or above ``level``."""
    rank = LEVEL_ORDER[level]
    props = schema["properties"]
    return [
        name for name in schema.get("required", [])
        if LEVEL_ORDER.get((props[name].get("x-adif") or {}).get("granularity", "variant"), 1) <= rank
    ]


def step_map(path: Path, real_model: bool) -> dict[str, Any]:
    """Run the gateway on the file and compare with the intended mapping."""
    cfg = load_overlay(overlay_path=OVERLAY)
    if not real_model:
        cfg.matching.stages.semantic.enabled = False
    result, _ = run_schema(path, build_context(cfg, real_model=real_model))
    rows = []
    for rec in result.records:
        intended = INTENDED.get(rec.raw_header, "NO_MAPPING")
        rows.append({"column": rec.raw_header, "proposed": rec.target_field,
                     "stage": rec.deciding_stage.value, "intended": intended,
                     "correct": rec.target_field == intended})
    return {"stages": cfg.enabled_stages(), "decision": cfg.matching.arbitration,
            "columns": len(rows), "correct": sum(r["correct"] for r in rows), "detail": rows}


def _rows(path: Path) -> list[dict[str, Any]]:
    import csv
    with path.open(encoding="utf-8") as f:
        return [{INTENDED[k]: v.strip() for k, v in row.items() if k in INTENDED and v.strip()}
                for row in csv.DictReader(f)]


def check_passport(doc: dict[str, Any], level: str, schema: dict[str, Any],
                   vocab: dict[str, set[str]], parent_uri: str | None) -> dict[str, Any]:
    """Run every per-passport check and return explicit pass/fail results."""
    cdm = {k: v for k, v in doc.items() if k in schema["properties"]}
    validator = Draft202012Validator(schema)
    type_errors = [f"{'.'.join(map(str, e.path)) or '(root)'}: {e.message}"
                   for e in validator.iter_errors(cdm) if e.validator != "required"]
    vocab_errors = [f"{f}: {cdm[f]!r}" for f, allowed in vocab.items()
                    if f in cdm and str(cdm[f]).lower() not in allowed]
    required = mandatory_for(level, schema)
    missing = [f for f in required if cdm.get(f) in (None, "")]
    links = [s for s in doc.get("sameAs", []) if str(s).startswith("https://id.gs1.org")]
    bad_links = [s for s in links if not DL_PATTERN.match(s)]
    parent_ok = True
    if parent_uri is not None:
        parent_ok = parent_uri in (doc.get("adid:variant"), doc.get("adid:family"))
    rdf: Any = "pyld not installed"
    try:
        from pyld import jsonld
        try:
            rdf = len(jsonld.to_rdf(doc, {"format": "application/n-quads"}).splitlines())
        except Exception as exc:  # noqa: BLE001 - any processor failure is a failed check
            rdf = f"ERROR: {exc}"
    except ImportError:
        pass
    checks = {
        "no_type_or_format_errors": not type_errors,
        "controlled_vocabularies_respected": not vocab_errors,
        "level_mandatory_fields_present": not missing,
        "jsonld_converts_to_rdf": isinstance(rdf, int) and rdf > 0 if not isinstance(rdf, str) or not rdf.startswith("pyld") else None,
        "gs1_digital_links_well_formed": not bad_links,
        "parent_link_correct": parent_ok,
    }
    return {"checks": checks, "mandatory_required_here": required, "missing": missing,
            "type_errors": type_errors, "vocabulary_errors": vocab_errors,
            "rdf_triples": rdf, "gs1_digital_links": links, "fields_present": len(cdm)}


def run(real_model: bool = False) -> dict[str, Any]:
    """Execute the four steps and return the full record."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw_ctx = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    context = raw_ctx.get("@context", raw_ctx)
    vocab = _load_vocabularies(VOCAB_PATH)

    mapping = step_map(INPUT, real_model)

    node = RegistryNode("demo-1", RegistryStore(":memory:", "demo-1"), RootIndex(":memory:"),
                        AccessPolicy.load("config/registry.yaml"), base_url="http://demo-node")
    report = register_rows(node, _rows(INPUT), "examplelanka", schema)
    client = TestClient(create_app(node))

    passports = []
    seen: set[str] = set()
    for ids in report.row_adids:
        for level in ("family", "variant", "instance"):
            adid = ids.get(level)
            if adid is None or adid in seen:
                continue
            seen.add(adid)
            entity = node.store.get(adid)
            response = client.get(entity.path, headers={"Accept": "application/ld+json"})
            resolved = response.status_code == 200 and response.json().get("@id") == node.uri(adid)
            doc = response.json() if response.status_code == 200 else dpp_view(node, adid, PUBLIC, context)
            parent = None
            if level == "variant":
                parent = node.uri(ids["family"])
            elif level == "instance":
                parent = node.uri(ids["variant"])
            result = check_passport(doc, level, schema, vocab, parent)
            result["checks"] = {"resolves_over_http_at_its_adid": resolved, **result["checks"]}
            applicable = [v for v in result["checks"].values() if v is not None]
            passports.append({"level": level, "adid_path": entity.path, "uri": node.uri(adid),
                              "passed": all(applicable), **result})

    by_level: dict[str, list[bool]] = {}
    for p in passports:
        by_level.setdefault(p["level"], []).append(p["passed"])
    return {
        "status": "DEMONSTRATION (one invented product; not an evaluation of accuracy or scale)",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": str(INPUT),
        "step1_gateway_mapping": mapping,
        "step3_registration": {k: v for k, v in report.as_dict().items() if k != "row_adids"},
        "step4_passports": passports,
        "summary": {lvl: f"{sum(v)}/{len(v)} passed" for lvl, v in by_level.items()},
        "all_passed": all(p["passed"] for p in passports),
    }


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m eval.e2e_passport_demo")
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    record = run(args.real_model)
    m = record["step1_gateway_mapping"]
    print(f"Step 1  gateway mapping ({' -> '.join(m['stages'])}, {m['decision']}): "
          f"{m['correct']}/{m['columns']} columns as intended")
    for row in m["detail"]:
        if not row["correct"]:
            print(f"        x {row['column']!r}: proposed {row['proposed']} ({row['stage']}), intended {row['intended']}")
    reg = record["step3_registration"]
    print(f"Step 3  registered: {reg['created']}  skipped: {len(reg['skipped'])}  conflicts: {len(reg['conflicts'])}")
    print("Step 4  passport checks")
    for p in record["step4_passports"]:
        flag = "PASS" if p["passed"] else "FAIL"
        print(f"  {flag}  {p['level']:8} {p['adid_path']}")
        for name, ok in p["checks"].items():
            mark = "n/a " if ok is None else ("ok  " if ok else "FAIL")
            print(f"          {mark} {name}")
        if p["missing"] or p["type_errors"] or p["vocabulary_errors"]:
            print(f"          missing={p['missing']} type={p['type_errors']} vocab={p['vocabulary_errors']}")
    print(f"\nSummary: {record['summary']}  all passed: {record['all_passed']}")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"e2e_passport_demo_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    print(f"Record: {path}")
    return 0 if record["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
