"""Command line helpers: python -m app.cli {setup-link|sync|check}"""
import argparse
import json
import os
import sys

from . import auth, db, sync


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup-link", help="print the one-time owner setup path (empty if an owner exists)")
    s = sub.add_parser("sync", help="run a sync now in the foreground")
    s.add_argument("--full", action="store_true", help="re-download every chat")
    sub.add_parser("check", help="verify the install: database, templates, static files, API key")
    a = ap.parse_args(argv)
    db.init()
    con = db.connect()
    if a.cmd == "setup-link":
        if not auth.has_owner(con):
            print("/setup?token=" + auth.setup_token())
        return 0
    if a.cmd == "sync":
        res = sync.run_sync("cli", full=a.full)
        print(json.dumps(res, indent=2))
        return 1 if res.get("status") == "error" else 0
    if a.cmd == "check":
        from pathlib import Path
        here = Path(__file__).resolve().parent
        need = ["templates/base.html", "templates/summary.html", "templates/project.html", "templates/dive.html",
                "templates/login.html", "templates/setup.html", "static/style.css", "static/app.js"]
        missing = [p for p in need if not (here / p).is_file()]
        ok = True
        for p in missing:
            print("MISSING  " + p); ok = False
        con.execute("SELECT COUNT(*) FROM settings").fetchone()
        print("ok       database " + str(db.DB_PATH))
        if os.environ.get("ABACUS_API_KEY"):
            print("ok       ABACUS_API_KEY is set")
        else:
            print("WARNING  ABACUS_API_KEY is not set: the site runs, but syncing will fail until it is")
        try:
            import abacusai  # noqa: F401
            print("ok       abacusai SDK importable")
        except ImportError:
            print("MISSING  abacusai SDK"); ok = False
        return 0 if ok and not missing else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
