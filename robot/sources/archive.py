"""Online prices from the Wayback Machine's copies of a shop's pages (Dr. Max, Farmacia Tei…).

Dr. Max's own site turns robots away, so we never ask it. The public archive keeps copies of its category pages, and
each copy carries the listed products' current price, regular price and lowest price in the last 30 days. A price's
day is the day the copy was made, so the app can say "văzut pe 14.10".
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import date

from .. import channels, db

CDX = "https://web.archive.org/cdx/search/cdx"


def _bani(x):
    return None if x is None else int(round(x * 100))


def _pointer(conn, key: str, value: str = None):
    if value is None:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def run(conn, web, today: int, host: str, parse, place: tuple, source: str, pointer_key: str,
        cap: int = channels.DAILY_CAP) -> dict:
    """Read the copies of `host` made since the last run (first run: the last 8 weeks), oldest first.
    parse(html) -> [(ext_key, name, brand, price, regular, low30)]; place = (name, url)."""
    pointer = _pointer(conn, pointer_key)
    start = pointer or db.day_to_date(today - channels.MAX_AGE_DAYS).strftime("%Y%m%d000000")
    q = urllib.parse.urlencode([("url", host + "/*"), ("from", start), ("filter", "statuscode:200"),
                                ("filter", "mimetype:text/html"), ("collapse", "urlkey"),
                                ("fl", "timestamp,original"), ("limit", "500")])
    lines = [line.split() for line in web.get(CDX + "?" + q).splitlines() if line.strip()]
    rows = sorted((x[0], x[1]) for x in lines if len(x) >= 2 and re.fullmatch(r"\d{14}", x[0]) and x[1].startswith("http"))
    if lines and not rows:  # an error page instead of the index: never take its lines for copies
        return {"pages": 0, "products": 0, "written": 0, "ok": False,
                "note": "the archive's index answered something unexpected (an error page?); nothing read, next run retries"}
    rows = [r for r in rows if pointer is None or r[0] > pointer]  # 'from' is inclusive: the last copy comes back
    place_id = channels.place_id(conn, "online", place[0], url=place[1])
    pages = found = written = unreadable = 0
    left = cap
    for ts, url in rows:
        try:
            html = web.get("https://web.archive.org/web/%sid_/%s" % (ts, url))
        except Exception:  # one copy the archive can't serve must not stop the others
            unreadable += 1
            _pointer(conn, pointer_key, ts)
            continue
        pages += 1
        new = {}
        for ext, name, brand, price, regular, low30 in parse(html):
            found += 1
            pid = channels.product_for(conn, source, ext, name, brand)
            price, regular = _bani(price), _bani(regular)
            new[pid] = (price, 1 if regular and price < regular else 0, regular, _bani(low30))
        day = db.day_number(date(int(ts[:4]), int(ts[4:6]), int(ts[6:8])))
        n = channels.apply_place(conn, place_id, day, new, "archive", cap=left)
        written, left = written + n, left - n
        if left <= 0:
            break  # the daily cap: this page may be unfinished, so the pointer stays before it
        _pointer(conn, pointer_key, ts)
        conn.commit()
    conn.commit()
    if pages and not found:
        return {"pages": pages, "products": 0, "written": written, "ok": False,
                "note": "0 products from %d pages: has %s changed its page format?" % (pages, place[0])}
    note = "%d pages, %d products, %d changes" % (pages, found, written)
    if left <= 0:
        note += "; daily cap reached, the rest next run"
    if unreadable:
        note += "; %d copies could not be read" % unreadable
    return {"pages": pages, "products": found, "written": written, "ok": not (rows and not pages), "note": note}
