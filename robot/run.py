"""The daily robot: stores, catalog and prices -> change-only history -> one small daily file per area.

python3 -m robot.run --db data/pretbun.sqlite --areas areas.json --out data/daily [--weekly]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from . import db
from .channels import forget_app
from .review import for_review, write as write_review
from .dailyfile import build_daily, distance_km, write_daily
from .history import apply_store, apply_zone, current_store_prices, current_zone_prices
from .monitorul import Client, parse_catalog, parse_categories, parse_stores_with_prices
from .sizes import parse_size
from .zones import chain_of_store, network, pick_rep, split, zone_key

TRACK_CAP = 1000
ROTATION_DAYS = 7
REP_RADIUS_M = 100


@dataclass
class Report:
    day: int = 0
    chains_ok: list = field(default_factory=list)
    chains_failed: list = field(default_factory=list)
    capped: list = field(default_factory=list)
    zone_rows: int = 0
    store_rows: int = 0
    files: dict = field(default_factory=dict)
    odd: int = 0  # prices a shop gave under another product's official number (dropped)


def exit_code(report: Report) -> int:
    return 1 if report.chains_failed else 0


class OfflineClient:
    """Answers from saved responses, for tests and dry runs. mapping: chain key -> fixture file with its stores."""

    def __init__(self, fixtures_dir: str, mapping: dict, fail=()):
        self.dir, self.mapping, self.fail = fixtures_dir, mapping, set(fail)

    def _read(self, name: str) -> bytes:
        with open(os.path.join(self.dir, name), "rb") as f:
            return f.read()

    def networks(self) -> dict:
        return {k: k for k in self.mapping}

    def categories(self) -> list:
        return parse_categories(self._read("categories.xml"))

    def catalog(self, category_id: int) -> list:
        return parse_catalog(self._read("catalog_lapte.xml")) if category_id == 137 else []

    def chain_catalog(self, chain_key, categories=None):
        return parse_catalog(self._read("catalog_lapte.xml")) if not categories or 137 in categories else []

    def stores_prices(self, lat, lon, radius_m, product_ids, chain_key):
        if chain_key in self.fail:
            raise ValueError("offline failure for %s" % chain_key)
        stores, obs = parse_stores_with_prices(self._read(self.mapping[chain_key]))
        return stores, obs, len(stores) >= 50


def ro_today() -> int:
    # shortcut: Romania is UTC+2 (UTC+3 in summer); at the 03:30 UTC run time both give the same date.
    return db.day_number((datetime.now(timezone.utc) + timedelta(hours=2)).date())


def read_staples(path: str) -> list:
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            text = line.split("#", 1)[0].strip()
            if text:
                ids.append(int(text))
    return ids


_new_id = db.new_id


def _chain_id(conn, key: str, name: str) -> int:
    row = conn.execute("SELECT id FROM chains WHERE source_key = ?", (key,)).fetchone()
    if row:
        return row[0]
    cid = _new_id(conn, "chains")
    db.write(conn, "chains", {"id": cid, "name": name, "source_key": key})
    return cid


def _zone_id(conn, zkey: str, chain_id: int) -> int:
    row = conn.execute("SELECT id FROM zones WHERE name = ?", (zkey,)).fetchone()
    if row:
        return row[0]
    zid = _new_id(conn, "zones")
    db.write(conn, "zones", {"id": zid, "chain_id": chain_id, "name": zkey, "rep_store_id": None})
    return zid


def _area_of(s, areas: list) -> str:
    """The nearest area, so a store keeps one zone even where two areas overlap."""
    return min(areas, key=lambda a: distance_km(a["lat"], a["lon"], s.lat, s.lon))["name"]


def _upsert_store(conn, s, names: dict, areas: list) -> None:
    key, banner = chain_of_store(s)  # ATAC: its own chain, requested under AUCHAN
    chain_id = _chain_id(conn, key, banner or names.get(s.chain_key, s.chain_key))
    zkey = "%s|%s" % (zone_key(s), _area_of(s, areas))  # zones per area: chains may price differently by city
    row = {"chain_id": chain_id, "zone_id": _zone_id(conn, zkey, chain_id), "name": s.name,
           "address": s.address, "lat": s.lat, "lon": s.lon, "type": s.type, "active": 1}
    old = conn.execute("SELECT chain_id, zone_id, name, address, lat, lon, type, active FROM stores WHERE id = ?",
                       (s.id,)).fetchone()
    if old != tuple(row.values()):
        db.write(conn, "stores", dict(id=s.id, **row), replace=True)


_brand_id = db.brand_id


def _upsert_product(conn, pid: int, name: str, category_id=None, brand=None) -> None:
    """New products get their shop name, size and reported brand; existing ones only a missing category or brand.
    The catalog build (step 2) owns titles, items and brand spelling, so whole rows are carried over, never cut."""
    cols = ("name", "category_id", "brand_id", "size_qty", "size_unit", "title", "item_id", "barcode")
    row = conn.execute("SELECT %s FROM products WHERE id = ?" % ", ".join(cols), (pid,)).fetchone()
    if row:
        cur = dict(zip(cols, row))
        new = dict(cur, category_id=category_id if category_id is not None else cur["category_id"],
                   brand_id=cur["brand_id"] or (_brand_id(conn, brand) if brand else None))
        if new == cur:
            return
    else:
        qty, unit = parse_size(name) or (None, None)
        new = {"name": name, "category_id": category_id, "brand_id": _brand_id(conn, brand) if brand else None,
               "size_qty": qty, "size_unit": unit}
    db.write(conn, "products", dict(id=pid, **new), replace=True)


def _sizes_from_shop_names(conn, obs) -> None:
    """A product without a pack size takes the size most shops' own names give it ("KETCHUP TOPDOWN 400ML HEINZ")."""
    missing = {r[0] for r in conn.execute("SELECT id FROM products WHERE size_qty IS NULL")}
    found = {}
    for o in obs:
        if o.product_id in missing:
            size = parse_size(o.shop_name)
            if size:
                found.setdefault(o.product_id, Counter())[size] += 1
    for pid, sizes in found.items():
        qty, unit = sizes.most_common(1)[0][0]
        row = conn.execute("SELECT name, category_id, brand_id, title, item_id, barcode FROM products WHERE id = ?", (pid,)).fetchone()
        db.write(conn, "products", {"id": pid, "name": row[0], "category_id": row[1], "brand_id": row[2], "size_qty": qty,
                                    "size_unit": unit, "title": row[3], "item_id": row[4], "barcode": row[5]}, replace=True)


