"""What the ADID resolver returns: the record view, the DPP view, the neighbourhood.

Assembled at request time from the current registry state and filtered by the
caller's role, so there is one source of truth and no stale copies.

* **Record view** — identity (the ADID v2 path and its parts), status, the
  CDM data grouped into information sections, alternate identifiers and
  relationships.
* **DPP view** — a JSON-LD passport (CDM vocabulary) whose ``@id`` is the
  ADID URI. A variant's passport inherits family data; an instance's inherits
  family and variant data. One request returns the complete passport (O3).
* **Neighbourhood** — related products found from registry links and shared
  CDM attributes (D49).
"""

from __future__ import annotations

from typing import Any

from src.registry.federation import RegistryNode
from src.registry.gs1 import digital_link
from src.registry.ids import parse_path
from src.registry.policy import Principal
from src.registry.store import Entity, RegistryError

__all__ = ["AccessDenied", "NotFound", "record_view", "dpp_view", "summary", "neighbourhood", "label",
           "get_visible", "lot_members"]

ADID_NS = "https://id.adir.example/ns#"

INVERSE = {"variantOf": "hasVariant", "instanceOf": "hasInstance"}
#: Kinds a public caller may see in relationship lists and search results.
#: Instances are hidden so the registry cannot be used to enumerate physical
#: items; an instance can still be resolved by anyone holding its ADID.
PUBLIC_RELATED_KINDS = {"family", "variant"}


class AccessDenied(RegistryError):
    """The caller's role may not see this record."""


class NotFound(RegistryError):
    """No such record (or it was withdrawn)."""


def _visible_entity(node: RegistryNode, entity: Entity, principal: Principal, direct: bool) -> bool:
    if principal.privileged or principal.owns(entity.registrar):
        return True
    if entity.kind in PUBLIC_RELATED_KINDS:
        return True
    return direct and entity.kind == "instance"


def label(entity: Entity) -> str:
    """Short human-readable label for listings (never used as identity)."""
    m = entity.metadata
    if entity.kind == "family":
        return str(m.get("productFamily", entity.adid[:8]))
    if entity.kind == "variant":
        parts = [str(m[k]) for k in ("colour", "size") if m.get(k)]
        return " / ".join(parts) or str(m.get("gtin", entity.adid[:8]))
    return f"item {m.get('serialNumber', entity.adid[:8])}"


def summary(node: RegistryNode, entity: Entity) -> dict[str, Any]:
    """Compact public description used in relation lists and search results."""
    out = {"adid": entity.adid, "uri": node.uri(entity.adid), "path": entity.path, "kind": entity.kind,
           "label": label(entity), "status": entity.status}
    if entity.kind == "variant":
        for k in ("colour", "size", "gtin"):
            if entity.metadata.get(k):
                out[k] = entity.metadata[k]
    return out


def _identifiers(node: RegistryNode, entity: Entity, principal: Principal) -> dict[str, Any]:
    ids: dict[str, Any] = {"uri": node.uri(entity.adid), "path": entity.path, "urn": node.urn(entity.adid)}
    if entity.path:
        ids["parts"] = parse_path(entity.path)
    public_schemes = {"gtin", "alias"} | ({"sgtin"} if entity.kind == "instance" else set())
    for scheme, values in entity.alt_ids.items():
        if principal.privileged or principal.owns(entity.registrar) or scheme in public_schemes:
            ids[scheme] = values
    gtins = entity.alt_ids.get("gtin") or []
    if entity.kind == "variant" and gtins:
        ids["gs1DigitalLink"] = [digital_link(g) for g in gtins]
    for key in entity.alt_ids.get("sgtin", []):
        gtin14, serial = key.split(".", 1)
        ids.setdefault("gs1DigitalLink", []).append(digital_link(gtin14, serial))
    return ids


