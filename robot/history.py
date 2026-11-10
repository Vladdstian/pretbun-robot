"""Price history: a row only on the day something changes. Reading back: latest row on or before a day.

zone_prices.price NULL = not sold in the zone.
store_prices.price NULL = back to the zone price; 0 = not sold in this store (no real price is 0 bani).
"""
from __future__ import annotations

from . import db

NOT_SOLD_HERE = 0


def _latest(conn, table: str, key: str) -> dict:
    sql = ("SELECT t.{k}, t.product_id, t.price, t.promo FROM {t} t JOIN "
           "(SELECT {k}, product_id, MAX(day) AS d FROM {t} GROUP BY {k}, product_id) m "
           "ON t.{k} = m.{k} AND t.product_id = m.product_id AND t.day = m.d").format(t=table, k=key)
    return {(a, p): (price, promo) for a, p, price, promo in conn.execute(sql)}


def current_zone_prices(conn) -> dict:
    return _latest(conn, "zone_prices", "zone_id")


def current_store_prices(conn) -> dict:
    """Exceptions in effect now: (store, product) -> (price or None for 'not sold here', promo)."""
    out = {}
    for key, (price, promo) in _latest(conn, "store_prices", "store_id").items():
        if price is not None:
            out[key] = (None if price == NOT_SOLD_HERE else price, promo)
    return out


def apply_zone(conn, day: int, new: dict) -> int:
    cur, n = current_zone_prices(conn), 0
    for (zone_id, product_id), (price, promo) in new.items():
        old = cur.get((zone_id, product_id))
        if old == (price, promo) or (old is None and price is None):
            continue
        db.write(conn, "zone_prices", {"zone_id": zone_id, "product_id": product_id, "day": day,
                                       "price": price, "promo": promo}, replace=True)
        n += 1
    return n


def apply_store(conn, day: int, checked: set, new: dict) -> int:
    cur, n = current_store_prices(conn), 0
    for key in set(checked) | set(new):
        want, have = new.get(key), cur.get(key)
        if want == have:
            continue
        if want is None:
            price, promo = None, 0  # back to the zone price
        else:
            price, promo = (NOT_SOLD_HERE if want[0] is None else want[0]), want[1]
        db.write(conn, "store_prices", {"store_id": key[0], "product_id": key[1], "day": day,
                                        "price": price, "promo": promo}, replace=True)
        n += 1
    return n


def price_on(conn, store_id: int, product_id: int, day: int):
    row = conn.execute("SELECT price FROM store_prices WHERE store_id = ? AND product_id = ? AND day <= ? "
                       "ORDER BY day DESC LIMIT 1", (store_id, product_id, day)).fetchone()
    if row and row[0] is not None:
        return None if row[0] == NOT_SOLD_HERE else row[0]
    zone = conn.execute("SELECT zone_id FROM stores WHERE id = ?", (store_id,)).fetchone()
    if not zone:
        return None
    row = conn.execute("SELECT price FROM zone_prices WHERE zone_id = ? AND product_id = ? AND day <= ? "
                       "ORDER BY day DESC LIMIT 1", (zone[0], product_id, day)).fetchone()
    return row[0] if row else None


def weighted_average(conn, zone_id: int, product_id: int, start: int, end: int):
    """Average over [start, end): each price counts for the days it lasted; days not sold are left out."""
    rows = conn.execute("SELECT day, price FROM zone_prices WHERE zone_id = ? AND product_id = ? AND day < ? "
                        "ORDER BY day", (zone_id, product_id, end)).fetchall()
    total = days = 0
    for i, (d, price) in enumerate(rows):
        a, b = max(d, start), min(rows[i + 1][0] if i + 1 < len(rows) else end, end)
        if price is not None and b > a:
            total += price * (b - a)
            days += b - a
    return total / days if days else None
