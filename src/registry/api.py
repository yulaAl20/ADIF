"""ADID resolver and registry API (ADID v2, D51 — proposed post-freeze design).

Run one node::

    python -m src.registry.admin add-registrar demoknit "Demo Knit Works"   # prints a key
    uvicorn src.registry.api:build --factory --port 8100

Identifiers (path depth = level, as in the frozen v1.0 grammar):
    GET  /adid/{familyUUID}                                  family
    GET  /adid/{familyUUID}/{colour}_{size}                  variant
    GET  /adid/{familyUUID}/{colour}_{size}/{instanceUUID}   instance
         Browser → product page; ``Accept: application/ld+json`` or ``?view=dpp``
         → JSON-LD passport; otherwise → JSON record. A variant's or instance's
         bare UUID at depth 1 redirects (301) to its canonical path.

Tools on a record (by its UUID):
    GET  /id/{uuid}/related | /neighbourhood | /history | /verify
    GET  /lot/{batchNumber}          recall query (owner or authority only)
    GET  /01/{gtin}[/21/{serial}]    GS1 key → 303 to the ADID
    GET  /alias/{registrar}/{...}    v1-style readable alias → 303 to the ADID
    GET  /search                     controlled discovery (families and variants)
    GET  /registry/info

Registrant (``X-ADIR-Key``):
    POST  /registrations             CDM rows from the gateway → ADIDs
    POST  /entities                  one family, variant or instance
    PATCH /entities/{uuid}           edit CDM attributes (ADID and path unchanged)
    POST  /entities/{uuid}/status    deprecate / withdraw
    POST  /entities/{uuid}/alt-ids   bind another identifier
"""

from __future__ import annotations

import os

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from src.registry.federation import RegistryNode, RootIndex
from src.registry.gs1 import normalise_gtin, sgtin_key
from src.registry.ids import AdidFormatError, adid_path, parse_adid, parse_path, variant_key
from src.registry.policy import AccessPolicy, Principal, Role
from src.registry.registration import register_rows
from src.registry.store import PREDICATES, RegistryError, RegistryStore
from src.registry.views import AccessDenied, NotFound, dpp_view, lot_members, neighbourhood, record_view, summary

__all__ = ["create_app", "node_from_config", "build"]

CONFIG = Path("config/registry.yaml")
CDM_SCHEMA = Path("cdm/cdm_v1.0.schema.json")
CDM_CONTEXT = Path("cdm/cdm_v1.0.context.jsonld")


