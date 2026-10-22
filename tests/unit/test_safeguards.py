"""Website prototype safeguards (D61)."""

from __future__ import annotations

import re
import time

import pytest
from fastapi.testclient import TestClient

from src.web.safeguards import UPLOAD_TTL_SECONDS, AuditLog, LoginThrottle, safe_next
from tests.unit.test_web import HTML, PW, csrf_of, login, site  # noqa: F401  (fixture)


@pytest.mark.parametrize("target,expected", [
    ("/portal/upload", "/portal/upload"),
    ("//evil.example/x", "/portal"),          # protocol-relative: an open redirect
    ("https://evil.example", "/portal"),
    ("/\\evil.example", "/portal"),
    ("javascript:alert(1)", "/portal"),
    ("/ok\nSet-Cookie: x", "/portal"),
    ("", "/portal"),
])
def test_safe_next_only_follows_same_site_paths(target, expected):
    assert safe_next(target) == expected


def test_login_does_not_redirect_off_site(site):
    app, *_ = site
    c = TestClient(app)
    r = c.post("/login", data={"csrf": csrf_of(c), "username": "me@demoknit.org", "password": PW,
                               "next": "//evil.example/phish"}, headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/portal"


def test_repeated_failed_logins_are_throttled_and_logged(site):
    app, *_ = site
    c = TestClient(app)
    for _ in range(5):
        r = c.post("/login", data={"csrf": csrf_of(c), "username": "me@demoknit.org", "password": "wrong"},
                   headers=HTML, follow_redirects=False)
        assert r.status_code == 401
    r = c.post("/login", data={"csrf": csrf_of(c), "username": "me@demoknit.org", "password": PW},
               headers=HTML, follow_redirects=False)
    assert r.status_code == 429                       # even the right password waits
    outcomes = [e["outcome"] for e in app.state.audit.recent()]
    assert outcomes.count("failed") == 5 and "throttled" in outcomes


def test_successful_login_and_account_decision_are_audited(site):
    app, _, accounts, _ = site
    from src.registry.policy import Role
    accounts.create("new@x.org", PW, "New", "New Co", Role.REGISTRANT, "pending", "new-co")
    c = TestClient(app)
    login(c, "op@x.org")
    token = csrf_of(c, "/admin")
    c.post("/admin/accounts/new@x.org/approve", data={"csrf": token}, headers=HTML, follow_redirects=False)
    actions = [(e["actor"], e["action"]) for e in app.state.audit.recent()]
    assert ("op@x.org", "login") in actions and ("op@x.org", "account_approve") in actions
    assert "Access log" in c.get("/admin", headers=HTML).text


def test_uploads_expire(site):
    app, *_ = site
    c = TestClient(app)
    login(c, "me@demoknit.org")
    token = csrf_of(c, "/portal/upload")
    with open("demo/demo_knitwear_export_spring.csv", "rb") as fh:
        r = c.post("/portal/upload", data={"csrf": token}, files={"file": ("s.csv", fh, "text/csv")},
                   headers=HTML, follow_redirects=False)
    review = r.headers["location"]
    up = next(iter(app.state.uploads.values()))
    up.created_at = time.time() - UPLOAD_TTL_SECONDS - 1
    assert c.get(review, headers=HTML).status_code == 404


def test_audit_log_has_no_update_or_delete():
    log = AuditLog(":memory:")
    log.log("a", "login")
    assert not any(hasattr(log, m) for m in ("delete", "update", "clear"))
    assert log.recent()[0]["action"] == "login"


def test_throttle_window_resets_after_success():
    t = LoginThrottle(max_failures=2, window_seconds=60)
    t.failed("k"); t.failed("k")
    assert t.blocked("k") > 0
    t.succeeded("k")
    assert t.blocked("k") == 0


def test_pending_account_sign_in_is_not_counted_as_guessing(site):
    """Showing that a pending account cannot sign in must not lock the room out."""
    app, _, accounts, _ = site
    from src.registry.policy import Role as _Role
    accounts.create("waiting@pending.org", "pending-pass-123", "W", "Pending Org", _Role.REGISTRANT, "pending")
    c = TestClient(app)
    for _ in range(8):
        token = re.search(r'name="csrf" value="([^"]+)"', c.get("/login", headers=HTML).text).group(1)
        r = c.post("/login", data={"csrf": token, "username": "waiting@pending.org",
                                   "password": "pending-pass-123", "next": "/portal"}, headers=HTML)
        assert r.status_code == 401 and "waiting for the registry operator" in r.text


def test_typing_mistakes_by_several_people_do_not_lock_out_the_room(site):
    """Many people behind one address: a few wrong passwords must not block everyone."""
    app, *_ = site
    c = TestClient(app)
    for user in ("a@x.org", "b@x.org", "c@x.org", "d@x.org", "e@x.org", "f@x.org"):
        r = c.post("/login", data={"csrf": csrf_of(c), "username": user, "password": "wrong"},
                   headers=HTML, follow_redirects=False)
        assert r.status_code == 401
    r = c.post("/login", data={"csrf": csrf_of(c), "username": "me@demoknit.org", "password": PW},
               headers=HTML, follow_redirects=False)
    assert r.status_code == 303
