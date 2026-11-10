"""Products the cleaning rules can't fix (asked 2026-11-10: "put them on a special list, don't show them on the site").

for_review(conn) -> {product id: reason}; the daily files leave them out and daily/admin/review.json lists them for review.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from math import log

from robot.history import current_zone_prices
from robot.names import normalize
from robot.sizes import portion_size

CHEAP = 10  # under a tenth of its kind's middle price per kg: a portion priced as the box (0,77 lei for 1 kg of butter).
# Too expensive by the same factor goes to review too, since kinds are checked against the official category.


def _medians(conn) -> dict:
    by = defaultdict(list)
    for (_, pid), (price, _) in current_zone_prices(conn).items():
        if price is not None:
            by[pid].append(price)
    return {pid: sorted(v)[len(v) // 2] for pid, v in by.items()}


def for_review(conn, rules: dict = None) -> dict:
    """rules: robot/settings.py (factor, hide_no_size, show = product ids the admin chose to show anyway)."""
    rules = rules or {}
    cheap, show = rules.get("factor", CHEAP), set(rules.get("show", ()))
    price = _medians(conn)
    rows = {pid: (sq, su, item, attrs) for pid, sq, su, item, attrs in conn.execute(
        "SELECT p.id, p.size_qty, p.size_unit, p.item_id, i.attrs FROM products p LEFT JOIN product_info i ON i.product_id = p.id")}
    out, kinds = {}, defaultdict(list)
    for pid, bani in price.items():
        sq, su, item, attrs = rows.get(pid, (None, None, None, None))
        if not sq:
            if rules.get("hide_no_size", True):
                out[pid] = "fără mărime: nu se poate compara la kg sau litru"
        elif item is not None:
            kinds[(item, attrs, su)].append((bani * 1000 / sq if su in ("g", "ml") else bani / sq, pid))
    names = dict(conn.execute("SELECT id, name FROM products"))
    for group in kinds.values():
        if len(group) < 3:
            continue
        mid = sorted(v for v, _ in group)[len(group) // 2]
        for v, pid in group:
            if v * cheap < mid:
                out[pid] = "preț ciudat: %.2f lei pe unitate față de %.2f obișnuit" % (v / 100, mid / 100)
                continue
            if v > mid * cheap:  # possible now that kinds are checked against the official category (2026-11-10)
                out[pid] = "preț ciudat, prea scump: %.2f lei pe unitate față de %.2f obișnuit" % (v / 100, mid / 100)
                continue
            # a multipack whose price looks like one piece's ("4x0.33nrt" at 6,19 lei): the pack and the single piece are
            # different products, so it is neither resized nor shown (2026-11-10 "don't mix")
            sq, su = rows[pid][0], rows[pid][1]
            part = portion_size(normalize(names.get(pid) or ""))
            if part and part[1] == su and part[0] < sq and v * 2 < mid:
                one = v * sq / part[0]
                if abs(log(one / mid)) < abs(log(v / mid)):
                    out[pid] = "preț de verificat: pare prețul unei bucăți, nu al pachetului"
    day = conn.execute("SELECT MAX(day) FROM zone_prices").fetchone()[0]
    if day is not None:
        for pid, why in _jumps(conn, day).items():
            out.setdefault(pid, why)
    return {pid: why for pid, why in out.items() if pid not in show}


def _jumps(conn, day: int, factor: float = 5.0) -> dict:
    """{product id: reason} for products whose newest price is over `factor` times, or under 1/`factor` of,
    their oldest price in the 30 days before `day` (any zone)."""
    first, last = {}, {}  # pid -> (day, price)
    for pid, d, price in conn.execute(
            "SELECT product_id, day, price FROM zone_prices WHERE day BETWEEN ? AND ? AND price IS NOT NULL", (day - 30, day)):
        if pid not in first or d < first[pid][0]:
            first[pid] = (d, price)
        if pid not in last or d > last[pid][0]:
            last[pid] = (d, price)
    out = {}
    for pid, (d0, oldest) in first.items():
        d1, newest = last[pid]
        if d0 != d1 and (newest > factor * oldest or newest * factor < oldest):
            out[pid] = "preț sărit: %.2f lei față de %.2f acum o lună" % (newest / 100, oldest / 100)
    return out


def score(conn) -> dict:
    """How good the product data is (README D4): of the products priced in the last 3 days, how many have a kind, a size, a brand."""
    row = conn.execute("""SELECT COUNT(*), COUNT(item_id), COUNT(size_qty), COUNT(brand_id) FROM products WHERE id IN
        (SELECT DISTINCT product_id FROM zone_prices WHERE day >= (SELECT MAX(day) FROM zone_prices) - 3 AND price IS NOT NULL)""").fetchone()
    return dict(zip(("priced", "with_kind", "with_size", "with_brand"), row))


def write(conn, review: dict, out_dir: str) -> str:
    names = dict(conn.execute("SELECT id, COALESCE(title, name) FROM products"))
    path = os.path.join(out_dir, "admin", "review.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(([pid, names.get(pid, ""), why] for pid, why in review.items()), key=lambda r: r[2]), f, ensure_ascii=False)
    with open(os.path.join(out_dir, "admin", "quality.json"), "w", encoding="utf-8") as f:
        json.dump({"day": conn.execute("SELECT MAX(day) FROM zone_prices").fetchone()[0], **score(conn), "review": len(review)}, f)
    return path