def _relations(node: RegistryNode, entity: Entity, principal: Principal) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    edges = [(p, o) for p, o in node.store.related(entity.adid, direction="out")]
    edges += [(INVERSE.get(p, p), s) for p, s in node.store.related(entity.adid, direction="in")]
    for name, other_id in edges:
        other = node.store.get(other_id)
        if other is None:
            out.setdefault(name, []).append({"adid": other_id, "uri": node.uri(other_id), "remote": True})
            continue
        if _visible_entity(node, other, principal, direct=False):
            out.setdefault(name, []).append(summary(node, other))
    return out


def get_visible(node: RegistryNode, adid: str, principal: Principal, direct: bool = True) -> Entity:
    """Fetch an entity, refusing kinds the principal may not resolve."""
    entity = node.store.get(adid)
    if entity is None:
        raise NotFound(f"No record {adid} on node {node.node_id}.")
    if not _visible_entity(node, entity, principal, direct=direct):
        raise AccessDenied(f"This {entity.kind} record is restricted to its manufacturer and to authorities.")
    return entity


def record_view(node: RegistryNode, adid: str, principal: Principal) -> dict[str, Any]:
    """The registry entry for ``adid``, filtered for ``principal``."""
    entity = get_visible(node, adid, principal)
    base = {"adid": entity.adid, "kind": entity.kind, "status": entity.status, "registrar": entity.registrar,
            "node": node.node_id, "identifiers": _identifiers(node, entity, principal)}
    if entity.status == "withdrawn":
        base["tombstone"] = "Withdrawn: registered in error. This identifier is retired and is not reassigned."
        return base
    if entity.replaced_by:
        base["replaced_by"] = {"adid": entity.replaced_by, "uri": node.uri(entity.replaced_by)}
    sections, withheld = node.policy.sectioned(entity.metadata, principal, entity.registrar)
    base.update({
        "version": entity.version, "updated_at": entity.updated_at,
        "sections": sections, "withheld_sections": withheld,
        "relations": _relations(node, entity, principal),
        "integrity": {"version": entity.version, "head_hash": entity.head_hash,
                      "verify": f"/id/{entity.adid}/verify"},
    })
    return base


def _chain(node: RegistryNode, entity: Entity) -> list[Entity]:
    chain, current, seen = [], entity, set()
    while current is not None and current.adid not in seen:
        seen.add(current.adid)
        chain.append(current)
        up = None
        for predicate in ("instanceOf", "variantOf"):
            hits = node.store.related(current.adid, predicate, "out")
            if hits:
                up = node.store.get(hits[0][1])
                break
        current = up
    return chain


