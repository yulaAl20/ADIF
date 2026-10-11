"""Connect the legacy Streamlit app to the ADID registry node (ADID v2, D51).

The web app runs the node in-process from ``config/registry.yaml``. The company
name typed in step 1 becomes the registrar. In this demonstration the app acts
with operator rights on behalf of that company; the REST API is where API keys
and roles are enforced.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.registry.api import node_from_config
from src.registry.federation import RegistryNode
from src.registry.gs1 import normalise_gtin
from src.registry.ids import AdidFormatError, parse_adid
from src.registry.policy import PUBLIC, Principal, Role
from src.registry.registration import RegistrationReport, register_rows, rows_from_mapping
from src.registry.views import dpp_view, record_view

CDM_CONTEXT = Path("cdm/cdm_v1.0.context.jsonld")


@lru_cache(maxsize=1)
def get_node() -> RegistryNode:
    return node_from_config()


@lru_cache(maxsize=1)
def cdm_context() -> dict[str, Any] | None:
    if not CDM_CONTEXT.is_file():
        return None
    raw = json.loads(CDM_CONTEXT.read_text(encoding="utf-8"))
    return raw.get("@context", raw)


def owner(company: str) -> Principal:
    return Principal(Role.REGISTRANT, company)


def register_session(engine, session) -> RegistrationReport:
    rows = rows_from_mapping(session.frame, session.result.records)
    return register_rows(get_node(), rows, session.company, engine.registry.schema)


def lookup(text: str) -> str | None:
    """Accept an ADID (any form), a GTIN, or a readable alias path."""
    node = get_node()
    text = text.strip()
    if not text:
        return None
    try:
        return parse_adid(text)
    except AdidFormatError:
        pass
    gtin = normalise_gtin(text)
    if gtin:
        return node.root.gs1(gtin) or node.store.find("gtin", gtin)
    alias = text.lower().strip("/")
    if alias.startswith("alias/"):
        alias = alias[6:]
    return node.store.find("alias", alias)


def record(adid: str, principal: Principal = PUBLIC) -> dict[str, Any]:
    return record_view(get_node(), adid, principal)


def passport(adid: str, principal: Principal = PUBLIC) -> dict[str, Any]:
    return dpp_view(get_node(), adid, principal, cdm_context())
