"""Gateway output → ADID v2 registrations (D51).

The hybrid gateway decides *which column means what*. This module takes one
mapped file and issues ADIDs at the three research identity levels:

* one **family** per distinct ``productFamily`` → ``/adid/{familyUUID}``
* one **variant** per colour + size within a family →
  ``/adid/{familyUUID}/{colour}_{size}`` (its own UUID is kept as metadata)
* one **instance** per ``serialNumber`` →
  ``/adid/{familyUUID}/{colour}_{size}/{instanceUUID}``

Each row's values are split across the levels by the frozen CDM's declared
granularity (``x-adif.granularity``). **Batch is CDM data, not identity**
(D22 option 3, restored by D51): batch-level fields are stored on the instance,
or — for unserialised products — collected as a list of lots on the variant.
An authority can still list everything from one lot through a restricted
``batchNumber`` search.

**Re-registration is idempotent.** Entities are found again by their
alternate identifiers (family code, GTIN, SGTIN) or by their issued path. A
second upload of the same catalogue creates nothing; an upload that corrects an
attribute updates the same entity — same ADID, new version, history kept. The
variant segment of the path is issued once and does not change when the
colour or size *attribute* is later corrected.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from src.identity.adid import AdidError, slugify
from src.registry.federation import RegistryNode
from src.registry.gs1 import normalise_gtin, sgtin_key, valid_serial
from src.registry.ids import adid_path, new_adid, variant_key
from src.registry.store import AltIdConflict, RegistryError

__all__ = ["RegistrationReport", "coerce_types", "granularity_map", "rows_from_mapping", "register_rows"]

LEVELS = ("family", "variant", "batch", "instance")


@dataclass
class RegistrationReport:
    registrar: str
    rows: int = 0
    created: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)
    unchanged: Counter = field(default_factory=Counter)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    row_adids: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready summary."""
        return {
            "registrar": self.registrar, "rows": self.rows,
            "created": dict(self.created), "updated": dict(self.updated),
            "unchanged": dict(self.unchanged), "skipped": self.skipped,
            "conflicts": self.conflicts, "row_adids": self.row_adids,
        }


def granularity_map(cdm_schema: dict[str, Any]) -> dict[str, str]:
    """CDM field → ``family`` / ``variant`` / ``batch`` / ``instance``."""
    out = {}
    for name, spec in cdm_schema.get("properties", {}).items():
        g = (spec.get("x-adif") or {}).get("granularity", "variant")
        out[name] = g if g in LEVELS else "variant"
    return out


def rows_from_mapping(frame: pd.DataFrame, records: Iterable[Any]) -> list[dict[str, Any]]:
    """Turn a mapped upload into one ``{cdm_field: value}`` dict per row."""
    mapped = [r for r in records if r.is_mapped()]
    rows = []
    for i in range(len(frame)):
        row = {}
        for r in mapped:
            value = frame.iloc[i, r.source_position]
            if value is not None and not (isinstance(value, float) and pd.isna(value)) and str(value).strip():
                row[r.target_field] = str(value).strip()
        rows.append(row)
    return rows


