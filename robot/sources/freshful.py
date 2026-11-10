"""Freshful online prices from its public pages: every subcategory page shows its first 20 products.

The rest of a long subcategory loads from Freshful's internal data service, which we don't use (see glovo.py). With
about 490 subcategories, most of them small, the public pages still cover a large part of the shop. Weekly.
"""
from __future__ import annotations


from .. import channels
from .freshful_html import categories, products
from .web import Blocked

SITE = "https://www.freshful.ro"


def _bani(x):
    return None if x is None else int(round(x * 100))


def run(conn, web, today: int, max_pages: int = 600, cap: int = channels.DAILY_CAP) -> dict:
    cats = categories(web.get(SITE + "/"))
    place = channels.place_id(conn, "online", "Freshful", url=SITE)
    new, pages, found, unreadable = {}, 0, 0, 0
    for slug in cats[:max_pages]:
        try:
            html = web.get("%s/c/%s" % (SITE, slug))
        except (Blocked, OSError):  # a page we may not read, or still no network after the retries
            unreadable += 1
            continue
        pages += 1
        for p in products(html):
            found += 1
            pid = channels.product_for(conn, "freshful", p["sku"], p["name"], p["brand"])
            promo = 1 if p["original"] and p["original"] > p["price"] else 0
            new[pid] = (_bani(p["price"]), promo, _bani(p["original"]) if promo else None, None)  # seen twice: once
    written = channels.apply_place(conn, place, today, new, "site", cap=cap)
    conn.commit()
    if not new:
        return {"pages": pages, "products": 0, "written": 0, "ok": False,
                "note": "0 products from %d category pages: has Freshful changed its pages?" % pages}
    note = "%d category pages, %d products, %d changes" % (pages, len(new), written)
    if unreadable:
        note += "; %d pages not readable" % unreadable
    return {"pages": pages, "products": len(new), "written": written, "ok": True, "note": note}
