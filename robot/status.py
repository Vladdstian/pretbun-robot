"""The admin page's numbers (app spec §9): freshness per source and the database's size, as daily/admin/status.json.

python3 -m robot.status --db pretbun.sqlite --out daily
"""
from __future__ import annotations

import argparse
import json
import os
import re

from robot.sync_d1 import _utc_today, sent_today

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
LATE_AFTER = {"official": 2, "app": 2, "online": 14, "labels": 40}  # days without news before the admin page shows red


def d1_tables() -> list:
    text = open(SCHEMA, encoding="utf-8").read().split("-- robot-only")[0]
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text)


def status(conn, today: int) -> dict:
    sources = []

    def add(name, kind, last_change, last_check, changed):
        seen = max(x for x in (last_change, last_check, -10**6) if x is not None)
        sources.append({"source": name, "kind": kind, "last_change": last_change, "last_check": last_check,
                        "changed": changed, "late": today - seen > LATE_AFTER[kind]})

    for name, last, checked in conn.execute(
            "SELECT c.name, (SELECT MAX(day) FROM zone_prices p JOIN zones z ON z.id = p.zone_id WHERE z.chain_id = c.id),"
            " (SELECT MAX(day) FROM zone_checks k JOIN zones z ON z.id = k.zone_id WHERE z.chain_id = c.id)"
            " FROM chains c ORDER BY c.name"):
        n = conn.execute("SELECT COUNT(*) FROM zone_prices p JOIN zones z ON z.id = p.zone_id JOIN chains c ON c.id = z.chain_id"
                         " WHERE c.name = ? AND p.day = ?", (name, last)).fetchone()[0]
        add(name, "official", last, checked, n)
    for name, kind, last in conn.execute(
            "SELECT COALESCE(pl.app, pl.name), pl.channel, MAX(pp.day) FROM place_prices pp JOIN places pl ON pl.id = pp.place_id"
            " WHERE pp.source IN ('site', 'archive', 'app') GROUP BY 1, 2 ORDER BY 1"):
        n = conn.execute("SELECT COUNT(*) FROM place_prices pp JOIN places pl ON pl.id = pp.place_id"
                         " WHERE COALESCE(pl.app, pl.name) = ? AND pp.day = ?", (name, last)).fetchone()[0]
        add(name, "app" if kind == "app" else "online", last, None, n)
    last, n = conn.execute("SELECT MAX(day), COUNT(*) FROM facts").fetchone()
    add("Open Food Facts", "labels", last, None, n)

    rows = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in d1_tables()}
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    return {"day": today, "sources": sources,
            "database": {"rows": rows, "bytes": page * conn.execute("PRAGMA page_count").fetchone()[0],
                         "d1_sent_today": sent_today(conn, _utc_today())}}


def main(argv=None) -> int:
    import sqlite3
    from robot.run import ro_today
    ap = argparse.ArgumentParser(description="The admin page's status file")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    path = os.path.join(a.out, "admin", "status.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(status(sqlite3.connect(a.db), ro_today()), f, ensure_ascii=False, indent=1)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
