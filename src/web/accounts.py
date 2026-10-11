"""Web accounts: who may sign in, and as what (D48).

Accounts map a person to a registry principal. A manufacturer account is
created **pending** and can do nothing until the registry operator approves
it — the registry equivalent of ICANN accrediting a registrar before it may
register names. Authority accounts are created by the operator only.

Passwords are stored as PBKDF2-HMAC-SHA256 hashes with a per-account salt
(standard library only, no extra dependency).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.identity.adid import AdidError, slugify
from src.registry.policy import Principal, Role

__all__ = ["Account", "AccountError", "AccountStore"]

ITERATIONS = 240_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    username     TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    organisation TEXT NOT NULL,
    registrar_id TEXT NOT NULL,
    role         TEXT NOT NULL,
    status       TEXT NOT NULL,
    salt         TEXT NOT NULL,
    pw_hash      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    approved_by  TEXT,
    approved_at  TEXT
);
"""


class AccountError(Exception):
    """An account operation was refused, with a reason a person can act on."""


@dataclass(frozen=True)
class Account:
    username: str
    display_name: str
    organisation: str
    registrar_id: str
    role: Role
    status: str
    created_at: str
    approved_by: str | None

    @property
    def active(self) -> bool:
        return self.status == "active"

    def principal(self) -> Principal:
        """The registry principal this account acts as."""
        return Principal(self.role, self.registrar_id)


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AccountStore:
    """SQLite-backed accounts."""

    def __init__(self, db_path: str | Path) -> None:
        db = str(db_path)
        if db != ":memory:":
            Path(db).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db, check_same_thread=False, isolation_level=None)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()

    def _q(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @staticmethod
    def _row(r: tuple) -> Account:
        return Account(r[0], r[1], r[2], r[3], Role(r[4]), r[5], r[8], r[9])

    def create(
        self,
        username: str,
        password: str,
        display_name: str,
        organisation: str,
        role: Role | str = Role.REGISTRANT,
        status: str = "pending",
        registrar_id: str | None = None,
    ) -> Account:
        """Create an account. Manufacturers start ``pending`` by default."""
        username = username.strip().lower()
        if not username or "@" not in username and len(username) < 3:
            raise AccountError("Use an email address or a username of at least 3 characters.")
        if len(password) < 10:
            raise AccountError("Use a password of at least 10 characters.")
        role = Role(role)
        try:
            registrar = registrar_id or slugify(organisation)
        except AdidError:
            raise AccountError("The organisation name needs at least one letter or number.") from None
        if self._q("SELECT 1 FROM accounts WHERE username=?", (username,)):
            raise AccountError("An account with that username already exists.")
        if role == Role.REGISTRANT and self._q(
            "SELECT 1 FROM accounts WHERE registrar_id=? AND role='registrant'", (registrar,)
        ):
            raise AccountError(
                f"The organisation '{organisation}' is already registered. Ask its existing account holder, "
                "or the registry operator, to add you."
            )
        salt = secrets.token_hex(16)
        self._q(
            "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (username, display_name.strip() or username, organisation.strip(), registrar, role.value,
             status, salt, _hash(password, salt), _now(), None, None),
        )
        return self.get(username)

    def get(self, username: str) -> Account | None:
        rows = self._q("SELECT * FROM accounts WHERE username=?", (username.strip().lower(),))
        return self._row(rows[0]) if rows else None

    def authenticate(self, username: str, password: str) -> Account:
        """Check a password. Raises with a reason; never says which part was wrong."""
        rows = self._q("SELECT * FROM accounts WHERE username=?", (username.strip().lower(),))
        if not rows or not hmac.compare_digest(_hash(password, rows[0][6]), rows[0][7]):
            raise AccountError("That username and password do not match an account.")
        account = self._row(rows[0])
        if account.status == "pending":
            raise AccountError("Your account is waiting for the registry operator to approve it.")
        if account.status != "active":
            raise AccountError("This account is suspended. Contact the registry operator.")
        return account

    def set_status(self, username: str, status: str, actor: str) -> None:
        if status not in ("active", "pending", "suspended", "rejected"):
            raise AccountError(f"Unknown status '{status}'.")
        self._q(
            "UPDATE accounts SET status=?, approved_by=?, approved_at=? WHERE username=?",
            (status, actor, _now(), username),
        )

    def pending(self) -> list[Account]:
        return [self._row(r) for r in self._q("SELECT * FROM accounts WHERE status='pending' ORDER BY created_at")]

    def all(self) -> list[Account]:
        return [self._row(r) for r in self._q("SELECT * FROM accounts ORDER BY role, created_at")]

    def count(self, role: Role | None = None) -> int:
        if role:
            return self._q("SELECT COUNT(*) FROM accounts WHERE role=?", (role.value,))[0][0]
        return self._q("SELECT COUNT(*) FROM accounts")[0][0]
