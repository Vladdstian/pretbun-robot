"""Catalog build (step 2): place products in items, give them plain names, brands, sizes and attributes, and write
only what changed. New products every run; everything when the catalog files change (their hash is kept in meta).

python3 -m robot.catalog --db pretbun.sqlite --out reports [--everything]
"""
from __future__ import annotations

from collections import Counter

import argparse
import json
import os
from dataclasses import asdict, dataclass

from . import db
from .brands import find_learned, learned_brands, BrandIndex
from .catalogdata import catalog_hash, load
from .dailyfile import write_daily
from .items import tidy_name, place, title
from .names import attrs as read_attrs, normalize
from .run import _brand_id, ro_today
from .sizes import priced_per_piece, parse_size

FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog")


@dataclass
class Report:
    placed: int = 0
    unplaced: int = 0
    changed: int = 0   # product rows written (products + product_info)


def _meta(conn, key: str, value: str = None):
    if value is None:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))  # robot-only, never in the outbox


def _items(conn, cat) -> dict:
    """slug -> item id. A slug keeps its id forever; a new item gets the next free id."""
    ids = dict(conn.execute("SELECT slug, item_id FROM item_info"))
    nxt = max([0] + list(ids.values()) + [conn.execute("SELECT COALESCE(MAX(id), 0) FROM items").fetchone()[0]]) + 1
    for it in cat.items:
        if it.slug not in ids:
            ids[it.slug], nxt = nxt, nxt + 1
        iid = ids[it.slug]
        if conn.execute("SELECT name, unit FROM items WHERE id = ?", (iid,)).fetchone() != (it.name, it.unit):
            db.write(conn, "items", {"id": iid, "name": it.name, "unit": it.unit}, replace=True)
        old = conn.execute("SELECT slug, shelf, size, typical FROM item_info WHERE item_id = ?", (iid,)).fetchone()
        typical = old[3] if old else None
        if old != (it.slug, it.shelf, it.size, typical):
            db.write(conn, "item_info", {"item_id": iid, "slug": it.slug, "shelf": it.shelf, "size": it.size,
                                         "typical": typical}, replace=True)
    return ids


# Official categories sold at the counter by weight: a product in one of them without a size is priced per kg (2026-11-10)
BY_WEIGHT = {"PASARE", "PESTE", "PORC", "VITA", "GATITA", "MEZELURI - ALTELE", "CARNE PROCESATA - ALTELE", "PROASPETE - ALTELE"}


def _sized_index(conn, cat) -> dict:
    """First word -> [(normalized name, product id, size)] for every product whose own name gives a size."""
    index = {}
    for pid, name in conn.execute("SELECT id, name FROM products"):
        n = normalize(name, cat.abbrev)
        size = parse_size(n)
        if size and n:
            index.setdefault(n.split()[0], []).append((n, pid, size))
    return index


def _complete_size(n: str, pid: int, index: dict, medians: dict):
    """A name cut short ("ketchup heinz top do") takes the size of the one full name it begins ("... top down 400ml"),
    when that product costs nearly the same (within 15%); several sizes or no price: no answer."""
    words, price = n.split(), medians.get(pid)
    if not words or price is None:
        return None
    start = " ".join(words)
    sizes = {size for m, q, size in index.get(words[0], []) if q != pid and m.startswith(start) and len(m) > len(start)
             and medians.get(q) is not None and abs(medians[q] - price) <= 0.15 * price}
    return sizes.pop() if len(sizes) == 1 else None


def _own_brands(conn, cat, learned: dict) -> dict:
    """Keep a learned brand only if most products whose names hold it carry that brand: "Agricola" is a maker, while
    "Cartofi", which one shop puts in the brand field, names potatoes of many makers (2026-11-10)."""
    holds, same = Counter(), Counter()
    for name, brand in conn.execute("SELECT p.name, b.name FROM products p LEFT JOIN brands b ON b.id = p.brand_id"):
        if not brand:
            continue  # only products with a brand say what a word means
        words, own = set(normalize(name, cat.abbrev).split()), normalize(brand)
        for w in words & learned.keys():
            holds[w] += 1
            same[w] += own == w
    return {k: v for k, v in learned.items() if " " in k or holds[k] == 0 or same[k] * 2 >= holds[k]}


