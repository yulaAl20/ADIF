"""Registry administration from the command line.

    python -m src.registry.admin add-registrar demoknit "Demo Knit Works"
    python -m src.registry.admin add-registrar customs-lk "Sri Lanka Customs" --role authority
    python -m src.registry.admin info
    python -m src.registry.admin verify-all

API keys are printed once and stored only as SHA-256 hashes.
"""

from __future__ import annotations

import argparse
import json

from src.registry.api import node_from_config
from src.registry.policy import Role


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m src.registry.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add-registrar", help="create an account and print its API key")
    add.add_argument("registrar_id")
    add.add_argument("name")
    add.add_argument("--role", default="registrant", choices=[r.value for r in Role if r != Role.PUBLIC])
    sub.add_parser("info", help="node, root and entity counts")
    sub.add_parser("verify-all", help="verify every entity's hash chain")
    args = parser.parse_args(argv)

    node = node_from_config()
    if args.cmd == "add-registrar":
        key = node.store.add_registrar(args.registrar_id, args.name, args.role)
        print(f"Registrar '{args.registrar_id}' ({args.role}) created.")
        print(f"API key (shown once — store it safely): {key}")
    elif args.cmd == "info":
        print(json.dumps({
            "node": node.node_id, "resolver": node.resolver, "nodes": node.root.nodes(),
            "entities": {k: node.store.count(k) for k in ("model", "variant", "batch", "instance")},
            "root_placements": node.root.placement_count(),
        }, indent=2))
    elif args.cmd == "verify-all":
        bad = [r for r in (node.store.verify(a) for a in node.store.all_adids()) if not r.ok]
        print(f"{node.store.count()} entities checked, {len(bad)} failed.")
        for r in bad[:20]:
            print(f"  {r.adid}: {'; '.join(r.problems)}")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
