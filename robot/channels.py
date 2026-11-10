"""Price channels (spec docs/superpowers/specs/2026-11-09-price-channels-design.md): places, their change-only
prices, and product identity across sources.

Official in-store prices stay in zone_prices / store_prices. Everything else (online shops, delivery apps, receipts,
reports, archives) lives here, always with its channel, source and day.
"""
from __future__ import annotations

from . import db

CHANNELS = ("store", "online", "app")
SOURCES = ("receipt", "report", "site", "archive", "app")
NEW_ID_START = 1_000_000_000  # official product ids have 7 digits
DAILY_CAP = 10_000            # changes per source per day, so D1's daily budget keeps room for the official data
MAX_AGE_DAYS = 56             # the app hides online, app and archive prices older than 8 weeks
PLACE_FIELDS = ("chain_id", "store_id", "app", "area_id", "url")


def forget_app(conn, app: str) -> int:
    """Delete an app's places and every price collected from it (Wolt, 2026-11-10: its terms forbid bots). Returns places removed."""
    ids = [r[0] for r in conn.execute("SELECT id FROM places WHERE app = ?", (app,))]
    for pid in ids:
        conn.execute("DELETE FROM place_prices WHERE place_id = ?", (pid,))
        conn.execute("DELETE FROM places WHERE id = ?", (pid,))
    conn.commit()
    return len(ids)


def place_id(conn, channel: str, name: str, **fields) -> int:
    """Get or create the place `(channel, name)`."""
    if channel not in CHANNELS:
        raise ValueError("unknown channel %r" % channel)
    if set(fields) - set(PLACE_FIELDS):
        raise ValueError("unknown place fields %s" % sorted(set(fields) - set(PLACE_FIELDS)))
    row = conn.execute("SELECT id FROM places WHERE channel = ? AND name = ?", (channel, name)).fetchone()
    if row:
        return row[0]
    pid = db.new_id(conn, "places")
    db.write(conn, "places", dict({"id": pid, "channel": channel, "name": name}, **fields))
    return pid


def current_place_prices(conn, place: int) -> dict:
    """product_id -> (price, promo, regular, low30) as of the latest row."""
    sql = ("SELECT t.product_id, t.price, t.promo, t.regular, t.low30 FROM place_prices t JOIN "
           "(SELECT product_id, MAX(day) AS d FROM place_prices WHERE place_id = ? GROUP BY product_id) m "
           "ON t.product_id = m.product_id AND t.day = m.d WHERE t.place_id = ?")
    return {p: (price, promo, regular, low30) for p, price, promo, regular, low30 in conn.execute(sql, (place, place))}


def apply_place(conn, place: int, day: int, new: dict, source: str, cap: int = DAILY_CAP) -> int:
    """Write what changed (price, promo, regular or low30) as of `day`, at most `cap` rows. Returns rows written.
    new: product_id -> (price, promo, regular, low30), prices in bani."""
    if source not in SOURCES:
        raise ValueError("unknown source %r" % source)
    cur, n = current_place_prices(conn, place), 0
    for product_id, values in sorted(new.items()):
        if n >= cap:
            break
        if cur.get(product_id) == tuple(values):
            continue
        price, promo, regular, low30 = values
        db.write(conn, "place_prices", {"place_id": place, "product_id": product_id, "day": day, "price": price,
                                        "promo": promo, "regular": regular, "low30": low30, "source": source},
                 replace=True)
        n += 1
    return n


def product_for(conn, source: str, ext_key: str, name: str, brand: str = None, barcode: str = None) -> int:
    """Our product for a shop's product: the known link, else the same barcode, else a new product (ids from 1e9).
    The shop's own key (ext_key) is the identity, never the name: one name can cover several pack sizes."""
    row = conn.execute("SELECT product_id FROM product_sources WHERE source = ? AND ext_key = ?",
                       (source, ext_key)).fetchone()
    if row:
        return row[0]
    pid = None
    if barcode:
        row = conn.execute("SELECT id FROM products WHERE barcode = ?", (barcode,)).fetchone()
        pid = row[0] if row else None
    if pid is None:
        last = conn.execute("SELECT MAX(id) FROM products WHERE id >= ?", (NEW_ID_START,)).fetchone()[0]
        pid = NEW_ID_START if last is None else last + 1
        db.write(conn, "products", {"id": pid, "name": name, "brand_id": db.brand_id(conn, brand) if brand else None,
                                    "barcode": barcode})
    db.write(conn, "product_sources", {"source": source, "ext_key": ext_key, "product_id": pid})
    return pid


def area_id(conn, area: dict) -> int:
    """Get or create the areas row for an areas.json entry (city centres, not anyone's home)."""
    row = conn.execute("SELECT id FROM areas WHERE name = ?", (area["name"],)).fetchone()
    if row:
        return row[0]
    aid = db.new_id(conn, "areas")
    db.write(conn, "areas", {"id": aid, "name": area["name"], "lat": area["lat"], "lon": area["lon"],
                             "radius_m": area.get("radius_m", 5000)})
    return aid
