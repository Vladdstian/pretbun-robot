"""Receipt prices accepted by the app (D1 table receipt_prices, written by the Worker) → the robot's database.

Each store gets a place in the "store" channel; its receipt prices are change-only rows with source "receipt",
so they reach the daily file (build_daily's "receipt_prices") and the history. Plan Task 10, robot side.

python3 -m robot.receipts since  --db pretbun.sqlite                   prints the last imported moment (Unix seconds)
python3 -m robot.receipts import --db pretbun.sqlite --json rows.json  rows from `wrangler d1 execute --json`
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from . import channels as ch
from . import db

KEY = "receipts_at"
# shortcut: an admin "undo" after the robot imported a receipt price does not remove it here; the next receipt or
# the official data replaces it. Upgrade: import the reverted receipts' ids and write the previous price back.


def since(conn) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (KEY,)).fetchone()
    return int(row[0]) if row else 0


def rows_from_wrangler(text: str) -> list:
    try:
        out = json.loads(text)
    except ValueError:
        return []
    return [r for block in out if isinstance(block, dict) and block.get("success") for r in block.get("results", [])]


def import_rows(conn, rows: list) -> int:
    stores = {sid: (chain, name) for sid, chain, name in conn.execute("SELECT id, chain_id, name FROM stores")}
    by_place_day, last, written = defaultdict(dict), since(conn), 0
    for r in sorted(rows, key=lambda r: r["at"]):
        last = max(last, int(r["at"]))
        if r["store_id"] not in stores:
            continue
        chain, name = stores[r["store_id"]]
        place = ch.place_id(conn, "store", "%s (%d)" % (name, r["store_id"]), chain_id=chain, store_id=r["store_id"])
        by_place_day[(place, int(r["day"]))][int(r["product_id"])] = (int(r["price"]), 0, None, None)
    for (place, day), new in sorted(by_place_day.items(), key=lambda kv: kv[0][1]):
        written += ch.apply_place(conn, place, day, new, "receipt")
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (KEY, str(last)))
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Receipt prices from the app into the robot's database")
    ap.add_argument("command", choices=["since", "import"])
    ap.add_argument("--db", required=True)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    conn = db.connect(a.db)
    if a.command == "since":
        print(since(conn))
        return 0
    with open(a.json, encoding="utf-8") as f:
        n = import_rows(conn, rows_from_wrangler(f.read()))
    conn.commit()
    print("receipt prices written:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
