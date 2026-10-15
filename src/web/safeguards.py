"""Prototype safeguards for the website (D61).

These reduce obvious risks in a research prototype. They do not amount to a
security assessment, and nothing in the project claims the site is
"certified secure". What each one does:

* :func:`safe_next` — only same-site relative paths are followed after login.
  ``//evil.example`` passes a plain ``startswith("/")`` test and is a
  protocol-relative redirect to another site (an open redirect).
* :class:`LoginThrottle` — locks a username and a client address after
  repeated failed sign-ins, slowing password guessing.
* :data:`UPLOAD_TTL_SECONDS` — an uploaded file under review expires, so
  manufacturer data does not sit in memory indefinitely.
* :func:`max_upload_bytes` — reads the frozen ingestion limit, so the website
  refuses what the gateway would refuse, before parsing.
* :class:`AuditLog` — append-only record of sign-ins, failed sign-ins,
  account decisions and registrations, shown to the operator.

Secure (HTTPS-only) session cookies are switched on by ``web.secure_cookies``
in ``config/registry.yaml`` or ``ADIR_SECURE_COOKIES=1``. They stay off by
default only because the demonstration runs on plain ``http://127.0.0.1``.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from src.dbconn import connect
__all__ = ["AuditLog", "LoginThrottle", "UPLOAD_TTL_SECONDS", "max_upload_bytes", "safe_next"]

UPLOAD_TTL_SECONDS = 2 * 3600


def safe_next(target: str | None, default: str = "/portal") -> str:
    """Return ``target`` only if it is a same-site relative path, else ``default``."""
    if not target:
        return default
    text = str(target).strip()
    if any(ord(c) < 32 for c in text) or "\\" in text:
        return default
    parts = urlsplit(text)
    if parts.scheme or parts.netloc or not text.startswith("/") or text.startswith("//"):
        return default
    return text


def max_upload_bytes(default_mb: int = 50) -> int:
    """The ingestion size limit from the frozen config, in bytes."""
    try:
        from src.config import load_config

        return int(load_config().ingestion.max_file_size_mb) * 1024 * 1024
    except Exception:  # noqa: BLE001 - fall back to a conservative limit
        return default_mb * 1024 * 1024


class LoginThrottle:
    """Sliding-window limit on failed sign-ins, per username and per address."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 900) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, *keys: str) -> int:
        """Seconds until sign-in is allowed again for any of ``keys``; 0 if allowed."""
        now = time.monotonic()
        with self._lock:
            wait = 0
            for key in keys:
                q = self._prune(key, now)
                if len(q) >= self.max_failures:
                    wait = max(wait, int(self.window - (now - q[0])) + 1)
            return wait

    def failed(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._prune(key, now).append(now)

    def succeeded(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._fails.pop(key, None)


_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    target  TEXT NOT NULL,
    outcome TEXT NOT NULL,
    client  TEXT NOT NULL
);
"""


class AuditLog:
    """Append-only access log. There is deliberately no update or delete method."""

    def __init__(self, db_path: str | Path) -> None:
        db = str(db_path)
        if db != ":memory:":
            Path(db).parent.mkdir(parents=True, exist_ok=True)
        self._conn = connect(db)
        self._conn.executescript(_AUDIT_SCHEMA)
        self._lock = threading.RLock()

    def log(self, actor: str, action: str, target: str = "", outcome: str = "ok", client: str = "") -> None:
        """Record one event."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (at, actor, action, target, outcome, client) VALUES (?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), actor or "-", action,
                 target, outcome, client),
            )

    def recent(self, limit: int = 50) -> list[dict[str, str]]:
        """Most recent events first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT at, actor, action, target, outcome, client FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(zip(("at", "actor", "action", "target", "outcome", "client"), r)) for r in rows]
