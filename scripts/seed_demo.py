"""Fill a local ADID registry with demonstration accounts and products.

    python -m scripts.seed_demo                 # uses the default demo password
    python -m scripts.seed_demo --password "something-longer"

Creates (skipping anything that already exists), all sharing one password:

* operator      operator@adir.example           approves manufacturers
* manufacturer  nimali@ceylonknit.example       Ceylon Knit Works: polo shirt, hoodie, dress; template "Knitwear export" (2 revisions)
* manufacturer  dilini@lankathreads.example     Lanka Threads: the Ceylon Breeze Crew Tee shown on the home page
* manufacturer  ruwan@kandygarments.example     Kandy Garments: a synthetic catalogue, so "similar products" has matches
* authority     officer@authority.example       sees restricted sections and batch contents
* pending       amaya@galleapparel.example      Galle Apparel: waiting for approval, to show the operator queue

On a server other people can reach, always pass a password of your own (or set ADIF_DEMO_PASSWORD).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

from src.registry.api import CONFIG, node_from_config
from src.registry.policy import Role
from src.registry.registration import register_rows, rows_from_mapping
from src.web.accounts import AccountError, AccountStore
from src.web.library import TemplateLibrary

SPRING = Path("demo/demo_knitwear_export_spring.csv")
AUTUMN = Path("demo/demo_knitwear_export_autumn.csv")
#: The worked example shown on the home page: one T-shirt design, three
#: colours x three sizes = nine variants, and three serialised items.
SHOWCASE = Path("demo/showcase_ceylon_breeze_tee.csv")
#: Ceylon Knit Works' catalogue: a polo shirt, a hoodie and a dress, all categorised.
CATALOGUE = Path("demo/catalogue_ceylon_knit.csv")


def main(argv: list[str] | None = None) -> int:
    """Seed demo data; safe to run twice."""
    parser = argparse.ArgumentParser(prog="python -m scripts.seed_demo")
    parser.add_argument("--password", default=os.environ.get("ADIF_DEMO_PASSWORD") or "adir-demo-2026",
                        help="password for every demo account (env ADIF_DEMO_PASSWORD on a hosted site)")
    args = parser.parse_args(argv)

    web = (yaml.safe_load(Path(CONFIG).read_text(encoding="utf-8")) or {}).get("web", {})
    node = node_from_config(CONFIG)
    accounts = AccountStore(web.get("accounts_db", "var/adir_web.sqlite"))
    library = TemplateLibrary(web.get("templates_db", "var/adir_web.sqlite"))

    people = [
        ("operator@adir.example", "Registry operator", "ADIF registry operator", Role.OPERATOR, "active", "adir-operator"),
        ("nimali@ceylonknit.example", "Nimali Perera", "Ceylon Knit Works (Pvt) Ltd", Role.REGISTRANT, "active", "ceylonknit"),
        ("ruwan@kandygarments.example", "Ruwan Silva", "Kandy Garments (Pvt) Ltd", Role.REGISTRANT, "active", "kandy-garments"),
        ("dilini@lankathreads.example", "Dilini Jayasuriya", "Lanka Threads (Pvt) Ltd", Role.REGISTRANT, "active", "lankathreads"),
        ("officer@authority.example", "Inspection officer", "Market surveillance office", Role.AUTHORITY, "active", "authority-1"),
        ("amaya@galleapparel.example", "Amaya Fernando", "Galle Apparel (Pvt) Ltd", Role.REGISTRANT, "pending", "galle-apparel"),
    ]
    for username, name, org, role, status, registrar in people:
        try:
            accounts.create(username, args.password, name, org, role, status, registrar)
            if status == "active":
                accounts.set_status(username, "active", "seed")
            print(f"  account  {username:30} {role.value:10} {status}")
        except AccountError:
            print(f"  account  {username:30} already exists")

    from webapp.engine import confirm_mappings, get_engine, run_mapping
    engine = get_engine()
    schema = engine.registry.schema

    def register_file(path: Path, registrar: str, actor: str) -> None:
        session = run_mapping(engine, path.name, path.read_bytes(), registrar)
        decisions = {r.raw_header: r.target_field for r in session.result.records}
        confirm_mappings(engine, session, decisions)
        rep = register_rows(node, rows_from_mapping(session.frame, session.result.records), registrar, schema,
                            actor=actor)
        print(f"  {registrar}: created {dict(rep.created)}, unchanged {dict(rep.unchanged)}")

    # A saved column-matching template with two revisions, to show versioning.
    ck = "nimali@ceylonknit.example"
    if SPRING.is_file() and library.get("ceylonknit", "Knitwear export") is None:
        session = run_mapping(engine, SPRING.name, SPRING.read_bytes(), "ceylonknit")
        decisions = {r.raw_header: r.target_field for r in session.result.records}
        library.save("ceylonknit", "Knitwear export", {h: f for h, f in decisions.items() if f != "NO_MAPPING"},
                     ck, engine.registry.schema_sha256, "knitwear_export_spring.csv", "Spring season")
    if AUTUMN.is_file() and len(library.versions("ceylonknit", "Knitwear export")) == 1:
        template = library.get("ceylonknit", "Knitwear export").as_template()
        session = run_mapping(engine, AUTUMN.name, AUTUMN.read_bytes(), "ceylonknit", template, "Knitwear export")
        decisions = {r.raw_header: r.target_field for r in session.result.records}
        library.save("ceylonknit", "Knitwear export", {h: f for h, f in decisions.items() if f != "NO_MAPPING"},
                     ck, engine.registry.schema_sha256, "knitwear_export_autumn.csv",
                     "Autumn season: renamed columns re-matched")
        print("  ceylonknit template 'Knitwear export' now has 2 revisions")

    if CATALOGUE.is_file():
        register_file(CATALOGUE, "ceylonknit", ck)
    if SHOWCASE.is_file():
        register_file(SHOWCASE, "lankathreads", "dilini@lankathreads.example")

    from eval.registry_eval import generate
    rows, _ = generate(11, ["kandy-garments"], models=6, serials=1)
    kandy = [dict(r, manufacturerName="Kandy Garments (Pvt) Ltd") for r in rows["kandy-garments"]]
    rep = register_rows(node, kandy, "kandy-garments", schema, actor="ruwan@kandygarments.example")
    print(f"  kandy-garments: created {dict(rep.created)}, unchanged {dict(rep.unchanged)}")

    print("\nPassword for every account above:", args.password)
    print("Start the site:  uvicorn src.web.app:build --factory --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
