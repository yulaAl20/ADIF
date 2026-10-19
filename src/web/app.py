"""The ADIF website: public pages, ADID product pages and the manufacturer portal.

Run::

    python -m scripts.seed_demo                      # optional: demo accounts and products
    uvicorn src.web.app:build --factory --port 8000

One app serves everything. The registry API (``src.registry.api``) is the base
application, so ``/adid/{uuid}`` is a single URI that answers a browser with a
product page and a machine with JSON or JSON-LD (D48). The website adds:

=========================  ====================================================
Public                     ``/`` landing · ``/registry`` lookup and search ·
                           ``/how-it-works`` · ``/adid/{uuid}`` product page
Accounts                   ``/login`` · ``/signup`` (manufacturer, pending
                           approval) · ``/logout``
Manufacturer portal        ``/portal`` · upload → review → register ·
                           products · edit details (versioned) · templates
                           (versioned)
Operator                   ``/portal/admin`` — approve accounts, create
                           authority accounts
=========================  ====================================================

Access is enforced on the server by the registry's own policy (D46); the
website never decides on its own what a role may see.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from urllib.parse import quote
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from src.matching.models import NO_MAPPING
from src.registry.api import CONFIG, create_app, node_from_config
from src.registry.federation import RegistryNode
from src.registry.gs1 import normalise_gtin
from src.registry.ids import AdidFormatError, parse_adid, to_uri
from src.registry.policy import PUBLIC, Principal, Role
from src.registry.registration import register_rows, rows_from_mapping
from src.registry.store import FACET_FIELDS, RegistryError
from src.registry.views import AccessDenied, NotFound, label, lot_members, neighbourhood, record_view, summary
from src.web.accounts import Account, AccountError, AccountStore
from src.web.library import TemplateLibrary, TemplateLibraryError
from src.web.safeguards import UPLOAD_TTL_SECONDS, AuditLog, LoginThrottle, max_upload_bytes, safe_next

__all__ = ["create_web_app", "build", "LOCKED_FIELDS"]

HERE = Path(__file__).parent
#: Fields that link uploads to an existing record (registration keys). Editing
#: them would silently detach the record from future uploads, so they are
#: read-only in the portal. A genuine mistake is fixed by withdrawing the record
#: and registering a replacement (D50).
LOCKED_FIELDS = {"gtin", "serialNumber", "batchNumber", "productFamily"}
KIND_NAMES = {"family": "Family", "variant": "Variant", "instance": "Instance"}
KIND_PLURAL = {"family": "Families", "variant": "Variants", "instance": "Instances"}
#: Two-host layout (optional). With ADIF_PUBLIC_HOST=adif.my and ADIF_APP_HOST=app.adif.my,
#: the public registry lives on the first and accounts (sign-in, sign-up, portal, operator)
#: on the second. Unset, everything is served from one host, as before.
ACCOUNT_PREFIXES = ("/login", "/signup", "/logout", "/portal", "/admin", "/welcome")
PUBLIC_PREFIXES = ("/registry", "/how-it-works", "/about", "/adid/", "/01/")


def _env_host(name: str) -> str:
    return os.environ.get(name, "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")


#: Category shortcuts on the registry page.
SIZE_ORDER = ("XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL")
BROWSE_CATEGORIES = ("T-shirt", "Polo shirt", "Hoodie", "Dress", "Trousers", "Shorts")

#: Display colours for colour names used in uploads (matched loosely, see colour_hex).
_COLOUR_HEX = {
    "oceanblue": "#1F6E9C", "coconutwhite": "#F3EFE4", "cinnamon": "#A8592A", "navy": "#24365F",
    "sand": "#D8C49C", "black": "#22242A", "white": "#FBFAF7", "offwhite": "#F1ECE0", "olive": "#6B7340",
    "skyblue": "#86B9E0", "lightblue": "#A9CBE8", "charcoal": "#45484F", "maroon": "#702433",
    "burgundy": "#6B1F33", "grey": "#9A9C9F", "gray": "#9A9C9F", "blue": "#2F64B0", "green": "#3F7A4F",
    "red": "#C23B3B", "teal": "#1F7D7A", "coral": "#E57A63", "beige": "#D9C7A7", "pink": "#E6A3B8",
    "yellow": "#E8C547", "brown": "#7A5133", "orange": "#E07B2E", "purple": "#6A4C93",
}


def colour_hex(name: Any) -> str:
    """A display colour for a colour name however it was spelt ("NAVY-BLUE", "Navy")."""
    from src.registry.store import normalise_facet

    key = normalise_facet(name or "")
    if key in _COLOUR_HEX:
        return _COLOUR_HEX[key]
    for word, hexv in sorted(_COLOUR_HEX.items(), key=lambda kv: -len(kv[0])):
        if word in key:
            return hexv
    return "#C9C6BF"


#: Design code of the worked example registered by ``scripts.seed_demo``.
SHOWCASE_FAMILY = "CB-TEE-01"


def qr_path(text: str) -> dict[str, Any]:
    """A real, scannable QR code as one SVG path (unit = one module)."""
    try:
        import segno
    except ImportError:  # optional: the label falls back to a plain frame
        return {"d": "", "size": 0}
    qr = segno.make(text, error="m")
    d = []
    for y, row in enumerate(qr.matrix):
        x = 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                d.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return {"d": "".join(d), "size": len(qr.matrix)}


@dataclass
class PortalUpload:
    """One file moving through upload → review → register, owned by a registrar."""

    token: str
    registrar: str
    session: Any
    template_used: str | None = None
    confirm_summary: dict[str, Any] | None = None
    saved_template: str | None = None
    registration: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


FREEZE_RECORD = Path("config/freeze_record_v1.0.yaml")


def frozen_artefacts(record: Path = FREEZE_RECORD) -> list[dict[str, Any]]:
    """Recompute the SHA-256 of each frozen research artefact against D30 (D53).

    The website is a demonstration layer; the evaluated version is the frozen
    one. Showing the comparison keeps that boundary visible and checkable.
    See :mod:`src.integrity` for the line-ending status.
    """
    from src.integrity import check_frozen

    return check_frozen(record)


def _secret_key(path: Path) -> str:
    import os
    if os.environ.get("ADIR_SECRET_KEY"):
        return os.environ["ADIR_SECRET_KEY"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def create_web_app(
    node: RegistryNode,
    accounts: AccountStore,
    library: TemplateLibrary,
    secret_key: str,
    engine_getter: Callable[[], Any] | None = None,
    audit: AuditLog | None = None,
    secure_cookies: bool = False,
    login_throttle: LoginThrottle | None = None,
) -> FastAPI:
    """Assemble the website over one registry node."""
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    uploads: dict[str, PortalUpload] = {}
    audit = audit or AuditLog(":memory:")
    throttle = login_throttle or LoginThrottle()
    upload_limit = max_upload_bytes()

    def client_of(request: Request) -> str:
        return request.client.host if request.client else ""

    public_host = _env_host("ADIF_PUBLIC_HOST")
    app_host = _env_host("ADIF_APP_HOST")
    split = bool(public_host and app_host)

    def host_of(request: Request) -> str:
        return (request.headers.get("host") or "").split(":")[0].lower()

    def on_app_host(request: Request) -> bool:
        return split and host_of(request) == app_host

    def app_url(path: str) -> str:
        """Address of an account page: on app.adif.my when the two-host layout is on."""
        return f"https://{app_host}{path}" if split else path

    def site_url(path: str) -> str:
        """Address of a public registry page: on adif.my when the two-host layout is on."""
        return f"https://{public_host}{path}" if split else path

    def purge_expired_uploads() -> None:
        cutoff = time.time() - UPLOAD_TTL_SECONDS
        for token in [t for t, u in uploads.items() if u.created_at < cutoff]:
            uploads.pop(token, None)

    def href(adid: str) -> str:
        """Canonical ADID v2 path for a record (falls back to /adid/{uuid})."""
        ent = node.store.get(adid)
        return ent.path if ent is not None and ent.path else f"/adid/{adid}"

    templates.env.filters["href"] = href
    templates.env.filters["colour_hex"] = colour_hex

    def engine():
        if engine_getter is not None:
            return engine_getter()
        from webapp.engine import get_engine
        return get_engine()

    # ---------------------------------------------------------- session helpers
    def current_account(request: Request) -> Account | None:
        username = request.session.get("user")
        if not username:
            return None
        account = accounts.get(username)
        if account is None or not account.active:
            request.session.pop("user", None)
            return None
        return account

    def session_principal(request: Request) -> Principal | None:
        account = current_account(request)
        return account.principal() if account else None

    def csrf(request: Request) -> str:
        token = request.session.get("csrf")
        if not token:
            token = secrets.token_urlsafe(24)
            request.session["csrf"] = token
        return token

    async def form_checked(request: Request) -> Any:
        form = await request.form()
        if not secrets.compare_digest(str(form.get("csrf", "")), request.session.get("csrf", "-")):
            raise HTTPException(400, "This form expired. Go back, reload the page and try again.")
        return form

    def flash(request: Request, message: str, kind: str = "ok") -> None:
        request.session.setdefault("flash", []).append({"text": message, "kind": kind})

    def render(request: Request, page: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
        account = current_account(request)
        context = {
            "user": account,
            "csrf": csrf(request),
            "flashes": request.session.pop("flash", []),
            "kind_names": KIND_NAMES,
            "kind_plural": KIND_PLURAL,
            "resolver": node.resolver,
            "path": request.url.path,
            "on_app": on_app_host(request),
            "app_url": app_url,
            "site_url": site_url,
            **ctx,
        }
        return templates.TemplateResponse(request, page, context, status_code=status_code)

    def error_page(request: Request, status: int, title: str, message: str) -> HTMLResponse:
        return render(request, "error.html", status_code=status, title=title, message=message)

    def require(request: Request, *roles: Role) -> Account | RedirectResponse:
        account = current_account(request)
        if account is None:
            return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
        if roles and account.role not in roles:
            raise HTTPException(403, "Your account does not have access to this page.")
        return account

    # -------------------------------------------------------------- product page
    def render_entity(request: Request, adid: str, principal: Principal) -> HTMLResponse:
        try:
            record = record_view(node, adid, principal)
            near = neighbourhood(node, adid, principal) if record["status"] != "withdrawn" else None
        except AccessDenied as exc:
            return error_page(request, 403, "This record is restricted", str(exc))
        except NotFound as exc:
            return error_page(request, 404, "Not found", str(exc))
        entity = node.store.get(adid)
        verify = node.store.verify(adid)
        can_see_history = principal.privileged or principal.owns(entity.registrar)
        history = node.store.history(adid) if can_see_history else []
        return render(
            request, "entity.html",
            record=record, entity=entity, near=near, verify=verify, label=label(entity),
            can_edit=principal.owns(entity.registrar) and entity.status != "withdrawn",
            history=history, status_code=410 if entity.status == "withdrawn" else 200,
        )

    app = create_app(node, html_renderer=render_entity, session_principal=session_principal)
    app.title = "ADIF — Apparel DPP Interoperability Framework (research prototype)"
    # A cookie domain such as ".adif.my" keeps people signed in on both adif.my and app.adif.my,
    # so an authority who signs in on the app still sees restricted sections on product pages.
    app.add_middleware(SessionMiddleware, secret_key=secret_key, session_cookie="adir_session",
                       max_age=8 * 3600, same_site="lax", https_only=secure_cookies,
                       domain=os.environ.get("ADIF_COOKIE_DOMAIN", "").strip() or None)

    @app.middleware("http")
    async def host_routing(request: Request, call_next):
        """Send account pages to the app host and registry pages to the public host."""
        if split:
            host, path = host_of(request), request.url.path
            query = ("?" + request.url.query) if request.url.query else ""
            if host in (public_host, "www." + public_host) and path.startswith(ACCOUNT_PREFIXES):
                return RedirectResponse(f"https://{app_host}{path}{query}", status_code=307)
            if host == "www." + public_host:
                return RedirectResponse(f"https://{public_host}{path}{query}", status_code=308)
            wants_html = "text/html" in (request.headers.get("accept") or "")
            if (host == app_host and request.method == "GET" and wants_html
                    and path.startswith(PUBLIC_PREFIXES)):
                return RedirectResponse(f"https://{public_host}{path}{query}", status_code=307)
        return await call_next(request)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.middleware("http")
    async def json_download(request: Request, call_next):
        """``?download=1`` on a passport or record saves it as a file instead of showing it."""
        response = await call_next(request)
        if request.query_params.get("download") == "1" and "json" in (response.headers.get("content-type") or ""):
            view = request.query_params.get("view", "record")
            stem = request.url.path.strip("/").replace("adid/", "", 1).replace("/", "_") or "record"
            name = f"passport_{stem}.jsonld" if view == "dpp" else f"record_{stem}.json"
            response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        wants_html = "text/html" in (request.headers.get("accept") or "") and not request.url.path.startswith(
            ("/search", "/registry/info", "/registrations", "/entities", "/relations"))
        if wants_html:
            titles = {400: "Something in that request was not right", 401: "Sign in needed",
                      403: "Not available to you", 404: "Not found", 410: "Withdrawn"}
            return error_page(request, exc.status_code, titles.get(exc.status_code, "Request refused"), str(exc.detail))
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    # ------------------------------------------------------------- public pages
    def example_ids() -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for kind in ("family", "variant"):
            ids = node.store.search({}, kinds=[kind], limit=1)
            out[kind] = ids[0] if ids else None
        return out

    def showcase(base_url: str) -> dict[str, Any] | None:
        """The worked example on the home page: one registered design and its variants."""
        fams = node.store.search({"productFamily": SHOWCASE_FAMILY}, kinds=["family"], limit=1)
        if not fams:
            return None
        fam = node.store.get(fams[0])
        variants, lots = [], {}
        for _, vid in node.store.related(fam.adid, "variantOf", "in"):
            v = node.store.get(vid)
            if v is None or v.status != "active":
                continue
            items = []
            for _, iid in node.store.related(vid, "instanceOf", "in"):
                inst = node.store.get(iid)
                if inst is not None and inst.status == "active":
                    items.append({"path": inst.path, "serial": inst.metadata.get("serialNumber", ""),
                                  "uuid": inst.adid, "qr": qr_path(base_url.rstrip("/") + inst.path)})
            batch = v.metadata.get("batchNumber")
            if isinstance(batch, list):
                batch = batch[0] if batch else None
            if batch:
                lots.setdefault(str(batch), []).append(v.path)
            variants.append({"path": v.path, "segment": v.path.rsplit("/", 1)[-1],
                             "colour": v.metadata.get("colour", ""), "size": v.metadata.get("size", ""),
                             "gtin": (v.alt_ids.get("gtin") or [""])[0], "batch": batch, "items": items,
                             "qr": qr_path(base_url.rstrip("/") + v.path)})
        if not variants:
            return None
        colours = list(dict.fromkeys(v["colour"] for v in variants))
        sizes = list(dict.fromkeys(v["size"] for v in variants))
        similar = 0
        try:
            first = variants[0]
            similar = len(node.store.search({"productCategory": fam.metadata.get("productCategory", ""),
                                             "colour": first["colour"]}, kinds=["variant"], limit=50))
        except RegistryError:
            pass
        live = base_url.rstrip("/") + fam.path
        return {"family": fam, "variants": variants, "colours": colours, "sizes": sizes,
                "lots": lots, "qr": qr_path(live), "live_url": live,
                "item_count": sum(len(v["items"]) for v in variants), "similar": similar}

    def public_base(request: Request) -> str:
        """The site's own address, for QR codes (https behind a hosting proxy)."""
        configured = os.environ.get("ADIF_PUBLIC_URL", "").strip()
        if configured:
            return configured.rstrip("/")
        base = str(request.base_url).rstrip("/")
        host = request.url.hostname or ""
        if base.startswith("http://") and host not in ("localhost", "127.0.0.1", "testserver"):
            base = "https://" + base[len("http://"):]
        return base

    def counts_now() -> dict[str, int]:
        counts = {k: node.store.count(k) for k in ("family", "variant", "instance")}
        counts["manufacturers"] = len(node.store.registrars_with_entities())
        return counts

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(request: Request, q: str = ""):
        if on_app_host(request):
            return welcome(request)
        return registry_page(request, q, landing=True)

    @app.get("/welcome", response_class=HTMLResponse, include_in_schema=False)
    def welcome(request: Request):
        """The account entrance: choose who you are, then sign in or ask to join."""
        account = current_account(request)
        if account is not None:
            return RedirectResponse("/portal", status_code=303)
        return render(request, "welcome.html", counts=counts_now())

    @app.get("/about", response_class=HTMLResponse, include_in_schema=False)
    def about(request: Request):
        return render(request, "home.html", counts=counts_now(), examples=example_ids(),
                      show=showcase(public_base(request)))

    @app.get("/how-it-works", response_class=HTMLResponse, include_in_schema=False)
    def how(request: Request):
        return render(request, "how.html", show=showcase(public_base(request)))

    @app.get("/registry", response_class=HTMLResponse, include_in_schema=False)
    def registry_page(request: Request, q: str = "", landing: bool = False):
        principal = session_principal(request) or PUBLIC
        q = q.strip()
        if q:
            target = None
            try:
                target = parse_adid(q)
            except AdidFormatError:
                gtin = normalise_gtin(q)
                if gtin:
                    target = node.root.gs1(gtin) or node.store.find("gtin", gtin)
                else:
                    target = node.store.find("alias", q.lower().strip("/").removeprefix("alias/"))
            if target:
                return RedirectResponse(href(target), status_code=303)
        searchable = [f for f in FACET_FIELDS if f != "gtin" and node.policy.is_public(f)]
        filters = {f: request.query_params[f] for f in searchable if request.query_params.get(f, "").strip()}
        manufacturer = request.query_params.get("manufacturer", "").strip() or None
        kind = request.query_params.get("kind", "family")
        kinds = [kind] if kind in ("family", "variant") else ["family"]
        hits = node.store.search(filters, kinds=kinds, registrar=manufacturer, limit=node.policy.max_page_size)
        results = []
        for a in hits:
            e = node.store.get(a)
            item = summary(node, e)
            with node.store._lock:
                meta = node.store._inherited_metadata(node.store._conn, a)
            if not meta.get("productCategory"):
                continue  # browse lists categorised products only; direct lookup still finds the rest
            colours, sizes = [], []
            if e.kind == "family":
                variant_ids = [v for _, v in node.store.related(a, "variantOf", "in")]
                for vid in variant_ids:
                    v = node.store.get(vid)
                    if v is not None and v.status == "active":
                        colours.append(str(v.metadata.get("colour", "")))
                        sizes.append(str(v.metadata.get("size", "")))
            else:
                variant_ids = []
                colours, sizes = [str(meta.get("colour", ""))], [str(meta.get("size", ""))]
            item.update({"design": meta.get("productFamily"), "category": meta.get("productCategory"),
                         "manufacturer": e.registrar, "maker": meta.get("manufacturerName") or e.registrar,
                         "fibre": meta.get("fibreComposition"), "origin": meta.get("countryOfOrigin"),
                         "colours": list({colour_hex(c): c for c in reversed(colours) if c}.values())[::-1],
                         "sizes": [z for z in SIZE_ORDER if z in {x.strip().upper() for x in sizes}]
                                  + sorted({x.strip().upper() for x in sizes if x} - set(SIZE_ORDER)),
                         "versions": len(variant_ids) if e.kind == "family" else None})
            results.append(item)
        category = filters.get("productCategory", "")
        return render(request, "registry.html", q=q, not_found=bool(q), filters=filters, kind=kind,
                      manufacturer=manufacturer or "", results=results, category=category,
                      categories=BROWSE_CATEGORIES, facet_fields=searchable,
                      landing=landing and not q and not filters and not manufacturer,
                      counts=counts_now(), show=showcase(public_base(request)) if landing else None)

    @app.get("/id/{adid}/v/{version}", response_class=HTMLResponse, include_in_schema=False)
    def old_version(request: Request, adid: str, version: int):
        principal = session_principal(request) or PUBLIC
        try:
            adid = parse_adid(adid)
        except AdidFormatError as exc:
            raise HTTPException(400, str(exc)) from exc
        entity = node.store.get(adid)
        if entity is None:
            raise HTTPException(404, "No such record.")
        if not (principal.privileged or principal.owns(entity.registrar)):
            raise HTTPException(403, "Earlier versions are visible to the owner and to authorities.")
        snap = node.store.snapshot_at(adid, version)
        if snap is None:
            raise HTTPException(404, f"Version {version} does not exist.")
        prev = node.store.snapshot_at(adid, version - 1) if version > 1 else None
        changed = {}
        if prev:
            keys = set(snap["metadata"]) | set(prev["metadata"])
            changed = {k: (prev["metadata"].get(k), snap["metadata"].get(k)) for k in sorted(keys)
                       if prev["metadata"].get(k) != snap["metadata"].get(k)}
        hist = {h["version"]: h for h in node.store.history(adid)}
        return render(request, "version.html", adid=adid, entity=entity, snap=snap, version=version,
                      changed=changed, entry=hist.get(version), latest=entity.version)

    # ------------------------------------------------------------------ accounts
    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request, next: str = "/portal", as_: str = Query("", alias="as")):
        role = as_ if as_ in ("manufacturer", "authority", "operator") else ""
        return render(request, "login.html", next=safe_next(next), as_role=role)

    @app.post("/login", include_in_schema=False)
    async def login(request: Request):
        form = await form_checked(request)
        nxt = safe_next(str(form.get("next") or "/portal"))
        username = str(form.get("username", "")).strip().lower()
        keys = (f"user:{username}", f"client:{client_of(request)}")
        wait = throttle.blocked(*keys)
        if wait:
            audit.log(username, "login", outcome="throttled", client=client_of(request))
            return render(request, "login.html", status_code=429, next=nxt, username=username,
                          error=f"Too many failed sign-ins. Try again in about {max(1, wait // 60)} minute(s).")
        try:
            account = accounts.authenticate(username, str(form.get("password", "")))
        except AccountError as exc:
            throttle.failed(*keys)
            audit.log(username, "login", outcome="failed", client=client_of(request))
            return render(request, "login.html", status_code=401, error=str(exc), next=nxt,
                          username=form.get("username", ""))
        throttle.succeeded(*keys)
        audit.log(account.username, "login", client=client_of(request))
        request.session.clear()
        request.session["user"] = account.username
        flash(request, f"Signed in as {account.display_name}.")
        return RedirectResponse(nxt, status_code=303)

    @app.post("/logout", include_in_schema=False)
    async def logout(request: Request):
        await form_checked(request)
        audit.log(str(request.session.get("user", "")), "logout", client=client_of(request))
        request.session.clear()
        return RedirectResponse(site_url("/") if split else "/", status_code=303)

    @app.get("/signup", response_class=HTMLResponse, include_in_schema=False)
    def signup_page(request: Request):
        return render(request, "signup.html")

    @app.post("/signup", include_in_schema=False)
    async def signup(request: Request):
        form = await form_checked(request)
        values = {k: str(form.get(k, "")) for k in ("username", "display_name", "organisation", "password")}
        if values["password"] != str(form.get("password2", "")):
            return render(request, "signup.html", status_code=400, error="The two passwords do not match.", values=values)
        try:
            account = accounts.create(values["username"], values["password"], values["display_name"],
                                      values["organisation"], Role.REGISTRANT, "pending")
        except AccountError as exc:
            return render(request, "signup.html", status_code=400, error=str(exc), values=values)
        return render(request, "signup_done.html", account=account)

    # -------------------------------------------------------------------- portal
    MANUFACTURER = (Role.REGISTRANT, Role.OPERATOR)

    @app.get("/portal", response_class=HTMLResponse, include_in_schema=False)
    def portal(request: Request):
        account = require(request)
        if isinstance(account, RedirectResponse):
            return account
        if account.role == Role.AUTHORITY:
            return render(request, "portal/authority.html")
        if account.role == Role.OPERATOR:
            return RedirectResponse("/admin", status_code=303)
        reg = account.registrar_id
        counts = {k: len(node.store.owned_by(reg, k, limit=100_000)) for k in ("family", "variant", "instance")}
        models = [node.store.get(a) for a in node.store.owned_by(reg, "family", limit=8)]
        return render(request, "portal/dashboard.html", counts=counts, models=models,
                      templates_list=library.latest_all(reg)[:6],
                      versions={m.adid: len(node.store.related(m.adid, "variantOf", "in")) for m in models})

    @app.get("/portal/upload", response_class=HTMLResponse, include_in_schema=False)
    def upload_page(request: Request):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        return render(request, "portal/upload.html", templates_list=library.latest_all(account.registrar_id))

    @app.post("/portal/upload", include_in_schema=False)
    async def upload(request: Request):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        form = await form_checked(request)
        file = form.get("file")
        if file is None or not getattr(file, "filename", ""):
            flash(request, "Choose a file to upload.", "error")
            return RedirectResponse("/portal/upload", status_code=303)
        data = await file.read(upload_limit + 1)
        if len(data) > upload_limit:
            flash(request, f"This file is larger than the {upload_limit // (1024 * 1024)} MB limit.", "error")
            audit.log(account.username, "upload", getattr(file, "filename", ""), "too_large", client_of(request))
            return RedirectResponse("/portal/upload", status_code=303)
        purge_expired_uploads()
        template = None
        chosen = str(form.get("template", "")).strip()
        if chosen:
            named = library.get(account.registrar_id, chosen)
            template = named.as_template() if named else None
        from webapp.engine import EngineError, run_mapping
        try:
            session = run_mapping(engine(), file.filename, data, account.registrar_id, template, chosen or None)
        except EngineError as exc:
            flash(request, str(exc), "error")
            return RedirectResponse("/portal/upload", status_code=303)
        session.company = account.registrar_id  # the signed-in registrar, never a typed name
        token = secrets.token_urlsafe(9)
        uploads[token] = PortalUpload(token, account.registrar_id, session, chosen or None)
        audit.log(account.username, "upload", file.filename, client=client_of(request))
        return RedirectResponse(f"/portal/review/{token}", status_code=303)

    def own_upload(request: Request, token: str) -> tuple[Account, PortalUpload] | RedirectResponse:
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        purge_expired_uploads()
        item = uploads.get(token)
        if item is None or item.registrar != account.registrar_id:
            raise HTTPException(404, "That upload has expired or belongs to another account. Upload the file again.")
        return account, item

    @app.get("/portal/review/{token}", response_class=HTMLResponse, include_in_schema=False)
    def review(request: Request, token: str):
        got = own_upload(request, token)
        if isinstance(got, RedirectResponse):
            return got
        account, item = got
        s = item.session
        eng = engine()
        rows = []
        for i, r in enumerate(s.result.records):
            samples = [str(v) for v in s.frame.iloc[:3, r.source_position].tolist()]
            rows.append({"i": i, "header": r.raw_header, "target": r.target_field, "stage": r.deciding_stage.value,
                         "confidence": r.confidence, "review": r.review_required, "conflict": r.conflict_flagged,
                         "samples": samples, "notes": r.notes})
        return render(request, "portal/review.html", item=item, rows=rows, fields=sorted(eng.field_names),
                      no_mapping=NO_MAPPING, semantic_on=eng.semantic_on,
                      reuse=s.reuse, row_count=s.analysis.row_count,
                      to_review=sum(1 for r in rows if r["review"]))

    @app.post("/portal/review/{token}", include_in_schema=False)
    async def confirm(request: Request, token: str):
        got = own_upload(request, token)
        if isinstance(got, RedirectResponse):
            return got
        account, item = got
        form = await form_checked(request)
        s = item.session
        decisions = {r.raw_header: str(form.get(f"map_{i}", r.target_field)) for i, r in enumerate(s.result.records)}
        from webapp.engine import EngineError, confirm_mappings
        try:
            item.confirm_summary = confirm_mappings(engine(), s, decisions)
        except EngineError as exc:
            flash(request, str(exc), "error")
            return RedirectResponse(f"/portal/review/{token}", status_code=303)
        name = str(form.get("template_name", "")).strip()
        if name:
            try:
                saved = library.save(account.registrar_id, name,
                                     {h: f for h, f in decisions.items() if f != NO_MAPPING},
                                     account.username, engine().registry.schema_sha256, s.filename,
                                     str(form.get("template_note", "")))
                item.saved_template = f"{saved.name} (version {saved.version})"
            except TemplateLibraryError as exc:
                flash(request, str(exc), "error")
        return RedirectResponse(f"/portal/review/{token}#register", status_code=303)

    @app.post("/portal/register/{token}", include_in_schema=False)
    async def register(request: Request, token: str):
        got = own_upload(request, token)
        if isinstance(got, RedirectResponse):
            return got
        account, item = got
        await form_checked(request)
        if not item.session.confirmed:
            flash(request, "Confirm the column matches before registering.", "error")
            return RedirectResponse(f"/portal/review/{token}", status_code=303)
        rows = rows_from_mapping(item.session.frame, item.session.result.records)
        report = register_rows(node, rows, account.registrar_id, engine().registry.schema, actor=account.username)
        item.registration = report.as_dict()
        audit.log(account.username, "register", f"{len(rows)} rows: {dict(report.created)}", client=client_of(request))
        return RedirectResponse(f"/portal/registered/{token}", status_code=303)

    @app.get("/portal/registered/{token}", response_class=HTMLResponse, include_in_schema=False)
    def registered(request: Request, token: str):
        got = own_upload(request, token)
        if isinstance(got, RedirectResponse):
            return got
        account, item = got
        if item.registration is None:
            return RedirectResponse(f"/portal/review/{token}", status_code=303)
        rows = []
        for i, ids in enumerate(item.registration["row_adids"]):
            target = ids.get("instance") or ids.get("variant") or ids.get("family")
            e = node.store.get(target)
            rows.append({"row": i + 1, "ids": ids, "target": target, "uri": node.uri(target),
                         "label": label(e) if e else "", "kind": e.kind if e else ""})
        return render(request, "portal/registered.html", item=item, rep=item.registration, rows=rows)

    @app.get("/portal/lot", response_class=HTMLResponse, include_in_schema=False)
    def lot_page(request: Request, batch: str = ""):
        """Recall view: everything recorded under one batch number (owner or authority)."""
        account = require(request)
        if isinstance(account, RedirectResponse):
            return account
        principal = account.principal()
        results = None
        if batch.strip():
            registrar = None if principal.privileged else account.registrar_id
            try:
                results = lot_members(node, batch.strip(), principal, registrar)
            except AccessDenied as exc:
                raise HTTPException(403, str(exc)) from exc
        return render(request, "portal/lot.html", batch=batch.strip(), lot=results)

    @app.get("/portal/products", response_class=HTMLResponse, include_in_schema=False)
    def products(request: Request, q: str = ""):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        reg = account.registrar_id
        models = []
        for a in node.store.owned_by(reg, "family", limit=500):
            m = node.store.get(a)
            name = str(m.metadata.get("productFamily", ""))
            if q and q.lower() not in name.lower():
                continue
            variants = [node.store.get(v) for _, v in node.store.related(a, "variantOf", "in")]
            models.append({"family": m, "variants": [v for v in variants if v]})
        return render(request, "portal/products.html", models=models, q=q)

    @app.get("/portal/edit/{adid}", response_class=HTMLResponse, include_in_schema=False)
    def edit_page(request: Request, adid: str):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        entity = owned_entity(account, adid)
        cdm = engine().registry
        allowed = [f for f in cdm.names() if granularity_of(cdm, f) == level_of(entity.kind)]
        fields_ = sorted(set(entity.metadata) | set(allowed))
        return render(request, "portal/edit.html", entity=entity, fields=fields_, locked=LOCKED_FIELDS,
                      policy=node.policy, label=label(entity))

    def owned_entity(account: Account, adid: str):
        try:
            adid = parse_adid(adid)
        except AdidFormatError as exc:
            raise HTTPException(400, str(exc)) from exc
        entity = node.store.get(adid)
        if entity is None:
            raise HTTPException(404, "No such record on this registry.")
        if not account.principal().owns(entity.registrar):
            raise HTTPException(403, "Only the manufacturer that registered this product can change it.")
        return entity

    def level_of(kind: str) -> str:
        return {"family": "family", "variant": "variant", "instance": "instance"}[kind]

    def granularity_of(cdm, name: str) -> str:
        spec = cdm.schema.get("properties", {}).get(name, {})
        return (spec.get("x-adif") or {}).get("granularity", "variant")

    @app.post("/portal/edit/{adid}", include_in_schema=False)
    async def edit(request: Request, adid: str):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        entity = owned_entity(account, adid)
        form = await form_checked(request)
        if entity.status == "withdrawn":
            raise HTTPException(409, "A withdrawn record cannot be edited.")
        changes = {}
        for key, value in form.multi_items():
            if not key.startswith("f_"):
                continue
            name = key[2:]
            if name in LOCKED_FIELDS:
                continue  # never editable, whatever the form says
            new = str(value).strip()
            if new != str(entity.metadata.get(name, "")):
                changes[name] = new or None
        if not changes:
            flash(request, "Nothing changed, so no new version was saved.")
            return RedirectResponse(href(entity.adid), status_code=303)
        version = node.store.update(entity.adid, changes, account.username)
        flash(request, f"Saved as revision {version}. The ADID did not change, and revision {version - 1} is kept in the history.")
        return RedirectResponse(href(entity.adid), status_code=303)

    @app.post("/portal/status/{adid}", include_in_schema=False)
    async def status(request: Request, adid: str):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        entity = owned_entity(account, adid)
        form = await form_checked(request)
        action = str(form.get("action", ""))
        replaced = str(form.get("replaced_by", "")).strip() or None
        if action not in ("deprecated", "withdrawn", "active"):
            raise HTTPException(400, "Unknown action.")
        try:
            if replaced:
                replaced = (node.store.find_path("/adid/" + replaced.split("/adid/", 1)[1].strip("/"))
                            if replaced.count("/") >= 3 and "/adid/" in replaced else parse_adid(replaced))
                if not replaced or not node.store.exists(replaced):
                    raise HTTPException(400, "The replacement ID is not registered here.")
            node.store.set_status(entity.adid, action, account.username, replaced)
        except (RegistryError, AdidFormatError) as exc:
            raise HTTPException(400, str(exc)) from exc
        words = {"deprecated": "Marked as replaced", "withdrawn": "Withdrawn", "active": "Reactivated"}
        flash(request, f"{words[action]}. The ADID still resolves and is not reassigned.")
        return RedirectResponse(href(entity.adid), status_code=303)

    @app.get("/portal/templates", response_class=HTMLResponse, include_in_schema=False)
    def templates_page(request: Request):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        return render(request, "portal/templates.html", templates_list=library.latest_all(account.registrar_id))

    @app.get("/portal/templates/{name}", response_class=HTMLResponse, include_in_schema=False)
    def template_detail(request: Request, name: str):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        versions = library.versions(account.registrar_id, name)
        if not versions:
            raise HTTPException(404, "No template with that name.")
        return render(request, "portal/template.html", name=name, versions=versions)

    @app.post("/portal/templates/{name}/restore/{version}", include_in_schema=False)
    async def template_restore(request: Request, name: str, version: int):
        account = require(request, *MANUFACTURER)
        if isinstance(account, RedirectResponse):
            return account
        await form_checked(request)
        try:
            new = library.restore(account.registrar_id, name, version, account.username)
        except TemplateLibraryError as exc:
            raise HTTPException(404, str(exc)) from exc
        flash(request, f"Version {version} copied forward as version {new.version}. Nothing was overwritten.")
        return RedirectResponse(f"/portal/templates/{quote(name)}", status_code=303)

    # --------------------------------------------------------------- operator
    @app.get("/portal/admin", include_in_schema=False)
    def admin_old(request: Request):
        return RedirectResponse("/admin", status_code=308)

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin(request: Request):
        account = require(request, Role.OPERATOR)
        if isinstance(account, RedirectResponse):
            return account
        counts = {k: node.store.count(k) for k in ("family", "variant", "instance")}
        try:
            matching = engine().fingerprint
        except Exception as exc:  # the admin page must load even if the engine cannot
            matching = {"error": str(exc)}
        return render(request, "portal/admin.html", pending=accounts.pending(), all_accounts=accounts.all(),
                      counts=counts, nodes=node.root.nodes(), frozen=frozen_artefacts(), matching=matching,
                      audit_events=audit.recent(50))

    @app.post("/admin/accounts/{username}/{action}", include_in_schema=False)
    async def admin_account(request: Request, username: str, action: str):
        account = require(request, Role.OPERATOR)
        if isinstance(account, RedirectResponse):
            return account
        await form_checked(request)
        status_for = {"approve": "active", "reject": "rejected", "suspend": "suspended", "reactivate": "active"}
        if action not in status_for:
            raise HTTPException(400, "Unknown action.")
        target = accounts.get(username)
        if target is None:
            raise HTTPException(404, "No such account.")
        if target.username == account.username:
            raise HTTPException(400, "You cannot change your own account here.")
        accounts.set_status(username, status_for[action], account.username)
        audit.log(account.username, f"account_{action}", username, client=client_of(request))
        flash(request, f"{target.organisation}: {status_for[action]}.")
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/authority", include_in_schema=False)
    async def admin_authority(request: Request):
        account = require(request, Role.OPERATOR)
        if isinstance(account, RedirectResponse):
            return account
        form = await form_checked(request)
        try:
            created = accounts.create(str(form.get("username", "")), str(form.get("password", "")),
                                      str(form.get("display_name", "")), str(form.get("organisation", "")),
                                      Role.AUTHORITY, "active")
            accounts.set_status(created.username, "active", account.username)
            audit.log(account.username, "authority_created", created.username, client=client_of(request))
            flash(request, f"Authority account created for {created.organisation}.")
        except AccountError as exc:
            flash(request, str(exc), "error")
        return RedirectResponse("/admin", status_code=303)

    app.state.uploads = uploads
    app.state.accounts = accounts
    app.state.library = library
    app.state.audit = audit
    return app


