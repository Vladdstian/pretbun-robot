"""Online price sources, run weekly: each source on its own (one failure doesn't stop the others), then the
national file of online prices.

python3 -m robot.sources --db pretbun.sqlite --out daily --areas areas.json --apps catalog/apps.tsv [--only glovo]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .. import db
from ..dailyfile import build_national, write_daily
from ..run import ro_today
from . import drmax_archive, freshful, glovo, tei_archive
from .web import Polite



def sources_for(areas: list, apps: list) -> dict:
    """Every source as fn(conn, web, today); Glovo also needs the areas and the storefronts list."""
    return {"drmax": drmax_archive.run, "tei": tei_archive.run, "freshful": freshful.run,
            "glovo": lambda conn, web, today: glovo.run(conn, web, today, areas, apps)}


def main(argv=None, sources: dict = None, web=None) -> int:
    ap = argparse.ArgumentParser(description="PrețBun online price sources")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="", help="comma-separated source names")
    ap.add_argument("--areas", default="areas.json")
    ap.add_argument("--apps", default=os.path.join("catalog", "apps.tsv"))
    a = ap.parse_args(argv)
    if sources is None:
        with open(a.areas, encoding="utf-8") as f:
            sources = sources_for(json.load(f), glovo.read_apps(a.apps))
    conn, today = db.connect(a.db), ro_today()
    web = web or Polite()
    only = {x for x in a.only.split(",") if x}
    chosen = {k: v for k, v in sources.items() if not only or k in only}
    import time
    minutes = float(os.environ.get("ROBOT_DEADLINE_MIN", "240") or 240)  # a slow source (Glovo) must not eat the day
    deadline = time.monotonic() + minutes * 60
    summary, failed = {}, 0
    for name, fn in chosen.items():
        if time.monotonic() > deadline:
            summary[name] = {"ok": False, "note": "timp epuizat (%.0f min)" % minutes}
            failed += 1
            continue
        try:
            r = fn(conn, web, today)
        except Exception as e:  # report it and go on with the next source
            conn.rollback()  # nothing half-written stays behind (no products without prices)
            r = {"ok": False, "note": "%s: %s" % (type(e).__name__, e)}
        conn.commit()
        summary[name] = r
        failed += not r.get("ok")
    summary["national_file_bytes"] = write_daily(os.path.join(a.out, "national", "latest.json.gz"),
                                                 build_national(conn, today))
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
