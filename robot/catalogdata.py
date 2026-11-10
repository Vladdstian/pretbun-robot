"""The catalog's plain data files (catalog/*.tsv): items and their rules, brands, abbreviations, corrections, typical values.

Tab-separated, one header line, '#' comments. Split on tabs rather than read with csv: shop names may contain quotes.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Optional

UNITS = ("kg", "l", "buc")
FILES = ("items.tsv", "brands.tsv", "abbrev.tsv", "overrides.tsv", "typical.tsv")
NUTRIENTS = ("kcal", "fat", "sat", "carb", "sugar", "fiber", "prot", "salt")


@dataclass(frozen=True)
class Item:
    slug: str
    name: str
    title: str      # plain-name template: {fat}, {egg}, {flour}… come from the product's attributes
    shelf: str
    unit: str       # price-per-unit base
    size: Optional[int]  # usual size, in ml, g or pieces
    all: tuple      # words that must all appear; a trailing * matches a word start
    none: tuple     # words that rule the item out
    when: tuple     # (attr, lo, hi) numeric range, or (attr, value, None)
    rank: int


@dataclass
class Catalog:
    items: list = field(default_factory=list)
    brands: list = field(default_factory=list)      # (display, aliases, label)
    abbrev: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)   # product_id -> (slug | "-" | None, title | None, brand | None)
    typical: dict = field(default_factory=dict)     # slug -> {"n": [...8 nutrients], "grade": str, "source": str}


def _rows(path: str):
    """(line number, {column: value}) for every data line."""
    with open(path, encoding="utf-8") as f:
        lines = [(n, l.rstrip("\n")) for n, l in enumerate(f, 1) if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0][1].split("\t")]
    out = []
    for n, line in lines[1:]:
        cells = [c.strip() for c in line.split("\t")]
        out.append((n, dict(zip(head, cells + [""] * (len(head) - len(cells))))))
    return out


def _when(text: str, where: str) -> tuple:
    conds = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        attr, _, value = part.partition(" ")
        m = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", value.strip())
        if not attr or not value.strip():
            raise ValueError("%s: unreadable condition %r" % (where, part))
        conds.append((attr, float(m.group(1)), float(m.group(2))) if m else (attr, value.strip(), None))
    return tuple(conds)


def load(folder: str = "catalog") -> Catalog:
    cat = Catalog()
    seen = set()
    for n, r in _rows(os.path.join(folder, "items.tsv")):
        where = "items.tsv:%d" % n
        slug = r["slug"]
        if not re.fullmatch(r"[a-z0-9-]+", slug) or slug in seen:
            raise ValueError("%s: bad or duplicate slug %r" % (where, slug))
        if r["unit"] not in UNITS:
            raise ValueError("%s: unit must be one of %s, not %r" % (where, UNITS, r["unit"]))
        if not r["all"]:
            raise ValueError("%s: %s has no words to match" % (where, slug))
        seen.add(slug)
        cat.items.append(Item(slug, r["name"], r["title"] or r["name"], r["shelf"], r["unit"],
                              int(r["size"]) if r["size"] else None, tuple(r["all"].split()), tuple(r["none"].split()),
                              _when(r["when"], where), int(r["rank"]) if r["rank"] else 0))
    for n, r in _rows(os.path.join(folder, "brands.tsv")):
        cat.brands.append((r["brand"], tuple(a.strip() for a in r["aliases"].split("|") if a.strip()), r["label"] or None))
    for n, r in _rows(os.path.join(folder, "abbrev.tsv")):
        cat.abbrev[r["short"]] = r["long"]
    for n, r in _rows(os.path.join(folder, "overrides.tsv")):
        slug = r["slug"] or None
        if slug not in (None, "-") and slug not in seen:
            raise ValueError("overrides.tsv:%d: unknown item %r" % (n, slug))
        cat.overrides[int(r["product_id"])] = (slug, r["title"] or None, r["brand"] or None)
    for n, r in _rows(os.path.join(folder, "typical.tsv")):
        if r["slug"] not in seen:
            raise ValueError("typical.tsv:%d: unknown item %r" % (n, r["slug"]))
        cat.typical[r["slug"]] = {"n": [float(r[k]) if r[k] else None for k in NUTRIENTS],
                                  "grade": r["grade"] or None, "source": r["source"]}
    return cat


def catalog_hash(folder: str = "catalog") -> str:
    h = hashlib.sha256()
    for name in sorted(FILES):
        path = os.path.join(folder, name)
        h.update(name.encode() + b"\0")
        if os.path.exists(path):
            with open(path, "rb") as f:
                h.update(f.read())
    here = os.path.dirname(os.path.abspath(__file__))
    for rules in ("sizes.py", "names.py"):  # a fix in how names and sizes are read re-checks every product too
        with open(os.path.join(here, rules), "rb") as f:
            h.update(f.read())
    return h.hexdigest()