def build() -> FastAPI:
    """App factory: ``uvicorn src.web.app:build --factory``."""
    raw = yaml.safe_load(Path(CONFIG).read_text(encoding="utf-8"))
    web = raw.get("web", {})
    node = node_from_config(CONFIG)
    secure = bool(web.get("secure_cookies", False)) or os.environ.get("ADIR_SECURE_COOKIES") == "1"
    if os.environ.get("ADIF_AUTOSEED", "1") != "0" and node.store.count() == 0:
        # A fresh online database: register the demonstration catalogue in the
        # background, so the site answers at once and fills within a minute.
        import threading

        def _seed() -> None:
            try:
                from scripts.seed_demo import main as seed_main
                # Never the published default password on a reachable server.
                seed_main(["--password", os.environ.get("ADIF_DEMO_PASSWORD") or secrets.token_urlsafe(18)])
            except Exception as exc:  # never take the site down over demo data
                print(f"[adif] demo seeding failed: {exc!r}", flush=True)

        threading.Thread(target=_seed, name="adif-seed", daemon=True).start()
    return create_web_app(
        node,
        AccountStore(web.get("accounts_db", "var/adir_web.sqlite")),
        TemplateLibrary(web.get("templates_db", "var/adir_web.sqlite")),
        _secret_key(Path(web.get("secret_key_file", "var/secret_key"))),
        audit=AuditLog(web.get("audit_db", web.get("accounts_db", "var/adir_web.sqlite"))),
        secure_cookies=secure,
    )
