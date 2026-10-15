"""The ADID registry store (SQLite) — resolution layer for ADID v2 (D51).

Five tables carry the whole design:

``entities``
    One row per family, variant or instance. The primary key is the entity's
    UUID (v4); ``path`` is its canonical, immutable ADID v2 path
    (``/adid/{familyUUID}[/{colour}_{size}[/{instanceUUID}]]``). The row holds
    *kind* (family / variant / instance), owning registrar,
    lifecycle status and the attribute metadata as JSON. Identity and data are
    separate columns: an attribute edit rewrites ``metadata`` and bumps
    ``version``; it can never touch ``adid``.
``alt_ids``
    Other names for the same entity — GTIN, SGTIN, a manufacturer's style
    code, the human-readable alias path. ``(scheme, value)`` is unique across
    the registry, so one GTIN can never point at two entities. Rows are never
    deleted: an alias that stops describing an item (after a colour
    correction, say) keeps resolving to it.
``relations``
    Typed edges: ``variantOf`` (variant → family) and ``instanceOf``
    (instance → variant). The path encodes the same hierarchy for reading;
    the relations make it queryable. Batch is CDM data, not identity (D22,
    restored by D51); recall uses a restricted ``batchNumber`` facet.
``history``
    Append-only, one row per change, each carrying the SHA-256 of
    ``previous hash + canonical snapshot``. Any later edit to an entity, an
    alternate identifier or a relation that bypasses the API breaks the chain
    and :meth:`RegistryStore.verify` reports it (supervisor requirement 6:
    verification and governance).
``facets``
    Normalised attribute values for discovery queries, indexed by
    ``(field, value)`` so search does not scan JSON.

An ADID is never deleted and never reassigned. Withdrawal and deprecation are
status changes that leave a tombstone, so a printed identifier always resolves
to *something* — at worst, an explanation.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.dbconn import connect
from src.registry.ids import new_adid, parse_adid
from src.registry.policy import Principal, Role

__all__ = [
    "KINDS",
    "PREDICATES",
    "STATUSES",
    "Entity",
    "RegistryError",
    "AltIdConflict",
    "RelationError",
    "RegistryStore",
    "VerifyResult",
    "normalise_facet",
]

KINDS = ("family", "variant", "instance")
STATUSES = ("active", "deprecated", "withdrawn", "moved")

#: predicate -> (allowed subject kinds, allowed object kind)
PREDICATES: dict[str, tuple[tuple[str, ...], str]] = {
    "variantOf": (("variant",), "family"),
    "instanceOf": (("instance",), "variant"),
}

#: Facet fields indexed for discovery. Kept small on purpose: discovery is for
#: finding *related products*, not for querying arbitrary passport content.
FACET_FIELDS = (
    "productFamily", "productCategory", "colour", "size", "countryOfOrigin",
    "fibreComposition", "manufacturerName", "gtin", "batchNumber",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    adid        TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    registrar   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    replaced_by TEXT,
    metadata    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    head_hash   TEXT NOT NULL,
    path        TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_entities_kind ON entities(kind, registrar);
CREATE TABLE IF NOT EXISTS alt_ids (
    scheme      TEXT NOT NULL,
    value       TEXT NOT NULL,
    adid        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (scheme, value)
);
CREATE INDEX IF NOT EXISTS ix_alt_adid ON alt_ids(adid);
CREATE TABLE IF NOT EXISTS relations (
    subject     TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (subject, predicate, object)
);
CREATE INDEX IF NOT EXISTS ix_rel_object ON relations(object, predicate);
CREATE TABLE IF NOT EXISTS history (
    adid        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    at          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    snapshot    TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL,
    PRIMARY KEY (adid, version)
);
CREATE TABLE IF NOT EXISTS facets (
    adid        TEXT NOT NULL,
    field       TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (adid, field, value)
);
CREATE INDEX IF NOT EXISTS ix_facet_v2 ON facets(field, value, adid);
CREATE TABLE IF NOT EXISTS registrars (
    registrar_id TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL,
    key_sha256   TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL
);
"""

GENESIS = "0" * 64
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class RegistryError(Exception):
    """A registry operation was refused."""


class AltIdConflict(RegistryError):
    """An alternate identifier is already bound to a different entity."""