def node_from_config(path: str | Path = CONFIG) -> RegistryNode:
    """Build this process's registry node from ``config/registry.yaml``."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    n, r = raw["node"], raw["root"]
    return RegistryNode(
        node_id=n["node_id"],
        store=RegistryStore(n["db"], n["node_id"]),
        # ADIF_RESOLVER lets a hosted copy print its own address (e.g. https://adif-oydy.onrender.com)
        # instead of the example host. Only how addresses are written changes; no stored record does.
        root=RootIndex(r["index_db"], (os.environ.get("ADIF_RESOLVER") or r["resolver"]).rstrip("/")),
        policy=AccessPolicy.load(path),
        base_url=n["base_url"],
        operator=n.get("operator", ""),
    )


@lru_cache(maxsize=1)
def _cdm() -> tuple[dict[str, Any], dict[str, Any] | None]:
    schema = json.loads(CDM_SCHEMA.read_text(encoding="utf-8")) if CDM_SCHEMA.is_file() else {"properties": {}}
    context = None
    if CDM_CONTEXT.is_file():
        raw = json.loads(CDM_CONTEXT.read_text(encoding="utf-8"))
        context = raw.get("@context", raw)
    return schema, context


class EntityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    alt_ids: list[tuple[str, str]] = Field(default_factory=list)
    relations: list[tuple[str, str]] = Field(default_factory=list)


class Changes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: dict[str, Any]


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    replaced_by: str | None = None


class AltIdIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: str
    value: str


class RelationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    predicate: str
    object: str


class RowsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict[str, Any]]


#: Schemes a registrant may bind directly. ``gtin`` and ``sgtin`` are bound by
#: registration (with check-digit validation), and also go to the root index.
WRITABLE_SCHEMES = {"alias", "sku", "model_code", "batch_code", "item_code", "gtin", "sgtin"}


def create_app(
    node: RegistryNode,
    html_renderer: Callable[[Request, str, Principal], Any] | None = None,
    session_principal: Callable[[Request], Principal | None] | None = None,
) -> FastAPI:
    """Build the FastAPI app for one node (tests create several).

    Args:
        html_renderer: When given, a browser asking ``/adid/{uuid}`` for HTML
            gets a human-readable product page from the same URI that returns
            JSON or JSON-LD to machines. This is what lets a printed QR code
            open a web page (D48).
        session_principal: Resolve a signed-in web user from the request, so
            the website and the API apply the same access policy.
    """
    app = FastAPI(
        title=f"ADID registry node {node.node_id}",
        description="Apparel Digital Identity Registry — research prototype. Not a production service.",
        version="2.0.0-dev",
    )
    app.state.node = node

    def principal(key: str | None, request: Request | None = None) -> Principal:
        if key:
            return node.store.authenticate(key)
        if session_principal is not None and request is not None:
            return session_principal(request) or node.store.authenticate(None)
        return node.store.authenticate(None)

    def require_writer(p: Principal) -> Principal:
        if p.role not in (Role.REGISTRANT, Role.OPERATOR):
            raise HTTPException(401, "A registrant API key (X-ADIR-Key) is required to write.")
        return p

    def owned(adid: str, p: Principal):
        ent = node.store.get(adid)
        if ent is None:
            raise HTTPException(404, f"No entity {adid} on this node.")
        if not p.owns(ent.registrar):
            raise HTTPException(403, "Only the owning registrant may change this entity.")
        return ent

    def bare(adid: str) -> str:
        try:
            return parse_adid(adid)
        except AdidFormatError as exc:
            raise HTTPException(400, str(exc)) from exc

    def remote_or_404(adid: str, request: Request) -> RedirectResponse:
        node_id, url = node.locate(adid)
        if url and node_id != node.node_id:
            target = url.rstrip("/") + request.url.path
            if request.url.query:
                target += "?" + request.url.query
            return RedirectResponse(target, status_code=307)
        raise HTTPException(404, f"ADID {adid} is not registered in this federation.")

    def public_filter_fields(p: Principal, registrar: str | None) -> set[str]:
        from src.registry.store import FACET_FIELDS
        if p.privileged or (registrar and p.owns(registrar)):
            return set(FACET_FIELDS)
        return {f for f in FACET_FIELDS if node.policy.is_public(f)}

    @app.get("/registry/info", tags=["registry"])
    def info() -> dict[str, Any]:
        return {
            "node": node.node_id,
            "operator": node.operator,
            "resolver": node.resolver,
            "federation": node.root.nodes(),
            "identifier": {
                "version": "ADID v2 (proposed, post-freeze; the evaluated v1.0 grammar is unchanged)",
                "family": "/adid/{familyUUID}",
                "variant": "/adid/{familyUUID}/{colour}_{size}",
                "instance": "/adid/{familyUUID}/{colour}_{size}/{instanceUUID}",
                "grammar": "adid/grammar_v2.ebnf",
            },
            "levels": {k: node.store.count(k) for k in ("family", "variant", "instance")},
            "relations": {p: {"subject": list(s), "object": o} for p, (s, o) in PREDICATES.items()},
            "access_policy": {name: spec.get("tier") for name, spec in node.policy.sections.items()},
            "public_search_kinds": list(node.policy.public_kinds),
            "status_note": "Research prototype. Not a legally designated DPP service or authority.",
        }

    def answer(request: Request, adid: str, view: str, p: Principal):
        ent = node.store.get(adid)
        accept = request.headers.get("accept") or ""
        wants_ld = view == "dpp" or "application/ld+json" in accept
        if html_renderer is not None and view == "record" and not wants_ld and "text/html" in accept:
            return html_renderer(request, adid, p)
        try:
            if wants_ld:
                _, context = _cdm()
                return JSONResponse(dpp_view(node, adid, p, context), media_type="application/ld+json")
            body = record_view(node, adid, p)
        except AccessDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        except NotFound as exc:
            raise HTTPException(410 if ent.status == "withdrawn" else 404, str(exc)) from exc
        return JSONResponse(body, status_code=410 if ent.status == "withdrawn" else 200)

    def by_path(request: Request, path: str, family: str, view: str, key: str | None):
        try:
            parse_path(path)
        except AdidFormatError as exc:
            raise HTTPException(400, str(exc)) from exc
        adid = node.store.find_path(path.lower())
        if adid is None or node.store.get(adid).status == "moved":
            return remote_or_404(family.lower(), request)
        return answer(request, adid, view, principal(key, request))

    @app.get("/adid/{family}", tags=["resolve"])
    def resolve_family(family: str, request: Request, view: str = "record",
                       x_adir_key: str | None = Header(default=None)):
        adid = bare(family)
        ent = node.store.get(adid)
        if ent is None or ent.status == "moved":
            return remote_or_404(adid, request)
        if ent.kind != "family" and ent.path:
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(ent.path + query, status_code=301)
        return answer(request, adid, view, principal(x_adir_key, request))

    @app.get("/adid/{family}/{variant}", tags=["resolve"])
    def resolve_variant(family: str, variant: str, request: Request, view: str = "record",
                        x_adir_key: str | None = Header(default=None)):
        return by_path(request, f"/adid/{family}/{variant}", family, view, x_adir_key)

    @app.get("/adid/{family}/{variant}/{instance}", tags=["resolve"])
    def resolve_instance(family: str, variant: str, instance: str, request: Request, view: str = "record",
                         x_adir_key: str | None = Header(default=None)):
        return by_path(request, f"/adid/{family}/{variant}/{instance}", family, view, x_adir_key)

    def local_or_remote(adid: str, request: Request) -> str | RedirectResponse:
        adid = bare(adid)
        ent = node.store.get(adid)
        if ent is None or ent.status == "moved":
            return remote_or_404(adid, request)
        return adid

    @app.get("/id/{adid}/related", tags=["record tools"])
    def related(adid: str, request: Request, predicate: str | None = None,
                x_adir_key: str | None = Header(default=None)):
        got = local_or_remote(adid, request)
        if not isinstance(got, str):
            return got
        try:
            relations = record_view(node, got, principal(x_adir_key, request)).get("relations", {})
        except AccessDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        return relations if predicate is None else {k: v for k, v in relations.items() if k == predicate}

    @app.get("/id/{adid}/neighbourhood", tags=["record tools"])
    def neighbours(adid: str, request: Request, x_adir_key: str | None = Header(default=None)):
        """Parent, children, siblings, lot-mates (restricted) and similar products."""
        got = local_or_remote(adid, request)
        if not isinstance(got, str):
            return got
        try:
            return neighbourhood(node, got, principal(x_adir_key, request))
        except AccessDenied as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/id/{adid}/history", tags=["record tools"])
    def history(adid: str, request: Request):
        got = local_or_remote(adid, request)
        if not isinstance(got, str):
            return got
        return {"adid": got, "versions": node.store.history(got)}

    @app.get("/id/{adid}/verify", tags=["record tools"])
    def verify(adid: str, request: Request):
        got = local_or_remote(adid, request)
        if not isinstance(got, str):
            return got
        return node.store.verify(got).as_dict()

    @app.get("/lot/{batch_number}", tags=["discovery"])
    def lot(batch_number: str, request: Request, registrar: str | None = None,
            x_adir_key: str | None = Header(default=None)):
        """Recall query: everything recorded under one production lot (restricted)."""
        p = principal(x_adir_key, request)
        reg = registrar or (p.registrar_id if p.role == Role.REGISTRANT else None)
        try:
            members = lot_members(node, batch_number, p, reg)
        except AccessDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        return {"batchNumber": batch_number, "count": len(members), "members": members}

    def _gs1_redirect(key: str) -> RedirectResponse:
        adid = node.root.gs1(key) or node.store.find("sgtin" if "." in key else "gtin", key)
        if adid is None:
            raise HTTPException(404, f"GS1 key {key} is not registered.")
        ent = node.store.get(adid)
        return RedirectResponse(ent.path if ent and ent.path else f"/adid/{adid}", status_code=303)

    @app.get("/01/{gtin}", tags=["gs1"])
    def gs1_gtin(gtin: str):
        g = normalise_gtin(gtin)
        if g is None:
            raise HTTPException(400, f"'{gtin}' is not a valid GTIN (check digit).")
        return _gs1_redirect(g)

    @app.get("/01/{gtin}/21/{serial}", tags=["gs1"])
    def gs1_sgtin(gtin: str, serial: str):
        g = normalise_gtin(gtin)
        if g is None:
            raise HTTPException(400, f"'{gtin}' is not a valid GTIN (check digit).")
        return _gs1_redirect(sgtin_key(g, serial))

    @app.get("/alias/{path:path}", tags=["resolve"])
    def alias(path: str):
        adid = node.store.find("alias", path.strip("/").lower())
        if adid is None:
            raise HTTPException(404, f"No alias '{path}'. Aliases are conveniences; the ADID is the identifier.")
        ent = node.store.get(adid)
        return RedirectResponse(ent.path or f"/adid/{adid}", status_code=303)

    @app.get("/search", tags=["discovery"])
    def search(request: Request, kind: str | None = None, registrar: str | None = None,
               limit: int = 20, offset: int = 0, x_adir_key: str | None = Header(default=None)):
        p = principal(x_adir_key, request)
        filters = {k: v for k, v in request.query_params.items()
                   if k not in {"kind", "registrar", "limit", "offset"}}
        allowed = list(node.policy.public_kinds)
        if p.privileged or (p.role == Role.REGISTRANT and registrar == p.registrar_id):
            allowed = ["family", "variant", "instance"]
        kinds = [kind] if kind else allowed
        if any(k not in allowed for k in kinds):
            raise HTTPException(403, f"Kind '{kind}' is not publicly searchable. Public search covers {allowed}.")
        restricted = set(filters) - public_filter_fields(p, registrar)
        if restricted:
            raise HTTPException(403, f"Searching by {sorted(restricted)} is restricted to the manufacturer and authorities.")
        limit = max(1, min(limit, node.policy.max_page_size))
        try:
            hits = node.store.search(filters, kinds=kinds, registrar=registrar, limit=limit, offset=offset)
        except RegistryError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"filters": filters, "kinds": kinds, "count": len(hits),
                "results": [summary(node, node.store.get(a)) for a in hits]}

    # ------------------------------------------------------------ writes
    @app.post("/registrations", tags=["registrant"])
    def registrations(body: RowsIn, x_adir_key: str | None = Header(default=None)):
        p = require_writer(principal(x_adir_key))
        schema, _ = _cdm()
        report = register_rows(node, body.rows, p.registrar_id or "operator", schema)
        return report.as_dict()

    @app.post("/entities", tags=["registrant"], status_code=201)
    def create(body: EntityIn, x_adir_key: str | None = Header(default=None)):
        p = require_writer(principal(x_adir_key))
        rels = [tuple(r) for r in body.relations]
        parent = next((o for pr, o in rels if pr in ("variantOf", "instanceOf")), None)
        try:
            if body.kind == "family":
                path = "/adid/{self}"
            elif body.kind == "variant":
                fam = node.store.get(parent) if parent else None
                if fam is None or not body.metadata.get("colour") or not body.metadata.get("size"):
                    raise HTTPException(422, "A variant needs a variantOf family on this node and colour + size.")
                path = adid_path(fam.adid, variant_key(body.metadata["colour"], body.metadata["size"]))
            elif body.kind == "instance":
                var = node.store.get(parent) if parent else None
                if var is None or not var.path:
                    raise HTTPException(422, "An instance needs an instanceOf variant on this node.")
                path = var.path + "/{self}"
            else:
                raise HTTPException(422, "Kind must be family, variant or instance.")
            adid = node.register(body.kind, p.registrar_id, body.metadata,
                                 [tuple(a) for a in body.alt_ids], rels, actor=p.registrar_id, path=path)
        except (RegistryError, AdidFormatError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"adid": adid, "path": node.store.get(adid).path, "urn": node.urn(adid), "uri": node.uri(adid)}

    @app.patch("/entities/{adid}", tags=["registrant"])
    def patch(adid: str, body: Changes, x_adir_key: str | None = Header(default=None)):
        adid = bare(adid)
        p = require_writer(principal(x_adir_key))
        owned(adid, p)
        try:
            version = node.store.update(adid, body.changes, p.registrar_id or "operator")
        except RegistryError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"adid": adid, "version": version}

    @app.post("/entities/{adid}/status", tags=["registrant"])
    def status(adid: str, body: StatusIn, x_adir_key: str | None = Header(default=None)):
        adid = bare(adid)
        p = require_writer(principal(x_adir_key))
        owned(adid, p)
        if body.status not in ("active", "deprecated", "withdrawn"):
            raise HTTPException(422, "Status must be active, deprecated or withdrawn.")
        try:
            version = node.store.set_status(adid, body.status, p.registrar_id or "operator", body.replaced_by)
        except (RegistryError, AdidFormatError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"adid": adid, "status": body.status, "version": version}

    @app.post("/entities/{adid}/alt-ids", tags=["registrant"])
    def add_alt(adid: str, body: AltIdIn, x_adir_key: str | None = Header(default=None)):
        adid = bare(adid)
        p = require_writer(principal(x_adir_key))
        owned(adid, p)
        if body.scheme not in WRITABLE_SCHEMES:
            raise HTTPException(422, f"Scheme must be one of {sorted(WRITABLE_SCHEMES)}.")
        value = body.value
        if body.scheme == "gtin":
            value = normalise_gtin(value)
            if value is None:
                raise HTTPException(422, "Invalid GTIN check digit.")
        try:
            node.store.add_alt_id(adid, body.scheme, value, p.registrar_id or "operator")
            if body.scheme in ("gtin", "sgtin"):
                node.root.bind_gs1(value, adid)
        except RegistryError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"adid": adid, "bound": f"{body.scheme}:{value}"}

    @app.post("/relations", tags=["registrant"])
    def relate(body: RelationIn, x_adir_key: str | None = Header(default=None)):
        p = require_writer(principal(x_adir_key))
        subject, obj = bare(body.subject), bare(body.object)
        owned(subject, p)
        try:
            node.store.relate(subject, body.predicate, obj, p.registrar_id or "operator")
        except RegistryError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"subject": subject, "predicate": body.predicate, "object": obj}

    return app


def build() -> FastAPI:
    """App factory for ``uvicorn src.registry.api:build --factory``.

    A factory rather than a module-level app so that importing this module (in
    tests, or from the gateway) never opens or creates the node database.
    """
    return create_app(node_from_config())