def coerce_types(row: dict[str, Any], cdm_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert values of numeric CDM fields from text to numbers.

    Uploads arrive as text. Without this, ``carbonFootprint = "4.2"`` is stored
    as a string and the passport fails the CDM's ``type: number``, a defect
    found by the end-to-end passport demonstration (D60). A value that does not
    parse is left as it is, so the validator still reports it rather than it
    being silently dropped.
    """
    props = cdm_schema.get("properties", {})
    out = dict(row)
    for name, value in row.items():
        kind = (props.get(name) or {}).get("type")
        if kind in ("number", "integer") and isinstance(value, str):
            try:
                number = float(value.replace(",", "."))
                out[name] = int(number) if kind == "integer" and number.is_integer() else number
            except ValueError:
                pass
    return out


def _split(row: dict[str, Any], gran: dict[str, str]) -> dict[str, dict[str, Any]]:
    parts: dict[str, dict[str, Any]] = {lvl: {} for lvl in LEVELS}
    for k, v in row.items():
        parts[gran.get(k, "variant")][k] = v
    return parts


def _upsert(
    node: RegistryNode, report: RegistrationReport, kind: str, registrar: str,
    existing: str | None, metadata: dict[str, Any], alt: list[tuple[str, str]],
    relations: list[tuple[str, str]], path: str | None, actor: str, mint: str | None = None,
) -> str:
    store = node.store
    if existing is None:
        fresh = [a for a in alt if store.find(*a) is None]
        adid = node.register(kind, registrar, metadata, fresh, relations, actor=actor, path=path, adid=mint)
        report.created[kind] += 1
        return adid
    entity = store.get(existing)
    if entity.registrar != registrar:
        raise AltIdConflict(f"This {kind} is registered to '{entity.registrar}'.")
    changes = {k: v for k, v in metadata.items() if entity.metadata.get(k) != v}
    for scheme, value in alt:
        holder = store.find(scheme, value)
        if holder is None:
            store.add_alt_id(existing, scheme, value, actor)
        elif holder != existing:
            report.conflicts.append({"kind": kind, "adid": existing, "identifier": f"{scheme}:{value}", "held_by": holder})
    for predicate, obj in relations:
        store.relate(existing, predicate, obj, actor)
    if changes:
        store.update(existing, changes, actor)
        report.updated[kind] += 1
    else:
        report.unchanged[kind] += 1
    return existing


def _merge_lots(current: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    """Unserialised product: keep every lot's batch-level values as a sorted list."""
    out = {}
    for k, v in batch.items():
        seen = current.get(k, [])
        seen = seen if isinstance(seen, list) else [seen]
        out[k] = sorted({*map(str, seen), str(v)})
    return out


def register_rows(
    node: RegistryNode,
    rows: list[dict[str, Any]],
    registrar: str,
    cdm_schema: dict[str, Any],
    actor: str | None = None,
) -> RegistrationReport:
    """Register every row of a mapped file. See the module docstring."""
    gran = granularity_map(cdm_schema)
    actor = actor or registrar
    report = RegistrationReport(registrar=registrar, rows=len(rows))
    store = node.store
    with store.transaction():
        for index, row in enumerate(rows):
            try:
                row = coerce_types(row, cdm_schema)
                parts = _split(row, gran)
                family_name = row.get("productFamily")
                if not family_name:
                    report.skipped.append({"row": index, "reason": "No productFamily: a family cannot be identified (D9)."})
                    continue
                fam_slug = slugify(str(family_name))
                fam_key = ("family_code", f"{registrar}:{fam_slug}")
                family = _upsert(node, report, "family", registrar, store.find(*fam_key), parts["family"],
                                 [fam_key, ("alias", f"{registrar}/{fam_slug}")], [], "/adid/{self}", actor)
                ids = {"family": family}

                colour, size = row.get("colour"), row.get("size")
                gtin14 = normalise_gtin(row.get("gtin")) or normalise_gtin(row.get("productIdentifier"))
                if not (colour and size):
                    if gtin14 or row.get("serialNumber"):
                        report.skipped.append({"row": index, "reason": "No colour and size: the variant segment "
                                               "{colour}_{size} cannot be issued, so only the family was registered."})
                    report.row_adids.append(ids)
                    continue
                vkey = variant_key(colour, size)
                vpath = adid_path(family, vkey)
                existing = (store.find("gtin", gtin14) if gtin14 else None) or store.find_path(vpath)
                alt = [("alias", f"{registrar}/{fam_slug}/{vkey}")]
                if gtin14:
                    alt.insert(0, ("gtin", gtin14))
                if row.get("productIdentifier") and normalise_gtin(row["productIdentifier"]) is None:
                    alt.append(("sku", f"{registrar}:{row['productIdentifier']}"))
                vmeta = dict(parts["variant"])
                serial = row.get("serialNumber")
                if parts["batch"] and not serial:
                    current = store.get(existing).metadata if existing else {}
                    vmeta.update(_merge_lots(current, parts["batch"]))
                mint = None
                if existing is None:
                    mint = new_adid()
                    vmeta["variantId"] = mint  # the variant's own UUID, exposed as metadata (D51)
                variant = _upsert(node, report, "variant", registrar, existing, vmeta, alt,
                                  [("variantOf", family)], None if existing else vpath, actor, mint)
                if gtin14:
                    node.root.bind_gs1(gtin14, variant)
                ids["variant"] = variant
                vpath = store.get(variant).path  # the issued segment, even after a colour correction

                if serial:
                    key = ("sgtin", sgtin_key(gtin14, str(serial))) if gtin14 and valid_serial(serial) \
                        else ("item_code", f"{registrar}:{fam_slug}:{slugify(str(serial))}")
                    imeta = {**parts["batch"], **parts["instance"]}
                    inst = _upsert(node, report, "instance", registrar, store.find(*key), imeta, [key],
                                   [("instanceOf", variant)], vpath + "/{self}", actor)
                    if key[0] == "sgtin":
                        node.root.bind_gs1(key[1], inst)
                    ids["instance"] = inst
                report.row_adids.append(ids)
            except (AltIdConflict, AdidError) as exc:
                report.conflicts.append({"row": index, "error": str(exc)})
            except RegistryError as exc:
                report.skipped.append({"row": index, "reason": str(exc)})
    return report