class RelationError(RegistryError):
    """A relation violates the kind rules or names an unknown entity."""


def normalise_facet(value: Any) -> str:
    """Surface-normalise an attribute value for discovery.

    ``"Navy Blue"``, ``"navy-blue"``, ``"NAVY_BLUE"`` and ``"navyblue"`` all
    become ``navyblue`` — the same compact form the gateway uses for header
    lookup. Deliberately *only* surface normalisation: deciding that "grey" and
    "gray", or "navy" and "dark blue", are the same colour is a vocabulary
    question, not a string one, and is out of scope (docs/ADID_V2_DESIGN.md §8).
    """
    text = str(value).strip().lower()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return _NON_ALNUM.sub("", text)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Entity:
    adid: str
    kind: str
    registrar: str
    status: str
    replaced_by: str | None
    metadata: dict[str, Any]
    version: int
    created_at: str
    updated_at: str
    head_hash: str
    path: str | None = None
    alt_ids: dict[str, list[str]] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass
class VerifyResult:
    adid: str
    ok: bool
    versions: int
    problems: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"adid": self.adid, "ok": self.ok, "versions": self.versions, "problems": self.problems}


class RegistryStore:
    """One registry node's persistent store."""

    def __init__(self, db_path: str | Path, node_id: str = "local") -> None:
        self.node_id = node_id
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL" if self.db_path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()
        self._depth = 0

    # ------------------------------------------------------------------ infra
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Group writes. Nested calls join the outermost transaction."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    def close(self) -> None:
        self._conn.close()

    def _q(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # -------------------------------------------------------------- registrars
    def add_registrar(self, registrar_id: str, name: str, role: Role | str = Role.REGISTRANT) -> str:
        """Create an account and return its API key (shown once, stored hashed)."""
        role = Role(role)
        key = f"adir_{secrets.token_urlsafe(24)}"
        with self.transaction() as c:
            c.execute(
                "INSERT INTO registrars VALUES (?,?,?,?,?)",
                (registrar_id, name, role.value, _sha(key), _now()),
            )
        return key

    def authenticate(self, key: str | None) -> Principal:
        """Map an API key to a principal. No key (or an unknown one) is public."""
        if not key:
            return Principal(Role.PUBLIC)
        rows = self._q("SELECT registrar_id, role FROM registrars WHERE key_sha256=?", (_sha(key),))
        if not rows:
            return Principal(Role.PUBLIC)
        registrar_id, role = rows[0]
        return Principal(Role(role), registrar_id)

    # ---------------------------------------------------------------- reading
    def _row_to_entity(self, row: tuple) -> Entity:
        e = Entity(
            adid=row[0], kind=row[1], registrar=row[2], status=row[3],
            replaced_by=row[4], metadata=json.loads(row[5]), version=row[6],
            created_at=row[7], updated_at=row[8], head_hash=row[9], path=row[10],
        )
        for scheme, value in self._q(
            "SELECT scheme, value FROM alt_ids WHERE adid=? ORDER BY created_at, value", (e.adid,)
        ):
            e.alt_ids.setdefault(scheme, []).append(value)
        return e

    def get(self, adid: str) -> Entity | None:
        rows = self._q("SELECT * FROM entities WHERE adid=?", (adid,))
        return self._row_to_entity(rows[0]) if rows else None

    def find_path(self, path: str) -> str | None:
        """The UUID of the entity whose canonical ADID path is ``path``."""
        rows = self._q("SELECT adid FROM entities WHERE path=?", (path.lower().rstrip("/"),))
        return rows[0][0] if rows else None

    def exists(self, adid: str) -> bool:
        return bool(self._q("SELECT 1 FROM entities WHERE adid=?", (adid,)))

    def find(self, scheme: str, value: str) -> str | None:
        rows = self._q("SELECT adid FROM alt_ids WHERE scheme=? AND value=?", (scheme, value))
        return rows[0][0] if rows else None

    def related(
        self, adid: str, predicate: str | None = None, direction: str = "out"
    ) -> list[tuple[str, str]]:
        """Return ``(predicate, other_adid)`` pairs.

        ``out`` follows edges from this entity (variant → its family); ``in``
        follows edges into it (family → its variants).
        """
        if direction == "out":
            sql = "SELECT predicate, object FROM relations WHERE subject=?"
        else:
            sql = "SELECT predicate, subject FROM relations WHERE object=?"
        params: tuple = (adid,)
        if predicate:
            sql += " AND predicate=?"
            params += (predicate,)
        return [(p, o) for p, o in self._q(sql + " ORDER BY created_at", params)]

    def count(self, kind: str | None = None) -> int:
        if kind:
            return self._q("SELECT COUNT(*) FROM entities WHERE kind=?", (kind,))[0][0]
        return self._q("SELECT COUNT(*) FROM entities")[0][0]

    def all_adids(self, kind: str | None = None) -> list[str]:
        if kind:
            return [r[0] for r in self._q("SELECT adid FROM entities WHERE kind=?", (kind,))]
        return [r[0] for r in self._q("SELECT adid FROM entities")]

    # -------------------------------------------------------------- snapshots
    def _snapshot(self, adid: str) -> dict[str, Any]:
        """Everything the hash chain protects for one entity."""
        row = self._q(
            "SELECT kind, registrar, status, replaced_by, metadata, path FROM entities WHERE adid=?",
            (adid,),
        )[0]
        alt = sorted(self._q("SELECT scheme, value FROM alt_ids WHERE adid=?", (adid,)))
        rel = sorted(self._q("SELECT predicate, object FROM relations WHERE subject=?", (adid,)))
        return {
            "adid": adid, "kind": row[0], "registrar": row[1], "status": row[2],
            "replaced_by": row[3], "metadata": json.loads(row[4]), "path": row[5],
            "alt_ids": [list(a) for a in alt], "relations": [list(r) for r in rel],
        }

    def _append_history(self, c: sqlite3.Connection, adid: str, action: str, actor: str, version: int) -> None:
        prev = c.execute(
            "SELECT hash FROM history WHERE adid=? ORDER BY version DESC LIMIT 1", (adid,)
        ).fetchone()
        prev_hash = prev[0] if prev else GENESIS
        snapshot = _canonical(self._snapshot(adid))
        digest = _sha(prev_hash + snapshot)
        c.execute(
            "INSERT INTO history VALUES (?,?,?,?,?,?,?,?)",
            (adid, version, _now(), actor, action, snapshot, prev_hash, digest),
        )
        c.execute("UPDATE entities SET head_hash=? WHERE adid=?", (digest, adid))

    def _inherited_metadata(self, c: sqlite3.Connection, adid: str) -> dict[str, Any]:
        """Metadata merged down the hierarchy (family → variant → instance).

        Facets are indexed on inherited values so that "all variants of design
        TS-1000" or "all T-shirt variants" can be answered from the variant's
        own facet rows, even though ``productFamily`` is stored on the family.
        """
        chain = []
        current, seen = adid, set()
        while current and current not in seen:
            seen.add(current)
            row = c.execute("SELECT metadata FROM entities WHERE adid=?", (current,)).fetchone()
            if row is None:
                break
            chain.append(json.loads(row[0]))
            up = c.execute(
                "SELECT object FROM relations WHERE subject=? AND predicate IN ('instanceOf','variantOf') LIMIT 1",
                (current,),
            ).fetchone()
            current = up[0] if up else None
        merged: dict[str, Any] = {}
        for metadata in reversed(chain):
            merged.update(metadata)
        return merged

    def _refresh_facets(self, c: sqlite3.Connection, adid: str, metadata: dict[str, Any] | None = None) -> None:
        """Re-index ``adid`` and, because facets are inherited, its descendants."""
        stack, done = [adid], set()
        while stack:
            current = stack.pop()
            if current in done:
                continue
            done.add(current)
            values = self._inherited_metadata(c, current)
            c.execute("DELETE FROM facets WHERE adid=?", (current,))
            rows = set()
            for f in FACET_FIELDS:
                value = values.get(f)
                for v in (value if isinstance(value, list) else [value]):
                    if v not in (None, ""):
                        rows.add((current, f, normalise_facet(v)))
            c.executemany("INSERT INTO facets VALUES (?,?,?)", sorted(rows))
            stack.extend(
                r[0] for r in c.execute(
                    "SELECT subject FROM relations WHERE object=? AND predicate IN ('instanceOf','variantOf')",
                    (current,),
                )
            )

    # ---------------------------------------------------------------- writing
    def register(
        self,
        kind: str,
        registrar: str,
        metadata: dict[str, Any] | None = None,
        alt_ids: list[tuple[str, str]] | None = None,
        relations: list[tuple[str, str]] | None = None,
        actor: str | None = None,
        adid: str | None = None,
        allow_external_objects: bool = False,
        path: str | None = None,
    ) -> str:
        """Register a new entity and return its freshly minted ADID.

        All alternate identifiers are checked *before* anything is written, so a
        conflict leaves the registry unchanged.

        Args:
            adid: Only for migration between nodes (:meth:`import_bundle`); new
                registrations always mint.
            allow_external_objects: Permit relations to ADIDs held on another
                node (federation). Kind rules are then checked by the caller.
            path: The canonical ADID v2 path (D51). Unique and immutable once
                written. ``"{self}"`` in it is replaced by the minted UUID,
                so a family or instance can name its own path before minting.
        """
        if kind not in KINDS:
            raise RegistryError(f"Unknown kind '{kind}'. Expected one of {KINDS}.")
        metadata = {k: v for k, v in (metadata or {}).items() if v not in (None, "")}
        alt_ids = alt_ids or []
        relations = relations or []
        new_id = parse_adid(adid) if adid else new_adid()
        now = _now()
        with self.transaction() as c:
            if c.execute("SELECT 1 FROM entities WHERE adid=?", (new_id,)).fetchone():
                # Astronomically unlikely for a minted v4 UUID; possible on import.
                raise RegistryError(f"ADID {new_id} already exists on this node.")
            for scheme, value in alt_ids:
                held = c.execute(
                    "SELECT adid FROM alt_ids WHERE scheme=? AND value=?", (scheme, value)
                ).fetchone()
                if held:
                    raise AltIdConflict(f"{scheme} '{value}' is already registered to {held[0]}.")
            for predicate, obj in relations:
                self._check_relation(c, kind, predicate, obj, allow_external_objects)
            if path is not None:
                path = path.replace("{self}", new_id)
                if c.execute("SELECT adid FROM entities WHERE path=?", (path,)).fetchone():
                    raise AltIdConflict(f"ADID path {path} is already issued.")
            c.execute(
                "INSERT INTO entities VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (new_id, kind, registrar, "active", None, _canonical(metadata), 1, now, now, GENESIS, path),
            )
            c.executemany(
                "INSERT INTO alt_ids VALUES (?,?,?,?)",
                [(s, v, new_id, now) for s, v in alt_ids],
            )
            c.executemany(
                "INSERT INTO relations VALUES (?,?,?,?)",
                [(new_id, p, o, now) for p, o in relations],
            )
            self._refresh_facets(c, new_id, metadata)
            self._append_history(c, new_id, "register", actor or registrar, 1)
        return new_id

    def _check_relation(
        self, c: sqlite3.Connection, subject_kind: str, predicate: str, obj: str, external_ok: bool
    ) -> None:
        if predicate not in PREDICATES:
            raise RelationError(f"Unknown relation '{predicate}'. Expected one of {sorted(PREDICATES)}.")
        subject_kinds, object_kind = PREDICATES[predicate]
        if subject_kind not in subject_kinds:
            raise RelationError(f"A {subject_kind} cannot be the subject of '{predicate}'.")
        row = c.execute("SELECT kind FROM entities WHERE adid=?", (obj,)).fetchone()
        if row is None:
            if external_ok:
                return
            raise RelationError(f"'{predicate}' points at {obj}, which is not registered here.")
        if row[0] != object_kind:
            raise RelationError(f"'{predicate}' must point at a {object_kind}, not a {row[0]}.")

    def _bump(self, c: sqlite3.Connection, adid: str) -> int:
        row = c.execute("SELECT version FROM entities WHERE adid=?", (adid,)).fetchone()
        if row is None:
            raise RegistryError(f"No entity {adid}.")
        version = row[0] + 1
        c.execute("UPDATE entities SET version=?, updated_at=? WHERE adid=?", (version, _now(), adid))
        return version

    def update(self, adid: str, changes: dict[str, Any], actor: str) -> int:
        """Change attribute metadata. The ADID is untouched by construction.

        A value of ``None`` or ``""`` removes the attribute.
        """
        with self.transaction() as c:
            row = c.execute("SELECT metadata, status FROM entities WHERE adid=?", (adid,)).fetchone()
            if row is None:
                raise RegistryError(f"No entity {adid}.")
            if row[1] == "withdrawn":
                raise RegistryError("A withdrawn entity cannot be edited.")
            metadata = json.loads(row[0])
            for k, v in changes.items():
                if v in (None, ""):
                    metadata.pop(k, None)
                else:
                    metadata[k] = v
            c.execute("UPDATE entities SET metadata=? WHERE adid=?", (_canonical(metadata), adid))
            self._refresh_facets(c, adid, metadata)
            version = self._bump(c, adid)
            self._append_history(c, adid, "update", actor, version)
        return version

    def add_alt_id(self, adid: str, scheme: str, value: str, actor: str) -> None:
        with self.transaction() as c:
            held = c.execute("SELECT adid FROM alt_ids WHERE scheme=? AND value=?", (scheme, value)).fetchone()
            if held:
                if held[0] == adid:
                    return
                raise AltIdConflict(f"{scheme} '{value}' is already registered to {held[0]}.")
            c.execute("INSERT INTO alt_ids VALUES (?,?,?,?)", (scheme, value, adid, _now()))
            version = self._bump(c, adid)
            self._append_history(c, adid, f"add_alt_id:{scheme}", actor, version)

    def relate(self, subject: str, predicate: str, obj: str, actor: str, allow_external: bool = False) -> None:
        with self.transaction() as c:
            row = c.execute("SELECT kind FROM entities WHERE adid=?", (subject,)).fetchone()
            if row is None:
                raise RelationError(f"No entity {subject}.")
            if c.execute(
                "SELECT 1 FROM relations WHERE subject=? AND predicate=? AND object=?",
                (subject, predicate, obj),
            ).fetchone():
                return
            self._check_relation(c, row[0], predicate, obj, allow_external)
            c.execute("INSERT INTO relations VALUES (?,?,?,?)", (subject, predicate, obj, _now()))
            self._refresh_facets(c, subject)
            version = self._bump(c, subject)
            self._append_history(c, subject, f"relate:{predicate}", actor, version)

    def set_status(self, adid: str, status: str, actor: str, replaced_by: str | None = None) -> int:
        """Deprecate (superseded, still resolvable), withdraw (registered in
        error — tombstone only) or mark moved (now held by another node)."""
        if status not in STATUSES:
            raise RegistryError(f"Unknown status '{status}'.")
        if replaced_by is not None:
            replaced_by = parse_adid(replaced_by)
        with self.transaction() as c:
            c.execute("UPDATE entities SET status=?, replaced_by=? WHERE adid=?", (status, replaced_by, adid))
            version = self._bump(c, adid)
            self._append_history(c, adid, f"status:{status}", actor, version)
        return version

    # ----------------------------------------------------------- governance
    def history(self, adid: str) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT version, at, actor, action, prev_hash, hash FROM history WHERE adid=? ORDER BY version",
            (adid,),
        )
        return [
            {"version": v, "at": at, "actor": actor, "action": action, "prev_hash": p, "hash": h}
            for v, at, actor, action, p, h in rows
        ]

    def verify(self, adid: str) -> VerifyResult:
        """Recompute the hash chain and compare its head with the live record.

        Detects: an edited or deleted history row, a reordered chain, and any
        change to the entity, its alternate identifiers or its relations that
        was made without going through the store (e.g. directly in SQLite).
        """
        problems: list[str] = []
        rows = self._q(
            "SELECT version, snapshot, prev_hash, hash FROM history WHERE adid=? ORDER BY version",
            (adid,),
        )
        if not rows:
            return VerifyResult(adid, False, 0, ["No history for this ADID."])
        expected_prev = GENESIS
        for i, (version, snapshot, prev_hash, digest) in enumerate(rows, start=1):
            if version != i:
                problems.append(f"Version {i} missing (found {version}).")
            if prev_hash != expected_prev:
                problems.append(f"v{version}: chain link broken.")
            if _sha(prev_hash + snapshot) != digest:
                problems.append(f"v{version}: snapshot does not match its hash.")
            expected_prev = digest
        entity = self._q("SELECT head_hash, version FROM entities WHERE adid=?", (adid,))
        if not entity:
            problems.append("Entity row missing.")
        else:
            head, version = entity[0]
            if head != expected_prev or version != len(rows):
                problems.append("Entity head does not match the last history entry.")
            if _canonical(self._snapshot(adid)) != rows[-1][1]:
                problems.append("Live record differs from the last recorded snapshot (edited outside the registry).")
        return VerifyResult(adid, not problems, len(rows), problems)

    # ---------------------------------------------------------------- search
    def search(
        self,
        filters: dict[str, str],
        kinds: tuple[str, ...] | list[str] | None = None,
        registrar: str | None = None,
        status: str | None = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[str]:
        """Find ADIDs whose normalised facets equal every given filter."""
        unknown = set(filters) - set(FACET_FIELDS)
        if unknown:
            raise RegistryError(f"Not searchable: {sorted(unknown)}. Searchable fields: {list(FACET_FIELDS)}.")
        sql = "SELECT e.adid FROM entities e"
        params: list[Any] = []
        for i, (f, v) in enumerate(sorted(filters.items())):
            sql += f" JOIN facets f{i} ON f{i}.adid=e.adid AND f{i}.field=? AND f{i}.value=?"
            params += [f, normalise_facet(v)]
        where = []
        if kinds:
            where.append(f"e.kind IN ({','.join('?' * len(kinds))})")
            params += list(kinds)
        if registrar:
            where.append("e.registrar=?")
            params.append(registrar)
        if status:
            where.append("e.status=?")
            params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Order by the first facet's index so SQLite streams matches and stops at
        # the page limit instead of materialising and sorting every hit.
        sql += (" ORDER BY f0.adid" if filters else " ORDER BY e.adid") + " LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [r[0] for r in self._q(sql, tuple(params))]

    # ------------------------------------------------------------- migration
    def export_bundle(self, adid: str) -> dict[str, Any]:
        """Everything needed to re-home an entity on another node, history included."""
        ent = self._q("SELECT * FROM entities WHERE adid=?", (adid,))
        if not ent:
            raise RegistryError(f"No entity {adid}.")
        return {
            "entity": list(ent[0]),
            "alt_ids": [list(r) for r in self._q("SELECT * FROM alt_ids WHERE adid=?", (adid,))],
            "relations": [list(r) for r in self._q("SELECT * FROM relations WHERE subject=?", (adid,))],
            "history": [list(r) for r in self._q("SELECT * FROM history WHERE adid=? ORDER BY version", (adid,))],
        }

    def import_bundle(self, bundle: dict[str, Any]) -> str:
        """Re-home an entity exported by another node, preserving its ADID and
        its hash chain byte for byte (so :meth:`verify` still passes)."""
        e = bundle["entity"]
        with self.transaction() as c:
            c.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(e))
            c.executemany("INSERT OR IGNORE INTO alt_ids VALUES (?,?,?,?)", [tuple(r) for r in bundle["alt_ids"]])
            c.executemany("INSERT INTO relations VALUES (?,?,?,?)", [tuple(r) for r in bundle["relations"]])
            c.executemany("INSERT INTO history VALUES (?,?,?,?,?,?,?,?)", [tuple(r) for r in bundle["history"]])
            self._refresh_facets(c, e[0], json.loads(e[5]))
        return e[0]

    # --------------------------------------------------------------- versions
    def snapshot_at(self, adid: str, version: int) -> dict[str, Any] | None:
        """The recorded state of ``adid`` at ``version`` (for 'view old version')."""
        rows = self._q("SELECT snapshot FROM history WHERE adid=? AND version=?", (adid, version))
        return json.loads(rows[0][0]) if rows else None

    def registrars_with_entities(self) -> list[str]:
        """Registrars that have registered at least one record."""
        return [r[0] for r in self._q("SELECT DISTINCT registrar FROM entities ORDER BY registrar")]

    def owned_by(self, registrar: str, kind: str | None = None, limit: int = 500) -> list[str]:
        """ADIDs a registrar owns, newest first."""
        sql = "SELECT adid FROM entities WHERE registrar=?"
        params: tuple = (registrar,)
        if kind:
            sql += " AND kind=?"
            params += (kind,)
        return [r[0] for r in self._q(sql + " ORDER BY created_at DESC LIMIT ?", params + (limit,))]