def tracked_ids(conn, staples: list) -> list:
    """Staples, favorites and products on promo now, each once, capped."""
    ids = list(staples) + [r[0] for r in conn.execute("SELECT ref FROM favorites WHERE kind = 'p'")]
    ids += sorted(p for (_, p), (price, promo) in current_zone_prices(conn).items() if promo and price is not None)
    # shortcut: list items join here once step 3 defines the list format.
    return list(dict.fromkeys(ids))[:TRACK_CAP]


def _fail(report: Report, key: str, err: Exception, step: str = "") -> None:
    print("FAILED %s%s: %s" % (key, " (%s)" % step if step else "", err), file=sys.stderr)
    if key not in report.chains_failed:
        report.chains_failed.append(key)


def run(conn, client, areas: list, weekly: bool, out_dir: str, staples=(), categories=None, day=None) -> Report:
    rep = Report()
    nets = client.networks()
    keys = list(nets)

    # 1. catalog (weekly, or the first time): each chain's own products, one request per chain
    if weekly or not conn.execute("SELECT 1 FROM chain_products LIMIT 1").fetchone():
        try:
            cats = client.categories()
        except Exception as e:
            _fail(rep, "catalog", e, "categories")
            cats = []
        for cid, name, parent in cats:
            if conn.execute("SELECT name, parent_id FROM categories WHERE id = ?", (cid,)).fetchone() != (name, parent):
                db.write(conn, "categories", {"id": cid, "name": name, "parent_id": parent}, replace=True)
        for key in keys:
            try:
                products = client.chain_catalog(key, sorted(categories) if categories else None)
            except Exception as e:  # keeps last week's list; today's prices still count
                _fail(rep, "catalog:%s" % key, e, "catalog")
                continue
            for p in products:
                _upsert_product(conn, p.id, p.name, p.category_id)
            conn.execute("DELETE FROM chain_products WHERE chain_key = ?", (key,))  # robot-only: not sent to D1
            conn.executemany("INSERT OR IGNORE INTO chain_products VALUES (?, ?)", [(key, p.id) for p in products])

    # 2. stores (weekly, or the first time); the API needs product ids, so search with the staples
    probe = (list(staples) or [r[0] for r in conn.execute("SELECT id FROM products ORDER BY id LIMIT 200")])[:200]
    if (weekly or not conn.execute("SELECT 1 FROM stores LIMIT 1").fetchone()) and not probe:
        _fail(rep, "stores", ValueError("no staples or catalog products to search stores with"), "stores")
    elif weekly or not conn.execute("SELECT 1 FROM stores LIMIT 1").fetchone():
        for key in keys:
            for a in areas:
                try:
                    stores, _, capped = client.stores_prices(a["lat"], a["lon"], a.get("radius_m", 5000), probe, key)
                except Exception as e:  # one chain failing must not stop the others
                    _fail(rep, key, e, "stores")
                    continue
                if capped and key not in rep.capped:
                    rep.capped.append(key)
                for s in stores:
                    _upsert_store(conn, s, nets, areas)
        for i, a in enumerate(areas, 1):
            row = (a["name"], a["lat"], a["lon"], a.get("radius_m", 5000))
            if conn.execute("SELECT name, lat, lon, radius_m FROM areas WHERE id = ?", (i,)).fetchone() != row:
                db.write(conn, "areas", dict(zip(("id", "name", "lat", "lon", "radius_m"), (i,) + row)), replace=True)

    # 3. prices: tracked products + today's rotation slice in every store, per chain and area
    run_day = day if day is not None else ro_today()
    catalog = [r[0] for r in conn.execute("SELECT id FROM products ORDER BY id")]
    tracked = tracked_ids(conn, staples)
    sells = {key: [r[0] for r in conn.execute(
        "SELECT product_id FROM chain_products WHERE chain_key = ? ORDER BY product_id", (key,))] for key in keys}
    all_obs, checked = [], set()
    for key in keys:
        # each chain only about its own products; the whole catalog only for a chain whose list is unknown
        wanted = list(dict.fromkeys(tracked + (sells[key] or catalog)[run_day % ROTATION_DAYS::ROTATION_DAYS]))
        ok = True
        for a in areas:
            try:
                stores, obs, capped = client.stores_prices(a["lat"], a["lon"], a.get("radius_m", 5000), wanted, key)
            except Exception as e:
                _fail(rep, key, e, "prices")
                ok = False
                break
            if capped and key not in rep.capped:
                rep.capped.append(key)
            for s in stores:
                _upsert_store(conn, s, nets, areas)
            all_obs += obs
            checked |= {(o.store_id, o.product_id) for o in obs}
        if ok:
            rep.chains_ok.append(key)

    # 4. the whole catalog once per zone, from its representative store
    seen = Counter(o.store_id for o in all_obs)
    for zid, zname, key, old_rep in conn.execute(
            "SELECT z.id, z.name, c.source_key, z.rep_store_id FROM zones z JOIN chains c ON c.id = z.chain_id").fetchall():
        key = network(key)  # a chain like ATAC is requested under its network
        if key not in keys or key in rep.chains_failed:
            continue
        members = [r[0] for r in conn.execute("SELECT id FROM stores WHERE zone_id = ? AND active = 1", (zid,))]
        if not members:
            continue
        rep_id = pick_rep(members, seen)
        if rep_id != old_rep:
            db.write(conn, "zones", {"id": zid, "chain_id": conn.execute("SELECT chain_id FROM zones WHERE id = ?", (zid,)).fetchone()[0],
                                     "name": zname, "rep_store_id": rep_id}, replace=True)
        lat, lon = conn.execute("SELECT lat, lon FROM stores WHERE id = ?", (rep_id,)).fetchone()
        priced = [r[0] for r in conn.execute("SELECT DISTINCT product_id FROM zone_prices WHERE zone_id = ?", (zid,))]
        pool = sells.get(key) or catalog
        if priced:  # what the zone sells, plus a seventh a day of the chain's other products, so new ones arrive within a week
            known = set(priced)  # not `seen`: that name holds pick_rep's observation counts
            ids = priced + [p for p in pool if p not in known][run_day % ROTATION_DAYS::ROTATION_DAYS]
        else:
            ids = pool
        try:
            _, obs, _ = client.stores_prices(lat, lon, REP_RADIUS_M, ids, key)
        except Exception as e:
            _fail(rep, key, e, "zone catalog")
            continue
        own = [o for o in obs if o.store_id == rep_id]
        all_obs += own
        checked |= {(rep_id, o.product_id) for o in own}

    # 5. drop everything from chains that failed anywhere; keep one observation per store and product
    chain_of = {sid: network(key) for sid, key in conn.execute(
        "SELECT s.id, c.source_key FROM stores s JOIN chains c ON c.id = s.chain_id")}
    failed = set(rep.chains_failed)
    rep.chains_ok = [k for k in rep.chains_ok if k not in failed]
    best = {}
    for o in all_obs:
        if chain_of.get(o.store_id) in failed:
            continue
        if o.odd:  # the shop's own name describes another product: not this product's price
            rep.odd += 1
            continue
        k = (o.store_id, o.product_id)
        if k not in best or (o.price_bani is not None and (best[k].price_bani is None or o.price_bani < best[k].price_bani)):
            best[k] = o
    checked = {k for k in checked if chain_of.get(k[0]) not in failed}
    uniq = list(best.values())
    for o in uniq:
        if o.cat_id is not None and not conn.execute("SELECT 1 FROM categories WHERE id = ?", (o.cat_id,)).fetchone():
            db.write(conn, "categories", {"id": o.cat_id, "name": o.cat_name or str(o.cat_id), "parent_id": None})
        _upsert_product(conn, o.product_id, o.name, o.cat_id, o.brand or None)
    _sizes_from_shop_names(conn, [o for o in all_obs if not o.odd and o.shop_name])
    days = [o.day for o in uniq if o.day is not None]
    rep.day = max(days) if days else run_day  # the date of the prices, not the machine clock

    # 6. change-only history
    zone_of = {sid: zname for sid, zname in conn.execute("SELECT s.id, z.name FROM stores s JOIN zones z ON z.id = s.zone_id")}
    zid_of = {zname: zid for zid, zname in conn.execute("SELECT id, name FROM zones")}
    name_of = {zid: zname for zname, zid in zid_of.items()}
    current = {(name_of[z], p): v for (z, p), v in current_zone_prices(conn).items() if z in name_of}
    # stores already known to differ don't set the zone price (spec: the representative store may itself differ)
    zvals, exc = split([o for o in uniq if o.store_id in zone_of], zone_of, set(current_store_prices(conn)), current)
    rep.zone_rows = apply_zone(conn, rep.day, {(zid_of[zk], pid): v for (zk, pid), v in zvals.items()})
    rep.store_rows = apply_store(conn, rep.day, checked, exc)
    for zid, n in Counter(zid_of[zk] for zk, _ in zvals).items():
        if conn.execute("SELECT products FROM zone_checks WHERE zone_id = ? AND day = ?", (zid, rep.day)).fetchone() != (n,):
            db.write(conn, "zone_checks", {"zone_id": zid, "day": rep.day, "products": n}, replace=True)

    # 7. one daily file per area (latest + dated copy); products the cleaning rules can't fix are left out and listed
    hide = for_review(conn)
    write_review(conn, hide, out_dir)
    for a in areas:
        data = build_daily(conn, a, rep.day, hide)
        rep.files[a["name"]] = write_daily(os.path.join(out_dir, a["name"], "latest.json.gz"), data)
        write_daily(os.path.join(out_dir, a["name"], db.day_to_date(rep.day).isoformat() + ".json.gz"), data)
    conn.commit()
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PrețBun daily price robot")
    ap.add_argument("--db", required=True)
    ap.add_argument("--areas", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--weekly", action="store_true", help="also refresh stores and the catalog")
    ap.add_argument("--staples", default="staples.txt")
    ap.add_argument("--categories", default="", help="comma-separated category ids to limit the catalog (testing)")
    ap.add_argument("--raw", help="folder to keep the raw answers of this run")
    ap.add_argument("--offline", help="fixtures folder: answer from saved responses instead of the network")
    args = ap.parse_args(argv)
    with open(args.areas, encoding="utf-8") as f:
        areas = json.load(f)
    staples = read_staples(args.staples) if os.path.exists(args.staples) else []
    client = OfflineClient(args.offline, {"PENNY": "stores_penny.xml"}) if args.offline else Client(raw_dir=args.raw)
    conn = db.connect(args.db)
    forget_app(conn, "wolt")  # its terms forbid bots: the prices collected before 2026-11-10 go (a no-op afterwards)
    cats = {int(c) for c in args.categories.split(",") if c.strip()} or None
    report = run(conn, client, areas, args.weekly, args.out, staples, cats)
    print(json.dumps(asdict(report), ensure_ascii=False))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
