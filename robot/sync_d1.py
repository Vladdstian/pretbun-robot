"""Send the robot's changes to Cloudflare D1, at most `budget` statements per UTC day across all runs
(free plan: 100,000 rows written a day, reset at 00:00 UTC; the app needs the rest).

python3 -m robot.sync_d1 export --db pretbun.sqlite --out today.sql   prints the last statement number it wrote
python3 -m robot.sync_d1 done --db pretbun.sqlite --upto N             only after wrangler sent today.sql
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import db


def _d1_schema() -> str:
    with open(db.SCHEMA, encoding="utf-8") as f:
        return f.read().split("-- robot-only")[0]  # the outbox stays local


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def sent_today(conn, today: str) -> int:
    """Statements already sent on this UTC day, by any run (Cloudflare's own counter lags by hours)."""
    m = dict(conn.execute("SELECT key, value FROM meta WHERE key IN ('d1_day', 'd1_sent')").fetchall())
    return int(m.get("d1_sent", 0)) if m.get("d1_day") == today else 0


def export_outbox(conn, path: str, budget: int = 70000, today: str = None):
    """Schema + the waiting statements, oldest first, up to what is left of today's budget.
    Returns (count, last seq); (0, 0) when none wait or the day's budget is used up."""
    left = max(0, budget - sent_today(conn, today or _utc_today()))
    rows = conn.execute("SELECT seq, sql FROM outbox ORDER BY seq LIMIT ?", (left,)).fetchall()
    with open(path, "w", encoding="utf-8") as f:
        f.write(_d1_schema())
        for _, sql in rows:
            # D1 may get a statement twice (sent, then the run stopped before the 'sent' mark was saved): make that harmless
            if sql.startswith("INSERT INTO "):
                sql = "INSERT OR REPLACE INTO " + sql[len("INSERT INTO "):]
            f.write(sql + ";\n")
    return len(rows), (rows[-1][0] if rows else 0)


def mark_sent(conn, upto_seq: int, today: str = None) -> None:
    """After wrangler sent the file: drop those statements and add them to today's count."""
    today = today or _utc_today()
    n = conn.execute("SELECT COUNT(*) FROM outbox WHERE seq <= ?", (upto_seq,)).fetchone()[0]
    total = sent_today(conn, today) + n
    conn.execute("DELETE FROM outbox WHERE seq <= ?", (upto_seq,))
    conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", [("d1_day", today), ("d1_sent", str(total))])
    conn.commit()


def budget_from_info(path: str, cap: int = 70000, ceiling: int = 90000, unknown: int = 30000) -> int:
    """How many changes to send now: never more than `cap`, and never past `ceiling` counting what D1 says it already wrote
    in the last 24 h (people's sign-ups, lists and receipts included). Unreadable info → a safe `unknown`."""
    try:
        with open(path, encoding="utf-8") as f:
            written = int(json.load(f)["rows_written_24h"])
    except (OSError, ValueError, KeyError, TypeError):
        return unknown
    return max(0, min(cap, ceiling - written))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send the robot's changes to D1")
    ap.add_argument("command", choices=["export", "done"])
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="today.sql")
    ap.add_argument("--upto", type=int, help="for done: the number export printed")
    ap.add_argument("--d1-info", help="for export: `wrangler d1 info --json` output; sends only what fits under D1's daily limit")
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    if args.command == "export":
        n, last = export_outbox(conn, args.out, budget=budget_from_info(args.d1_info) if args.d1_info else 70000)
        left = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] - n
        print("%d changes for D1 (%d already sent today, UTC), %d wait for the next days"
              % (n, sent_today(conn, _utc_today()), left), file=sys.stderr)
        print(last)
    elif args.upto is None:
        ap.error("done needs --upto")
    else:
        mark_sent(conn, args.upto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
