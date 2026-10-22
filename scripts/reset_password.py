"""List accounts, or set a password, on the local or the hosted database.

    python -m scripts.reset_password --list
    python -m scripts.reset_password --demo --password "my-new-demo-pass"
    python -m scripts.reset_password --user nimali@ceylonknit.example --password "my-new-demo-pass"
    python -m scripts.reset_password --user amaya@galleapparel.example --status pending

Without DATABASE_URL this changes the local SQLite file under var/. To change the
hosted site (www.adif.my / app.adif.my), first set DATABASE_URL to the same Neon
connection string that Render uses, in the same terminal:

    Windows (cmd):         set DATABASE_URL=postgresql://...
    Windows (PowerShell):  $env:DATABASE_URL="postgresql://..."
    Linux / macOS:         export DATABASE_URL=postgresql://...

The site reads accounts on every sign-in, so no redeploy is needed afterwards.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from src.registry.api import CONFIG
from src.web.accounts import AccountError, AccountStore

#: The accounts created by scripts.seed_demo (and by the hosted site's first start).
DEMO_USERS = (
    "operator@adir.example",
    "nimali@ceylonknit.example",
    "ruwan@kandygarments.example",
    "dilini@lankathreads.example",
    "officer@authority.example",
    "amaya@galleapparel.example",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.reset_password")
    parser.add_argument("--list", action="store_true", help="show every account and its status")
    parser.add_argument("--user", action="append", default=[], help="account to change (repeatable)")
    parser.add_argument("--demo", action="store_true", help="change every demo account")
    parser.add_argument("--password", help="new password (at least 10 characters)")
    parser.add_argument("--status", choices=("active", "pending", "suspended", "rejected"),
                        help="also set the account status (e.g. put the Galle Apparel demo back to pending)")
    args = parser.parse_args(argv)

    web = (yaml.safe_load(Path(CONFIG).read_text(encoding="utf-8")) or {}).get("web", {})
    accounts = AccountStore(web.get("accounts_db", "var/adir_web.sqlite"))

    if args.list or not (args.user or args.demo):
        for a in accounts.all():
            print(f"  {a.username:34} {a.role.value:11} {a.status:10} {a.organisation}")
        return 0

    users = list(args.user) + (list(DEMO_USERS) if args.demo else [])
    if not args.password and not args.status:
        parser.error("give --password and/or --status")
    failed = 0
    for username in users:
        try:
            if args.password:
                accounts.set_password(username, args.password)
            if args.status:
                accounts.set_status(username, args.status, "reset_password")
            print(f"  updated  {username}")
        except AccountError as exc:
            failed += 1
            print(f"  skipped  {username}: {exc}")
    return 1 if failed and failed == len(users) else 0


if __name__ == "__main__":
    raise SystemExit(main())
