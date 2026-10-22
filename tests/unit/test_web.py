"""ADIR website and manufacturer portal (D48-D50)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from src.registry.federation import RegistryNode, RootIndex
from src.registry.policy import AccessPolicy, Role
from src.registry.store import RegistryStore
from src.web.accounts import AccountError, AccountStore
from src.web.app import create_web_app
from src.web.library import TemplateLibrary

HTML = {"Accept": "text/html"}
PW = "correct-horse-battery"


@pytest.fixture
def site():
    node = RegistryNode("lk-1", RegistryStore(":memory:"), RootIndex(":memory:"), AccessPolicy.load())
    accounts = AccountStore(":memory:")
    library = TemplateLibrary(":memory:")
    app = create_web_app(node, accounts, library, secret_key="test-secret")
    accounts.create("op@x.org", PW, "Op", "Registry operator", Role.OPERATOR, "active", "operator")
    accounts.create("me@demoknit.org", PW, "Nimali", "Demo Knit Works", Role.REGISTRANT, "active", "demoknit")
    accounts.create("rival@other.org", PW, "Rival", "Other Co", Role.REGISTRANT, "active", "other-co")
    accounts.create("officer@customs.org", PW, "Officer", "Customs", Role.AUTHORITY, "active", "customs")
    return app, node, accounts, library


def csrf_of(client: TestClient, path: str = "/login") -> str:
    page = client.get(path, headers=HTML).text
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def login(client: TestClient, user: str) -> None:
    token = csrf_of(client)
    r = client.post("/login", data={"csrf": token, "username": user, "password": PW, "next": "/portal"},
                    headers=HTML, follow_redirects=False)
    assert r.status_code == 303, r.text


def upload_and_register(client: TestClient, template_name: str = "") -> str:
    token = csrf_of(client, "/portal/upload")
    with open("demo/demo_knitwear_export_spring.csv", "rb") as fh:
        r = client.post("/portal/upload", data={"csrf": token, "template": ""},
                        files={"file": ("spring.csv", fh, "text/csv")}, headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and "/portal/review/" in r.headers["location"]
    review_url = r.headers["location"]
    page = client.get(review_url, headers=HTML).text
    choices = dict(re.findall(r'<select id="(map_\d+)" name="map_\d+">.*?<option value="([^"]+)"[^>]*selected', page, re.S))
    # the regex above picks the first selected option per select
    data = {"csrf": token, "template_name": template_name, **choices}
    r = client.post(review_url, data=data, headers=HTML, follow_redirects=False)
    assert r.status_code == 303
    up_token = review_url.rsplit("/", 1)[1]
    r = client.post(f"/portal/register/{up_token}", data={"csrf": token}, headers=HTML, follow_redirects=False)
    assert r.status_code == 303
    return up_token


def test_public_pages_render(site):
    app, *_ = site
    c = TestClient(app)
    for path in ("/", "/about", "/welcome", "/registry", "/how-it-works", "/login", "/signup"):
        r = c.get(path, headers=HTML)
        assert r.status_code == 200, path
    assert "address for life" in c.get("/about", headers=HTML).text
    assert "Look up an apparel product passport" in c.get("/", headers=HTML).text


def test_signup_is_pending_until_the_operator_approves(site):
    app, node, accounts, _ = site
    c = TestClient(app)
    token = csrf_of(c, "/signup")
    r = c.post("/signup", data={"csrf": token, "organisation": "Galle Apparel", "display_name": "A",
                                "username": "a@galle.org", "password": PW, "password2": PW}, headers=HTML)
    assert r.status_code == 200 and "waiting" in r.text
    with pytest.raises(AccountError, match="waiting"):
        accounts.authenticate("a@galle.org", PW)
    op = TestClient(app)
    login(op, "op@x.org")
    t = csrf_of(op, "/admin")
    op.post("/admin/accounts/a@galle.org/approve", data={"csrf": t}, headers=HTML)
    assert accounts.authenticate("a@galle.org", PW).active


def test_portal_requires_login_and_csrf(site):
    app, *_ = site
    c = TestClient(app)
    r = c.get("/portal/upload", headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    login(c, "me@demoknit.org")
    r = c.post("/portal/templates/x/restore/1", data={}, headers=HTML)
    assert r.status_code == 400


def test_upload_review_register_and_resolve_as_html_and_json(site):
    app, node, *_ = site
    c = TestClient(app)
    login(c, "me@demoknit.org")
    token = upload_and_register(c, template_name="Knitwear export")
    page = c.get(f"/portal/registered/{token}", headers=HTML).text
    adid = re.search(r"/adid/([0-9a-f-]{36})", page).group(1)
    # Same URI: a page for browsers, JSON for machines, JSON-LD on request.
    assert "This product's address" in c.get(f"/adid/{adid}", headers=HTML).text
    assert c.get(f"/adid/{adid}").json()["adid"] == adid
    assert c.get(f"/adid/{adid}", headers={"Accept": "application/ld+json"}).json()["@id"].endswith(adid)
    assert node.store.count("family") >= 1


def test_template_names_version_instead_of_overwriting(site):
    app, _, _, library = site
    c = TestClient(app)
    login(c, "me@demoknit.org")
    upload_and_register(c, template_name="Knitwear export")
    upload_and_register(c, template_name="Knitwear export")
    versions = library.versions("demoknit", "Knitwear export")
    assert [v.version for v in versions] == [2, 1]
    token = csrf_of(c, "/portal/templates")
    c.post("/portal/templates/Knitwear export/restore/1", data={"csrf": token}, headers=HTML)
    assert [v.version for v in library.versions("demoknit", "Knitwear export")] == [3, 2, 1]
    assert library.versions("other-co", "Knitwear export") == []   # private to the registrar


def test_edit_creates_a_version_and_never_changes_the_adid_or_locked_fields(site):
    app, node, *_ = site
    c = TestClient(app)
    login(c, "me@demoknit.org")
    upload_and_register(c)
    variant = node.store.search({"colour": "navy", "size": "m"}, kinds=["variant"])[0]
    before = node.store.get(variant)
    token = csrf_of(c, f"/portal/edit/{variant}")
    r = c.post(f"/portal/edit/{variant}", data={"csrf": token, "f_colour": "Navy Blue", "f_gtin": "0000000000000"},
               headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == before.path
    after = node.store.get(variant)
    assert after.adid == before.adid and after.version == before.version + 1
    assert after.metadata["colour"] == "Navy Blue"
    assert after.metadata["gtin"] == before.metadata["gtin"]        # locked field ignored
    assert node.store.verify(variant).ok
    old = c.get(f"/id/{variant}/v/{before.version}", headers=HTML)
    assert old.status_code == 200 and "Navy" in old.text


def test_other_manufacturers_and_the_public_cannot_change_a_record(site):
    app, node, *_ = site
    owner = TestClient(app)
    login(owner, "me@demoknit.org")
    upload_and_register(owner)
    variant = node.store.search({"colour": "navy"}, kinds=["variant"])[0]
    rival = TestClient(app)
    login(rival, "rival@other.org")
    assert rival.get(f"/portal/edit/{variant}", headers=HTML).status_code == 403
    token = csrf_of(rival, "/portal")
    assert rival.post(f"/portal/edit/{variant}", data={"csrf": token, "f_colour": "Red"},
                      headers=HTML).status_code == 403
    public = TestClient(app)
    assert public.get(f"/portal/edit/{variant}", headers=HTML, follow_redirects=False).status_code == 303
    assert node.store.get(variant).metadata["colour"] == "Navy"


def test_restricted_sections_follow_the_signed_in_role(site):
    app, node, *_ = site
    owner = TestClient(app)
    login(owner, "me@demoknit.org")
    upload_and_register(owner)
    variant = node.store.search({"batchNumber": "DL-7700"}, kinds=["variant"])[0]
    vpath = node.store.get(variant).path
    public = TestClient(app)
    page = public.get(vpath, headers=HTML).text
    assert "Purchase order" not in page and "Batch number" not in page
    assert public.get("/portal/lot?batch=DL-7700", headers=HTML, follow_redirects=False).status_code == 303
    officer = TestClient(app)
    login(officer, "officer@customs.org")
    assert "Batch number" in officer.get(vpath, headers=HTML).text
    lot = officer.get("/portal/lot?batch=DL-7700", headers=HTML)
    assert lot.status_code == 200 and vpath in lot.text


def test_neighbourhood_endpoint(site):
    app, node, *_ = site
    c = TestClient(app)
    login(c, "me@demoknit.org")
    upload_and_register(c)
    variant = node.store.search({"colour": "navy", "size": "m"}, kinds=["variant"])[0]
    near = TestClient(app).get(f"/id/{variant}/neighbourhood").json()
    assert near["up"] and near["up"][0]["kind"] == "family"
    assert all(s["kind"] == "variant" for s in near["siblings"])
    assert near["lot"] is None          # lot membership hidden from the public


def test_admin_is_operator_only_and_shows_frozen_hashes(site):
    app, *_ = site
    maker = TestClient(app)
    login(maker, "me@demoknit.org")
    assert maker.get("/admin", headers=HTML).status_code == 403
    op = TestClient(app)
    login(op, "op@x.org")
    page = op.get("/admin", headers=HTML).text
    assert "Frozen research artefacts" in page and "cdm/cdm_v1.0.schema.json" in page


def test_site_avoids_overclaiming_phrases(site):
    app, *_ = site
    c = TestClient(app)
    banned = ["EU DPP certified", "Guaranteed compliance", "100% accurate", "Official universal",
              "never break", "never changes", "legally designated DPP authority"]
    for path in ("/", "/registry", "/how-it-works", "/signup", "/login"):
        text = c.get(path, headers=HTML).text
        for phrase in banned:
            assert phrase.lower() not in text.lower(), (path, phrase)


def test_two_host_layout_sends_accounts_to_the_app_host(monkeypatch):
    """adif.my is the registry; signing in and joining happen on app.adif.my."""
    monkeypatch.setenv("ADIF_PUBLIC_HOST", "adif.my")
    monkeypatch.setenv("ADIF_APP_HOST", "app.adif.my")
    node = RegistryNode("lk-1", RegistryStore(":memory:"), RootIndex(":memory:"), AccessPolicy.load())
    app = create_web_app(node, AccountStore(":memory:"), TemplateLibrary(":memory:"), secret_key="t")
    public = TestClient(app, base_url="https://adif.my")
    account = TestClient(app, base_url="https://app.adif.my")
    front = public.get("/", headers=HTML)
    assert "Look up an apparel product passport" in front.text and "https://app.adif.my/welcome" in front.text
    for path in ("/login", "/signup", "/portal", "/admin"):
        r = public.get(path, headers=HTML, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == f"https://app.adif.my{path}"
    assert "Who are you signing in as?" in account.get("/", headers=HTML).text
    r = account.get("/registry?kind=variant", headers=HTML, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "https://adif.my/registry?kind=variant"
    assert account.get("/login?as=authority", headers=HTML).status_code == 200


@pytest.mark.parametrize("public_setting", ["www.adif.my", "adif.my"])
def test_app_host_signup_and_shared_sign_in(monkeypatch, public_setting):
    """Production layout: Render serves www.adif.my (adif.my redirects to it) and app.adif.my.

    Signing up happens on app.adif.my; one sign-in then works on both hosts, and a form on the
    registry host that posts to the app host (sign out) is accepted. The app must never
    redirect www.adif.my to adif.my itself, or it loops with Render's own redirect.
    """
    monkeypatch.setenv("ADIF_PUBLIC_HOST", public_setting)
    monkeypatch.setenv("ADIF_APP_HOST", "app.adif.my")
    monkeypatch.delenv("ADIF_COOKIE_DOMAIN", raising=False)
    node = RegistryNode("lk-1", RegistryStore(":memory:"), RootIndex(":memory:"), AccessPolicy.load())
    accounts = AccountStore(":memory:")
    app = create_web_app(node, accounts, TemplateLibrary(":memory:"), secret_key="t")
    accounts.create("op@x.org", PW, "Op", "Registry operator", Role.OPERATOR, "active", "operator")
    c = TestClient(app)
    www, appx = "https://www.adif.my", "https://app.adif.my"

    # 1. The public registry answers on www without bouncing to the bare domain.
    r = c.get(www + "/", headers=HTML, follow_redirects=False)
    assert r.status_code == 200 and "https://app.adif.my/welcome" in r.text
    # 2. Account pages on either public host go to the app host.
    for host in (www, "https://adif.my"):
        r = c.get(host + "/signup", headers=HTML, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == appx + "/signup"
    # 3. Sign up on the app host.
    page = c.get(appx + "/signup", headers=HTML)
    assert page.status_code == 200
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    r = c.post(appx + "/signup", headers=HTML, data={
        "csrf": token, "organisation": "Lanka Threads", "display_name": "Ayesha",
        "username": "ayesha@lankathreads.lk", "password": PW, "password2": PW})
    assert r.status_code == 200 and "lankathreads.lk" in r.text
    assert accounts.get("ayesha@lankathreads.lk").status == "pending"
    # 4. The operator approves it on the app host.
    token = re.search(r'name="csrf" value="([^"]+)"', c.get(appx + "/login", headers=HTML).text).group(1)
    r = c.post(appx + "/login", headers=HTML, follow_redirects=False,
               data={"csrf": token, "username": "op@x.org", "password": PW, "next": "/admin"})
    assert r.status_code == 303
    assert "domain=.adif.my" in r.headers["set-cookie"].lower() and "secure" in r.headers["set-cookie"].lower()
    admin = c.get(appx + "/admin", headers=HTML)
    assert "Lanka Threads" in admin.text
    token = re.search(r'name="csrf" value="([^"]+)"', admin.text).group(1)
    r = c.post(appx + "/admin/accounts/ayesha@lankathreads.lk/approve", headers=HTML,
               data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303 and accounts.get("ayesha@lankathreads.lk").status == "active"
    # 5. The operator's sign-in is visible on the public host too, and signing out there works.
    front = c.get(www + "/", headers=HTML)
    assert "Sign out" in front.text
    token = re.search(r'name="csrf" value="([^"]+)"', front.text).group(1)
    r = c.post(appx + "/logout", headers=HTML, data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    # 6. The new manufacturer can now sign in on the app host and reach the portal.
    token = re.search(r'name="csrf" value="([^"]+)"', c.get(appx + "/login", headers=HTML).text).group(1)
    r = c.post(appx + "/login", headers=HTML, follow_redirects=False,
               data={"csrf": token, "username": "ayesha@lankathreads.lk", "password": PW, "next": "/portal"})
    assert r.status_code == 303
    assert c.get(appx + "/portal", headers=HTML).status_code == 200


def test_bare_style_code_finds_the_design(site):
    """Typing a style code without the manufacturer prefix still finds the design."""
    app, node, *_ = site
    c = TestClient(app)
    login(c, "me@demoknit.org")
    upload_and_register(c)
    anon = TestClient(app)
    r = anon.get("/registry?q=TS-1000", headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/adid/")
    assert anon.get(r.headers["location"], headers=HTML).status_code == 200
    r = anon.get("/registry?q=NO-SUCH-STYLE", headers=HTML)
    assert r.status_code == 200 and "Nothing is registered" in r.text
