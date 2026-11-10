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
    return {pid: why for pid, why in out.items() if pid not in show}


def write(conn, review: dict, out_dir: str) -> str:
    names = dict(conn.execute("SELECT id, COALESCE(title, name) FROM products"))
    path = os.path.join(out_dir, "admin", "review.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(([pid, names.get(pid, ""), why] for pid, why in review.items()), key=lambda r: r[2]), f, ensure_ascii=False)
    return path
