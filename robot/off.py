"""Open Food Facts, products sold in Romania: a monthly download, exact labels only when certain, typical values.
Data: © Open Food Facts contributors, ODbL (the app credits it where facts are shown).

python3 -m robot.off fetch --out off.jsonl.gz
python3 -m robot.off match --db pretbun.sqlite --off off.jsonl.gz
python3 -m robot.off check --db pretbun.sqlite --off off.jsonl.gz [--sample 100]   the hand check, as TSV
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import statistics
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from . import db
from .brands import BrandIndex
from .catalogdata import load as load_catalog
from .items import place
from .names import attrs as read_attrs, normalize
from .off_export import romania_rows
from .sizes import parse_size

# the bulk export (≈1.5 GB gz, refreshed weekly): the search API stops after 10,000 results, and Open Food Facts asks
# bulk users to read the export instead (found 2026-11-09)
EXPORT = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"
USER_AGENT = "PretBun-robot/0.1 (family project)"
NUTRIENTS = ("energy-kcal_100g", "fat_100g", "saturated-fat_100g", "carbohydrates_100g", "sugars_100g",
             "fiber_100g", "proteins_100g", "salt_100g")
DIET = ("palm-oil-free", "vegan", "vegetarian")
FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog")


@dataclass
class OffProduct:
    code: str
    name: str
    brands: str
    quantity: str
    n: list               # per 100 g/ml, NUTRIENTS order, None where unknown
    grade: Optional[str]  # Nutri-Score a..e
    nova: Optional[int]
    diet: list
    allergens: list
    image: Optional[str]


def _open(path: str, mode: str = "rt"):
    return gzip.open(path, mode, encoding="utf-8") if path.endswith(".gz") else open(path, mode, encoding="utf-8")


def fetch(out_path: str, opener=urllib.request.urlopen, minimum: int = 10000) -> int:
    """Stream the export, keep the products sold in Romania (≈50,000 in Nov 2026) into out_path.
    On any failure, or fewer than `minimum` products (the export changed), the previous file stays as it was."""
    tmp = os.path.join(os.path.dirname(out_path) or ".", ".part-" + os.path.basename(out_path))
    written = 0
    try:
        req = urllib.request.Request(EXPORT, headers={"User-Agent": USER_AGENT})
        with opener(req, timeout=300) as r, gzip.open(r, "rt", encoding="utf-8", errors="replace", newline="\n") as lines, \
                _open(tmp, "wt") as f:
            for p in romania_rows(lines):
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
                written += 1
        if written < minimum:
            raise ValueError("only %d Romanian products in the export (expected at least %d); keeping the old file"
                             % (written, minimum))
        os.replace(tmp, out_path)
        return written
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load(path: str) -> list:
    out = []
    with _open(path) as f:
        for line in f:
            p = json.loads(line)
            name = (p.get("product_name_ro") or p.get("product_name") or "").strip()
            if not name:
                continue
            nut = p.get("nutriments") or {}
            n = [float(v) if isinstance(v, (int, float)) else None for v in (nut.get(k) for k in NUTRIENTS)]
            tags = {t.split(":", 1)[-1] for t in p.get("ingredients_analysis_tags") or []}
            out.append(OffProduct(str(p.get("code")), name, p.get("brands") or "", p.get("quantity") or "", n,
                                  p.get("nutriscore_grade") if p.get("nutriscore_grade") in tuple("abcde") else None,
                                  p.get("nova_group") if isinstance(p.get("nova_group"), int) else None,
                                  [d for d in DIET if d in tags],
                                  sorted(t.split(":", 1)[-1] for t in p.get("allergens_tags") or []),
                                  p.get("image_front_small_url")))
    return out


def _key(o: OffProduct, cat, brands: BrandIndex):
    """(item slug, brand, size) of an Open Food Facts product, read the same way as the shops' products."""
    n = normalize(o.name, cat.abbrev)
    slug, _ = place(-1, n, read_attrs(n), cat)
    brand = next((b for b in (brands.find(normalize(x, cat.abbrev)) for x in o.brands.split(",")) if b), None)
    return slug, brand or brands.find(n), parse_size(normalize(o.quantity, cat.abbrev))


