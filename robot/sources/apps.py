"""Delivery-app prices from public store pages (Glovo, Wolt): each page shows the store's featured products and
promotions. Full catalogues load from the apps' internal data services, which we don't use (a decision for the user;
Claude Code's safety check refused it on 2026-11-09). Storefronts come from catalog/apps.tsv."""
from __future__ import annotations


from .. import channels
from .web import Blocked

APP_NAMES = {"glovo": "Glovo"}
TITLES = {"brasov": "Brașov", "bucuresti": "București"}


def read_apps(path: str) -> list:
    """catalog/apps.tsv: app, area, store, chain (official source key or '-'), label."""
    with open(path, encoding="utf-8") as f:
        lines = [line.rstrip("\n").split("\t") for line in f if line.strip() and not line.startswith("#")]
    head = lines[0]
    return [dict(zip(head, cells)) for cells in lines[1:]]


def _bani(x):
    return None if x is None else int(round(x * 100))


def run(conn, web, today: int, areas: list, rows: list, app: str, page_url, parse,
        cap: int = channels.DAILY_CAP) -> dict:
    """page_url(area_name, store) -> address; parse(html) -> [(ext, name, price paid, regular price or None)]."""
    by_name = {a["name"]: a for a in areas}
    mine = [r for r in rows if r["app"] == app]
    for r in mine:
        if r["area"] not in by_name:
            raise ValueError("area %r is in catalog/apps.tsv but not in areas.json" % r["area"])
    pages = found = written = 0
    missing, left = [], cap
    for r in mine:
        area = by_name[r["area"]]
        title = TITLES.get(area["name"], area["name"].title())
        try:
            html = web.get(page_url(area["name"], r["store"]))
        except (Blocked, OSError):  # a store that left the app, a page we may not read, or no network
            missing.append(r["store"])
            continue
        pages += 1
        row = conn.execute("SELECT id FROM chains WHERE source_key = ?", (r["chain"],)).fetchone()
        place = channels.place_id(conn, "app", "%s · %s %s" % (APP_NAMES.get(app, app), r["label"], title), app=app,
                                  area_id=channels.area_id(conn, area), chain_id=row[0] if row else None)
        new = {}
        for ext, name, paid, regular in parse(html):
            found += 1
            pid = channels.product_for(conn, app, "%s:%s" % (r["store"], ext), name)
            promo = 1 if regular and paid < regular else 0
            new[pid] = (_bani(paid), promo, _bani(regular) if promo else None, None)
        n = channels.apply_place(conn, place, today, new, "app", cap=left)
        written, left = written + n, left - n
        conn.commit()
        if left <= 0:
            break
    note = "%d store pages, %d products, %d changes" % (pages, found, written)
    if missing:
        note += "; not readable: %s" % ", ".join(missing)
    if mine and not found:
        return {"pages": pages, "products": 0, "written": written, "ok": False,
                "note": "0 products from %d store pages: has %s changed its pages? %s" % (pages, APP_NAMES.get(app, app), note)}
    return {"pages": pages, "products": found, "written": written, "ok": True, "note": note}