def dpp_view(node: RegistryNode, adid: str, principal: Principal,
             cdm_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """JSON-LD DPP for any ADID: CDM data merged down family → variant → instance."""
    entity = get_visible(node, adid, principal)
    if entity.status == "withdrawn":
        raise NotFound("Withdrawn identifier: no passport is available.")
    chain = _chain(node, entity)
    data: dict[str, Any] = {}
    for level in reversed(chain):
        data.update(node.policy.filter_flat(level.metadata, principal, level.registrar))
    context: dict[str, Any] = dict(cdm_context or {"@vocab": "https://adif.example/ns/cdm#"})
    context["adid"] = ADID_NS
    context["sameAs"] = {"@id": "http://www.w3.org/2002/07/owl#sameAs", "@type": "@id"}
    for term in ("adid:family", "adid:variant", "adid:hasVariant", "adid:replacedBy"):
        context[term] = {"@type": "@id"}
    ids = _identifiers(node, entity, principal)
    doc: dict[str, Any] = {
        "@context": context,
        "@id": ids["uri"],
        "@type": "DigitalProductPassport",
        "sameAs": [ids["urn"], *ids.get("gs1DigitalLink", [])],
        "adid:level": entity.kind,
        "adid:path": entity.path,
        "adid:status": entity.status,
        "adid:recordVersion": entity.version,
        "adid:registrar": entity.registrar,
    }
    for level in chain[1:]:
        doc[f"adid:{level.kind}"] = node.uri(level.adid)
    if entity.replaced_by:
        doc["adid:replacedBy"] = node.uri(entity.replaced_by)
    if entity.kind == "family":
        variants = [node.store.get(v) for _, v in node.store.related(entity.adid, "variantOf", "in")]
        doc["adid:hasVariant"] = [node.uri(v.adid) for v in variants if v is not None]
    doc.update({k: v for k, v in data.items() if v not in (None, "")})
    return doc


def lot_members(node: RegistryNode, batch_number: str, principal: Principal,
                registrar: str | None = None) -> list[dict[str, Any]]:
    """Everything recorded under one production lot — the recall query.

    Batch is CDM data, not an ADID level (D22, D51), so this is a search on
    the restricted ``batchNumber`` facet, allowed for authorities and for the
    owning manufacturer only.
    """
    if not principal.privileged:
        if registrar is None or not principal.owns(registrar):
            raise AccessDenied("Lot searches are available to the manufacturer and to authorities only.")
    hits = node.store.search({"batchNumber": batch_number}, kinds=["variant", "instance"],
                             registrar=registrar, limit=10_000)
    return [summary(node, node.store.get(h)) for h in hits]


def neighbourhood(node: RegistryNode, adid: str, principal: Principal, similar_limit: int = 8) -> dict[str, Any]:
    """How related products are found for an ADID (D49).

    * **Structural** — the registry relations that the path also spells out:
      ``up`` (family of a variant, variant of an instance), ``down`` (a
      family's variants, a variant's instances), ``siblings`` (other variants
      of the same family, other instances of the same variant).
    * **Lot-mates** — for authorities and the owner only: other records with
      the same ``batchNumber`` (batch is CDM data, not identity).
    * **Similar** — other families' variants with the same normalised category
      and colour, from any manufacturer on this node.

    All results pass through the same access policy as a direct lookup.
    """
    entity = get_visible(node, adid, principal)
    store = node.store

    def visible(ids: list[str]) -> list[dict[str, Any]]:
        out = []
        for other_id in dict.fromkeys(ids):
            other = store.get(other_id)
            if other is None or other.adid == adid or other.status in ("withdrawn", "moved"):
                continue
            if _visible_entity(node, other, principal, direct=False):
                out.append(summary(node, other))
        return out

    up_ids = [o for p, o in store.related(adid, direction="out") if p in INVERSE]
    down_ids = [s for p, s in store.related(adid, direction="in") if p in INVERSE]
    sibling_ids: list[str] = []
    predicate = {"variant": "variantOf", "instance": "instanceOf"}.get(entity.kind)
    for parent in up_ids:
        if predicate:
            sibling_ids += [s for _, s in store.related(parent, predicate, "in")]

    with store._lock:
        meta = store._inherited_metadata(store._conn, adid)
    lot_mates: list[dict[str, Any]] = []
    lots = meta.get("batchNumber")
    if lots and (principal.privileged or principal.owns(entity.registrar)):
        for lot in (lots if isinstance(lots, list) else [lots]):
            lot_mates += [m for m in lot_members(node, str(lot), principal, entity.registrar) if m["adid"] != adid]

    similar: list[dict[str, Any]] = []
    filters = {k: meta[k] for k in ("productCategory", "colour") if meta.get(k)}
    if filters:
        own_family = meta.get("productFamily")
        for hit in store.search(filters, kinds=["variant"], limit=similar_limit * 4):
            other = store.get(hit)
            if other is None or hit == adid or hit in sibling_ids:
                continue
            with store._lock:
                other_meta = store._inherited_metadata(store._conn, hit)
            if own_family and other_meta.get("productFamily") == own_family:
                continue
            item = summary(node, other)
            item["design"] = other_meta.get("productFamily")
            item["manufacturer"] = other.registrar
            similar.append(item)
            if len(similar) >= similar_limit:
                break

    return {
        "adid": adid, "kind": entity.kind, "path": entity.path,
        "how": "Found from registry relations and shared CDM attributes; the path's levels mirror the relations.",
        "up": visible(up_ids), "down": visible(down_ids), "siblings": visible(sibling_ids),
        "lot": {"batchNumber": lots, "members": lot_mates} if lot_mates or (lots and (principal.privileged or principal.owns(entity.registrar))) else None,
        "similar": {"matched_on": filters, "results": similar},
    }
