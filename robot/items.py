"""Place a product in a general item, and build its plain name.

A rule word may list alternatives (`prefiert|parboiled`) and end in * to match a word start. A condition
`fat 1.2-1.9` needs the attribute; `fat? 78-90` also accepts a name that doesn't state it. Equal-rank matches go
to the review list: an unplaced product is still found by name, a wrong item misleads.
"""
from __future__ import annotations

import re


def _hit(token: str, words: set) -> bool:
    for alt in token.split("|"):
        if alt.endswith("*"):
            if any(w.startswith(alt[:-1]) for w in words):
                return True
        elif alt in words:
            return True
    return False


def _holds(cond: tuple, attrs: dict) -> bool:
    attr, lo, hi = cond
    optional, attr = attr.endswith("?"), attr.rstrip("?")
    if attr not in attrs:
        return optional
    value = attrs[attr]
    if hi is None:
        return str(value) in str(lo).split("|")
    try:
        return lo <= float(value) <= hi
    except (TypeError, ValueError):
        return False


WITH, MADE_OF = {"cu", "si", "aroma", "fara", "fr", "fz"}, {"sos", "crema", "aroma"}  # "biscuiți cu unt", "sos de unt": made with the item; "fără zahăr" (fr, fz): without it


def _as_ingredient(seq: list, i: int) -> bool:
    return i > 0 and (seq[i - 1] in WITH or (seq[i - 1] == "de" and i > 1 and seq[i - 2] in MADE_OF))  # "brizură de orez" stays rice


def _only_as_ingredient(token: str, seq: list) -> bool:
    at = [i for i, w in enumerate(seq) if _hit(token, {w})]
    return bool(at) and all(_as_ingredient(seq, i) for i in at)


def matches(item, words: set, attrs: dict, seq=None) -> bool:
    return (all(_hit(t, words) for t in item.all) and not any(_hit(t, words) for t in item.none)
            and all(_holds(c, attrs) for c in item.when) and not (seq and item.all and _only_as_ingredient(item.all[0], seq)))


def place(pid: int, norm: str, attrs: dict, cat):
    """(slug or None, reason): override, rule, 'no rule' or 'tie:a,b'."""
    forced = cat.overrides.get(pid)
    if forced and forced[0]:
        return (None if forced[0] == "-" else forced[0]), "override"
    seq = norm.split()
    words = set(seq)
    hits = [it for it in cat.items if matches(it, words, attrs, seq)]
    if not hits:
        return None, "no rule"
    top = max(it.rank for it in hits)
    best = [it.slug for it in hits if it.rank == top]
    return (best[0], "rule") if len(best) == 1 else (None, "tie:" + ",".join(best))


def _num(v) -> str:
    return ("%g" % v).replace(".", ",")


def size_text(size) -> str:
    if not size:
        return ""
    qty, unit = size
    if unit == "ml":
        return "%s L" % _num(qty / 1000) if qty >= 1000 else "%d ml" % qty
    if unit == "g":
        return "%s kg" % _num(qty / 1000) if qty >= 1000 else "%d g" % qty
    return "%d buc" % qty


_SIZE_WORD = re.compile(r"^\d+(?:[.,]\d+)?(?:x\d+(?:[.,]\d+)?)?(?:g|gr|kg|ml|l|cl|buc)$")


def tidy_name(norm: str, size) -> str:
    """A product with no item: its normalized words (abbreviations spelled out), the pack size moved to the end."""
    words = [w for w in norm.split() if not _SIZE_WORD.match(w)]
    text = " ".join(words)
    return text[:1].upper() + text[1:] + (" · " + size_text(size) if size else "")


def title(item, attrs: dict, size, shop_name: str) -> str:
    """'Lapte 1,5% · 1 L' from the item's template; without an item, the shop name tidied."""
    if item is None:
        text = " ".join((shop_name or "").split())
        return text[:1].upper() + text[1:]
    t = item.title.replace("{fat}", _num(attrs["fat"]) + "%" if "fat" in attrs else "(fără procent pe etichetă)")
    t = t.replace("{egg}", attrs.get("egg", "")).replace("{flour}", str(attrs.get("flour", "")))
    t = " ".join(t.split())
    return t + (" · " + size_text(size) if size else "")
