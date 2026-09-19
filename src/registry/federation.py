"""Root index and multi-node resolution (D45).

The ICANN analogy, made concrete:

* **Root** — one coordinating index that knows *which node* holds each ADID
  (and which entity each public GS1 key belongs to). It holds no product data.
  Its resolver host is the one printed in QR codes.
* **Nodes** — registries operated by different parties (a national body, an
  industry association, a large brand). They hold the records and answer
  queries. A node can be added, retired or have its records moved without any
  identifier changing, because identifiers name entities, not nodes.

Compared with the alternatives this study considers (docs/ADID_V2_DESIGN.md §6):

* *Fully centralised* — one database, simplest governance, single point of
  failure and of control.
* *Prefix-delegated* (DOI / Handle) — the identifier carries a registrar
  prefix that routes the lookup. Avoids a per-identifier root entry, but the
  prefix is meaning encoded in the identifier, which is what the redesign set
  out to remove.
* *Root index + nodes* (chosen) — identifiers stay opaque; the cost is that the
  root stores one ~60-byte placement row per entity, which is measured in the
  scalability evaluation.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.registry.ids import DEFAULT_RESOLVER, path_uri, to_uri, to_urn
from src.registry.policy import AccessPolicy
from src.registry.store import RegistryError, RegistryStore

__all__ = ["RootIndex", "RegistryNode", "Federation"]

_ROOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id   TEXT PRIMARY KEY,
    base_url  TEXT NOT NULL,
    operator  TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS placements (
    adid      TEXT PRIMARY KEY,
    node_id   TEXT NOT NULL,
    at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gs1_keys (
    key       TEXT PRIMARY KEY,
    adid      TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RootIndex:
    """Where each ADID lives. No product data is stored here."""

    def __init__(self, db_path: str | Path, resolver: str = DEFAULT_RESOLVER) -> None:
        self.resolver = resolver
        db = str(db_path)
        if db != ":memory:":
            Path(db).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db, check_same_thread=False, isolation_level=None)
        if db != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_ROOT_SCHEMA)
        self._lock = threading.RLock()

    def _x(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def add_node(self, node_id: str, base_url: str, operator: str) -> None:
        self._x(
            "INSERT INTO nodes VALUES (?,?,?, 'active') ON CONFLICT(node_id) DO UPDATE SET base_url=excluded.base_url, operator=excluded.operator, status='active'",
            (node_id, base_url, operator),
        )

    def set_node_url(self, node_id: str, base_url: str) -> None:
        """Infrastructure change: a node moves host. No identifier changes."""
        self._x("UPDATE nodes SET base_url=? WHERE node_id=?", (base_url, node_id))

    def node_url(self, node_id: str) -> str | None:
        rows = self._x("SELECT base_url FROM nodes WHERE node_id=? AND status='active'", (node_id,))
        return rows[0][0] if rows else None

    def nodes(self) -> list[dict[str, str]]:
        return [
            {"node_id": n, "base_url": u, "operator": o, "status": s}
            for n, u, o, s in self._x("SELECT * FROM nodes ORDER BY node_id")
        ]

    def place(self, adid: str, node_id: str) -> None:
        self._x(
            "INSERT INTO placements VALUES (?,?,?) ON CONFLICT(adid) DO UPDATE SET node_id=excluded.node_id, at=excluded.at",
            (adid, node_id, _now()),
        )

    def place_many(self, adids: list[str], node_id: str) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            self._conn.executemany(
                "INSERT INTO placements VALUES (?,?,?) ON CONFLICT(adid) DO UPDATE SET node_id=excluded.node_id",
                [(a, node_id, _now()) for a in adids],
            )
            self._conn.execute("COMMIT")

    def locate(self, adid: str) -> str | None:
        rows = self._x("SELECT node_id FROM placements WHERE adid=?", (adid,))
        return rows[0][0] if rows else None

    def bind_gs1(self, key: str, adid: str) -> None:
        """Index a public GS1 key (GTIN-14, or GTIN-14.serial) to its ADID."""
        held = self._x("SELECT adid FROM gs1_keys WHERE key=?", (key,))
        if held and held[0][0] != adid:
            raise RegistryError(f"GS1 key {key} is already bound to {held[0][0]} in the root index.")
        self._x("INSERT OR IGNORE INTO gs1_keys VALUES (?,?)", (key, adid))

    def gs1(self, key: str) -> str | None:
        rows = self._x("SELECT adid FROM gs1_keys WHERE key=?", (key,))
        return rows[0][0] if rows else None

    def placement_count(self) -> int:
        return self._x("SELECT COUNT(*) FROM placements")[0][0]


@dataclass
class RegistryNode:
    """A registry node: its store, its policy, and its link to the root."""

    node_id: str
    store: RegistryStore
    root: RootIndex
    policy: AccessPolicy = field(default_factory=AccessPolicy)
    base_url: str = "http://127.0.0.1:8100"
    operator: str = "unnamed operator"

    def __post_init__(self) -> None:
        self.root.add_node(self.node_id, self.base_url, self.operator)

    @property
    def resolver(self) -> str:
        return self.root.resolver

    def uri(self, adid: str) -> str:
        """Resolvable URI: the canonical ADID v2 path under the root resolver."""
        ent = self.store.get(adid)
        if ent is not None and ent.path:
            return path_uri(ent.path, self.resolver)
        return to_uri(adid, self.resolver)

    def urn(self, adid: str) -> str:
        return to_urn(adid)

    def register(self, *args: Any, **kwargs: Any) -> str:
        adid = self.store.register(*args, **kwargs)
        self.root.place(adid, self.node_id)
        return adid

    def locate(self, adid: str) -> tuple[str, str | None]:
        """Return ``(node_id, base_url)`` for any ADID the federation knows.

        Local first; otherwise the root index. ``("", None)`` when unknown.
        """
        ent = self.store.get(adid)
        if ent is not None and ent.status != "moved":
            return self.node_id, self.base_url
        node = self.root.locate(adid)
        if node is None or node == self.node_id:
            return ("", None) if ent is None else (self.node_id, self.base_url)
        return node, self.root.node_url(node)


class Federation:
    """In-process federation of several nodes behind one root.

    Used by the evaluation and the tests to measure cross-node resolution and
    migration without running several servers. The HTTP API does the same
    thing with redirects.
    """

    def __init__(self, root: RootIndex) -> None:
        self.root = root
        self.nodes: dict[str, RegistryNode] = {}

    def add(self, node: RegistryNode) -> RegistryNode:
        self.nodes[node.node_id] = node
        return node

    def resolve(self, adid: str) -> tuple[str, Any] | None:
        """Follow the root index to the node holding ``adid``."""
        node_id = self.root.locate(adid)
        if node_id is None or node_id not in self.nodes:
            return None
        entity = self.nodes[node_id].store.get(adid)
        if entity is None or entity.status == "moved":
            return None
        return node_id, entity

    def move(self, adid: str, to_node: str, actor: str = "operator") -> None:
        """Re-home a family, with all its variants and instances, on another node.

        A family's subtree moves together because its variant and instance
        paths start with the family UUID, which is what the root index locates.
        No identifier or path changes, histories move byte for byte, and the old
        node keeps a ``moved`` tombstone for each entity.
        """
        from_node = self.root.locate(adid)
        if from_node is None:
            raise RegistryError(f"{adid} is not placed on any node.")
        if from_node == to_node:
            return
        source = self.nodes[from_node].store
        entity = source.get(adid)
        if entity is None or entity.kind != "family":
            raise RegistryError("Move a family; its variants and instances move with it.")
        subtree = [adid]
        for _, v in source.related(adid, "variantOf", "in"):
            subtree.append(v)
            subtree += [i for _, i in source.related(v, "instanceOf", "in")]
        target = self.nodes[to_node].store
        for a in subtree:
            target.import_bundle(source.export_bundle(a))
            self.root.place(a, to_node)
        for a in subtree:
            source.set_status(a, "moved", actor)
