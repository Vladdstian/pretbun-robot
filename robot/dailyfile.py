"""The small daily file the app downloads: stores near an area, current prices per zone, store exceptions."""
from __future__ import annotations

import gzip
import json
import math
import os

from .channels import MAX_AGE_DAYS
from .db import day_to_date
from .history import NOT_SOLD_HERE


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _latest_on(conn, table: str, key: str, ids: list, day: int):
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    sql = ("SELECT t.{k}, t.product_id, t.price, t.promo FROM {t} t JOIN "
           "(SELECT {k}, product_id, MAX(day) AS d FROM {t} WHERE day <= ? AND {k} IN ({m}) GROUP BY {k}, product_id) x "
           "ON t.{k} = x.{k} AND t.product_id = x.product_id AND t.day = x.d").format(t=table, k=key, m=marks)
    return conn.execute(sql, [day] + ids).fetchall()


def _products(conn, used) -> list:
    # [id, plain name, brand, size, unit, item, attributes, Nutri-Score, diet]: the catalog's fields (step 2)
    return [[pid, title or name, brand, sq, su, item, json.loads(a) if a else None, grade, diet.split(",") if diet else None]
                for pid, name, title, brand, sq, su, item, a, grade, diet in conn.execute(
        "SELECT p.id, p.name, p.title, b.name, p.size_qty, p.size_unit, p.item_id, i.attrs, f.grade, f.diet FROM products p "
        "LEFT JOIN brands b ON b.id = p.brand_id LEFT JOIN product_info i ON i.product_id = p.id "
        "LEFT JOIN facts f ON f.product_id = p.id WHERE p.id IN (%s) ORDER BY p.id"
        % ",".join(str(int(i)) for i in sorted(used)))] if used else []




def build_daily(conn, area: dict, day: int) -> dict:
    radius_km = area.get("radius_m", 5000) / 1000.0
    stores = []
    for sid, chain_id, zone_id, name, address, lat, lon, typ in conn.execute(
            "SELECT id, chain_id, zone_id, name, address, lat, lon, type FROM stores WHERE active = 1 ORDER BY id"):
        dist = distance_km(area["lat"], area["lon"], lat, lon)
        if dist <= radius_km:
            stores.append([sid, chain_id, zone_id, name, address, lat, lon, typ, round(dist, 2)])
    zone_ids = sorted({s[2] for s in stores})
    prices, used = {}, set()
    for zone_id, pid, price, promo in sorted(_latest_on(conn, "zone_prices", "zone_id", zone_ids, day)):
        if price is not None:
            prices.setdefault(str(zone_id), []).append([pid, price, promo])
            used.add(pid)
    exceptions = []
    for sid, pid, price, promo in sorted(_latest_on(conn, "store_prices", "store_id", [s[0] for s in stores], day)):
        if price is not None:  # NULL = back to the zone price
            exceptions.append([sid, pid, None if price == NOT_SOLD_HERE else price, promo])
            used.add(pid)
    row = conn.execute("SELECT id FROM areas WHERE name = ?", (area["name"],)).fetchone()
    apps = [list(r) for r in conn.execute("SELECT id, name, app, chain_id FROM places WHERE channel = 'app' "
                                          "AND area_id = ? ORDER BY id", (row[0],))] if row else []
    app_prices, app_used = _place_prices(conn, [a[0] for a in apps], day)  # delivery apps in this area (step 2b)
    used |= app_used
    # in-store prices from people's receipts (robot/receipts.py): [store, product, price, day], newest per store and product
    shelf = {pid: sid for pid, sid in conn.execute("SELECT id, store_id FROM places WHERE channel = 'store' AND store_id IS NOT NULL")
             if sid in {s[0] for s in stores}}
    rec_prices, rec_used = _place_prices(conn, sorted(shelf), day)
    used |= rec_used
    receipt_prices = sorted([shelf[int(place)], pid, price, seen] for place, rows in rec_prices.items() for pid, price, _, _, _, seen in rows)
    products = _products(conn, used)
    chain_ids = sorted({s[1] for s in stores})
    return {
        "day": day, "date": day_to_date(day).isoformat(), "area": area["name"],
        "chains": {str(i): n for i, n in conn.execute(
            "SELECT id, name FROM chains WHERE id IN (%s)" % ",".join(map(str, chain_ids)))} if chain_ids else {},
        "zones": {str(i): n for i, n in conn.execute(
            "SELECT id, name FROM zones WHERE id IN (%s)" % ",".join(map(str, zone_ids)))} if zone_ids else {},
        "stores": stores, "products": products, "prices": prices, "exceptions": exceptions,
        "apps": apps, "app_prices": app_prices, "receipt_prices": receipt_prices,
    }


def _place_prices(conn, place_ids: list, day: int):
    """The latest price per (place, product) on or before `day`, if seen within MAX_AGE_DAYS.
    Returns ({place: [[product, price, promo, regular, low30, seen_day]]}, product ids used)."""
    prices, used = {}, set()
    if place_ids:
        ids = ",".join(str(int(p)) for p in place_ids)
        for place, pid, price, promo, regular, low30, seen in sorted(conn.execute(
                "SELECT t.place_id, t.product_id, t.price, t.promo, t.regular, t.low30, t.day FROM place_prices t JOIN "
                "(SELECT place_id, product_id, MAX(day) AS d FROM place_prices WHERE day <= ? AND place_id IN (%s) "
                "GROUP BY place_id, product_id) m ON t.place_id = m.place_id AND t.product_id = m.product_id "
                "AND t.day = m.d" % ids, (day,))):
            if day - seen <= MAX_AGE_DAYS:
                prices.setdefault(str(place), []).append([pid, price, promo, regular, low30, seen])
                used.add(pid)
    return prices, used


def build_national(conn, day: int) -> dict:
    """Online shops' prices (national, not per area): the latest price per product, if seen in the last 8 weeks."""
    places = [list(r) for r in conn.execute("SELECT id, channel, name, url FROM places WHERE channel = 'online' ORDER BY id")]
    prices, used = _place_prices(conn, [p[0] for p in places], day)
    return {"day": day, "date": day_to_date(day).isoformat(), "places": places, "prices": prices,
            "products": _products(conn, used)}


def write_daily(path: str, data: dict) -> int:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    blob = gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    with open(path, "wb") as f:
        f.write(blob)
    return len(blob)