def _median_prices(conn) -> dict:
    """Each product's middle price today across the zones."""
    from robot.history import current_zone_prices
    by = {}
    for (_, pid), (price, _) in current_zone_prices(conn).items():
        if price is not None:
            by.setdefault(pid, []).append(price)
    return {pid: sorted(v)[len(v) // 2] for pid, v in by.items()}


def build(conn, cat, day: int, everything: bool = False, folder: str = FOLDER, out: str = None) -> Report:
    rep = Report()
    h = catalog_hash(folder)
    everything = everything or h != _meta(conn, "catalog_hash")
    ids, by_slug, brands = _items(conn, cat), {it.slug: it for it in cat.items}, BrandIndex(cat.brands)
    brand_names = dict(conn.execute("SELECT id, name FROM brands"))
    rows = conn.execute("SELECT id, name, title, brand_id, item_id, category_id, size_qty, size_unit, barcode FROM products"
                        + ("" if everything else " WHERE title IS NULL")).fetchall()
    medians = index = None
    cat_names = dict(conn.execute("SELECT id, name FROM categories"))
    learned = _own_brands(conn, cat, learned_brands(conn.execute(
        "SELECT b.name, COUNT(*) FROM products p JOIN brands b ON b.id = p.brand_id GROUP BY b.name")))
    for pid, name, old_title, brand_id, item_id, cid, sq, su, barcode in rows:
        n = normalize(name, cat.abbrev)
        at = read_attrs(n)
        slug, _ = place(pid, n, at, cat)
        _, forced_title, forced_brand = cat.overrides.get(pid, (None, None, None))
        size = parse_size(n) or (sq, su)
        if not size or not size[0]:
            medians = medians if medians is not None else _median_prices(conn)
            index = index if index is not None else _sized_index(conn, cat)
            if (cat_names.get(cid) or "").upper() in BY_WEIGHT:
                size = (1000, "g")
            else:
                size = _complete_size(n, pid, index, medians) or size
        if slug and slug.startswith("oua"):  # eggs priced per egg ("Oua L*10" at 0,62 lei): the pack is one egg
            medians = medians if medians is not None else _median_prices(conn)
            if priced_per_piece(size, medians.get(pid)):
                size = (1, "buc")
        brand = forced_brand or brands.find(n, brand_names.get(brand_id)) or find_learned(n, learned)
        shown = tuple(size) if size and size[0] else None  # the name shows the size the price is for
        new = (forced_title or (title(by_slug.get(slug), at, shown, name) if slug else tidy_name(n, shown)),
               _brand_id(conn, brand) if brand else brand_id, ids[slug] if slug else None) + tuple(size)
        if new != (old_title, brand_id, item_id, sq, su):
            db.write(conn, "products", {"id": pid, "name": name, "title": new[0], "brand_id": new[1], "item_id": new[2],
                                        "category_id": cid, "size_qty": new[3], "size_unit": new[4], "barcode": barcode},
                     replace=True)
            rep.changed += 1
        a = json.dumps(at, sort_keys=True, separators=(",", ":")) if at else None
        old = conn.execute("SELECT attrs FROM product_info WHERE product_id = ?", (pid,)).fetchone()
        if (old[0] if old else None) != a:
            db.write(conn, "product_info", {"product_id": pid, "attrs": a}, replace=True)
            rep.changed += 1
        rep.placed += slug is not None
        rep.unplaced += slug is None
    _meta(conn, "catalog_hash", h)
    if out:
        _reports(conn, cat, out)
    conn.commit()
    return rep


def _reports(conn, cat, out: str) -> None:
    """coverage.txt per category and review.tsv: unplaced products, the stage's categories first, then by zones."""
    os.makedirs(out, exist_ok=True)
    names = dict(conn.execute("SELECT id, name FROM categories"))
    stats = conn.execute("SELECT category_id, COUNT(*), COUNT(item_id), COUNT(size_qty), COUNT(brand_id) FROM products "
                         "GROUP BY category_id ORDER BY COUNT(*) DESC").fetchall()
    with open(os.path.join(out, "coverage.txt"), "w", encoding="utf-8") as f:
        for cid, n, p, z, b in stats:
            f.write("%-24s %6d products  placed %5.1f%%  size %5.1f%%  brand %5.1f%%\n"
                    % (names.get(cid, cid), n, 100 * p / n, 100 * z / n, 100 * b / n))
    relevant = {cid for cid, _, p, _, _ in stats if p}
    zones = dict(conn.execute("SELECT product_id, COUNT(DISTINCT zone_id) FROM zone_prices GROUP BY product_id"))
    review = []
    for pid, name, cid in conn.execute("SELECT id, name, category_id FROM products WHERE item_id IS NULL"):
        if cat.overrides.get(pid, (None,))[0] == "-":
            continue  # reviewed: not an item
        n = normalize(name, cat.abbrev)
        review.append((cid not in relevant, -zones.get(pid, 0), name, pid, place(pid, n, read_attrs(n), cat)[1], cid))
    with open(os.path.join(out, "review.tsv"), "w", encoding="utf-8") as f:
        f.write("product_id\treason\tcategory\tzones\tname\n")
        for _, minus_zones, name, pid, why, cid in sorted(review):
            f.write("%d\t%s\t%s\t%d\t%s\n" % (pid, why, names.get(cid, cid), -minus_zones, name))


def app_files(conn, cat, out: str) -> None:
    """items.json.gz (items, typical values, shelves in order) and facts.json.gz (labelled products) for the app."""
    items = [{"id": iid, "slug": slug, "name": name, "shelf": shelf, "unit": unit, "size": size,
              "typical": json.loads(t) if t else None}
             for iid, slug, name, shelf, unit, size, t in conn.execute(
                 "SELECT s.item_id, s.slug, i.name, s.shelf, i.unit, s.size, s.typical FROM item_info s "
                 "JOIN items i ON i.id = s.item_id ORDER BY s.item_id")]
    facts = {str(pid): {"code": code, "grade": grade, "nova": nova, "n": json.loads(n) if n else None,
                        "diet": diet.split(",") if diet else [], "allergens": allergens.split(",") if allergens else [],
                        "image": image}
             for pid, code, grade, nova, n, diet, allergens, image in conn.execute(
                 "SELECT product_id, code, grade, nova, n, diet, allergens, image FROM facts ORDER BY product_id")}
    write_daily(os.path.join(out, "items.json.gz"), {"shelves": list(dict.fromkeys(it.shelf for it in cat.items)),
                                                     "items": items})
    write_daily(os.path.join(out, "facts.json.gz"), facts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Place products in items, plain names, brands, sizes (step 2)")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="reports")
    ap.add_argument("--everything", action="store_true", help="place every product, not only new ones")
    ap.add_argument("--files", help="also write the app's items.json.gz and facts.json.gz into this folder")
    a = ap.parse_args(argv)
    conn, cat = db.connect(a.db), load(FOLDER)
    rep = build(conn, cat, ro_today(), a.everything, FOLDER, a.out)
    if a.files:
        app_files(conn, cat, a.files)
    print(json.dumps(asdict(rep)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