def match(conn, off_list: list, cat, brands: BrandIndex) -> dict:
    """product id -> OffProduct, only when exactly one label has the same item, brand and size (2%)."""
    idx = defaultdict(list)
    for o in off_list:
        slug, brand, size = _key(o, cat, brands)
        if slug and brand and size:
            idx[(slug, brand)].append((size, o))
    out = {}
    for pid, slug, brand, qty, unit in conn.execute(
            "SELECT p.id, s.slug, b.name, p.size_qty, p.size_unit FROM products p JOIN item_info s ON s.item_id = p.item_id "
            "JOIN brands b ON b.id = p.brand_id WHERE p.size_qty IS NOT NULL"):
        cands = [o for (sq, su), o in idx.get((slug, brand), []) if su == unit and abs(sq - qty) <= 0.02 * qty]
        if cands and all(c.n == cands[0].n for c in cands):  # identical nutrition: the same product, another barcode
            out[pid] = cands[0]
    return out


def typical(off_list: list, cat) -> dict:
    """slug -> {"grade", "n", "from"}: medians of the item's labelled products, the most common grade; needs 3."""
    groups = defaultdict(list)
    for o in off_list:
        n = normalize(o.name, cat.abbrev)
        slug, _ = place(-1, n, read_attrs(n), cat)
        if slug and any(v is not None for v in o.n):
            groups[slug].append(o)
    out = {}
    for slug, lst in groups.items():
        if len(lst) < 3:
            continue
        med = []
        for i in range(len(NUTRIENTS)):
            vals = [o.n[i] for o in lst if o.n[i] is not None]
            med.append(round(statistics.median(vals), 2) if vals else None)
        grades = Counter(o.grade for o in lst if o.grade)
        out[slug] = {"grade": grades.most_common(1)[0][0] if grades else None, "n": med, "from": len(lst)}
    return out


def write_facts(conn, matches: dict, typ: dict, day: int) -> int:
    """Labels and typical values, change-only; a product that lost its label loses its facts row."""
    changed = 0
    cur = {r[0]: r[1:] for r in conn.execute("SELECT product_id, code, grade, nova, n, diet, allergens, image FROM facts")}
    for pid, o in matches.items():
        row = (o.code, o.grade, o.nova, json.dumps(o.n, separators=(",", ":")), ",".join(o.diet) or None,
               ",".join(o.allergens) or None, o.image)
        if cur.get(pid) != row:
            db.write(conn, "facts", dict(zip(("product_id", "code", "grade", "nova", "n", "diet", "allergens", "image", "day"),
                                             (pid,) + row + (day,))), replace=True)
            changed += 1
    for pid in set(cur) - set(matches):
        db.remove(conn, "facts", {"product_id": pid})
        changed += 1
    for slug, t in typ.items():
        row = conn.execute("SELECT item_id, shelf, size, typical FROM item_info WHERE slug = ?", (slug,)).fetchone()
        val = json.dumps(t, separators=(",", ":"), sort_keys=True)
        if row and row[3] != val:
            db.write(conn, "item_info", {"item_id": row[0], "slug": slug, "shelf": row[1], "size": row[2], "typical": val},
                     replace=True)
            changed += 1
    conn.commit()
    return changed


def check(conn, off_list: list, sample: int = 100, seed: int = 1) -> list:
    """A random sample of exact labels for a hand check: (our shelf name, label name, label brands, label size, code)."""
    by_code = {o.code: o for o in off_list}
    rows = conn.execute("SELECT f.product_id, p.name, f.code FROM facts f JOIN products p ON p.id = f.product_id "
                        "ORDER BY f.product_id").fetchall()
    random.Random(seed).shuffle(rows)
    return [(name, by_code[code].name, by_code[code].brands, by_code[code].quantity, code)
            for _, name, code in rows if code in by_code][:sample]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Open Food Facts for Romania")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", required=True)
    k = sub.add_parser("check")
    k.add_argument("--db", required=True)
    k.add_argument("--off", required=True)
    k.add_argument("--sample", type=int, default=100)
    m = sub.add_parser("match")
    m.add_argument("--db", required=True)
    m.add_argument("--off", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        print("%d products" % fetch(a.out))
        return 0
    if a.cmd == "check":
        print("ours\tlabel\tbrands\tsize\tcode")
        for row in check(db.connect(a.db), load(a.off), a.sample):
            print("\t".join(str(x) for x in row))
        return 0
    from .run import ro_today
    cat, conn, items = load_catalog(FOLDER), db.connect(a.db), load(a.off)
    matches = match(conn, items, cat, BrandIndex(cat.brands))
    changed = write_facts(conn, matches, typical(items, cat), ro_today())
    print(json.dumps({"off_products": len(items), "labelled": len(matches), "changed": changed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
