"""Fill a local ADID registry with demonstration accounts and products.

    python -m scripts.seed_demo                 # uses the default demo password
    python -m scripts.seed_demo --password "something-longer"

Creates (skipping anything that already exists):

* operator      operator@adir.example     approves manufacturers
* manufacturer  demo@demoknit.example     Demo Knit Works — registers demo/demo_knitwear_export_spring.csv
                                          and saves template "Knitwear export" (v1), then re-applies it to the
                                          autumn file and saves v2, to show versioning
* manufacturer  demo@kandy.example        Kandy Garments — a small synthetic catalogue, so "similar products"
                                          has something from another manufacturer to find
* authority     officer@customs.example   sees restricted sections and batch contents
* pending       new@galle.example         Galle Apparel — waiting for approval, to show the operator queue

**Demo only.** Every demo account shares one password, printed at the end.
Never use these accounts on a server other people can reach.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from src.registry.api import CONFIG, node_from_config
from src.registry.policy import Role
from src.registry.registration import register_rows, rows_from_mapping
from src.web.accounts import AccountError, AccountStore
from src.web.library import TemplateLibrary

SPRING = Path("demo/demo_knitwear_export_spring.csv")
AUTUMN = Path("demo/demo_knitwear_export_autumn.csv")


def main(argv: list[str] | None = None) -> int:
    """Seed demo data; safe to run twice."""
    parser = argparse.ArgumentParser(prog="python -m scripts.seed_demo")
    parser.add_argument("--password", default="adir-demo-2026", help="password for every demo account")
    args = parser.parse_args(argv)

    web = (yaml.safe_load(Path(CONFIG).read_text(encoding="utf-8")) or {}).get("web", {})
    node = node_from_config(CONFIG)
    accounts = AccountStore(web.get("accounts_db", "var/adir_web.sqlite"))
    library = TemplateLibrary(web.get("templates_db", "var/adir_web.sqlite"))

    people = [
        ("operator@adir.example", "Registry operator", "Registry operator (demo)", Role.OPERATOR, "active", "adir-operator"),
        ("demo@demoknit.example", "Nimali Perera", "Demo Knit Works", Role.REGISTRANT, "active", "demoknit"),
        ("demo@kandy.example", "Ruwan Silva", "Kandy Garments", Role.REGISTRANT, "active", "kandy-garments"),
        ("officer@customs.example", "Customs officer", "Sri Lanka Customs (demo)", Role.AUTHORITY, "active", "customs-demo"),
        ("new@galle.example", "Amaya Fernando", "Galle Apparel", Role.REGISTRANT, "pending", "galle-apparel"),
    ]
    for username, name, org, role, status, registrar in people:
        try:
            accounts.create(username, args.password, name, org, role, status, registrar)
            if status == "active":
                accounts.set_status(username, "active", "seed")
            print(f"  account  {username:28} {role.value:10} {status}")
        except AccountError:
            print(f"  account  {username:28} already exists")

    from webapp.engine import confirm_mappings, get_engine, run_mapping
    engine = get_engine()
    schema = engine.registry.schema

    if SPRING.is_file():
        session = run_mapping(engine, SPRING.name, SPRING.read_bytes(), "demoknit")
        decisions = {r.raw_header: r.target_field for r in session.result.records}
        confirm_mappings(engine, session, decisions)
        if library.get("demoknit", "Knitwear export") is None:
            library.save("demoknit", "Knitwear export",
                         {h: f for h, f in decisions.items() if f != "NO_MAPPING"},
                         "demo@demoknit.example", engine.registry.schema_sha256, SPRING.name, "Spring season")
        rep = register_rows(node, rows_from_mapping(session.frame, session.result.records), "demoknit", schema,
                            actor="demo@demoknit.example")
        print(f"  demoknit spring: created {dict(rep.created)}, unchanged {dict(rep.unchanged)}")
    if AUTUMN.is_file() and len(library.versions("demoknit", "Knitwear export")) < 2:
        template = library.get("demoknit", "Knitwear export").as_template()
        session = run_mapping(engine, AUTUMN.name, AUTUMN.read_bytes(), "demoknit", template, "Knitwear export")
        decisions = {r.raw_header: r.target_field for r in session.result.records}
        library.save("demoknit", "Knitwear export", {h: f for h, f in decisions.items() if f != "NO_MAPPING"},
                     "demo@demoknit.example", engine.registry.schema_sha256, AUTUMN.name,
                     "Autumn season: renamed columns re-matched")
        print("  demoknit template 'Knitwear export' now has 2 revisions")

    from eval.registry_eval import generate
    rows, _ = generate(11, ["kandy-garments"], models=6, serials=1)
    rep = register_rows(node, rows["kandy-garments"], "kandy-garments", schema, actor="demo@kandy.example")
    print(f"  kandy-garments: created {dict(rep.created)}, unchanged {dict(rep.unchanged)}")

    print("\nDemo password for every account above:", args.password)
    print("Start the site:  uvicorn src.web.app:build --factory --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
