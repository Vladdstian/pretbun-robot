"""Read the pack size from a product name: "Lapte 1,5% 1l" -> (1000, "ml")."""
from __future__ import annotations

import re

_NUM = r"(\d+(?:[.,]\d+)?)"
_FACTOR = {"l": (1000, "ml"), "litri": (1000, "ml"), "litru": (1000, "ml"), "ml": (1, "ml"), "kg": (1000, "g"),
           "g": (1, "g"), "gr": (1, "g"), "grame": (1, "g"),
           "buc": (1, "buc"), "bucati": (1, "buc")}


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_size(name: str):
    s = name.lower()
    if re.search(r"\boua\b", s):  # eggs: "l" is the egg size; "oua 6l" = six size-L eggs, "10buc 2/l" = ten
        if not re.search(r"buc|[x*]\s*\d", s):
            m = re.search(r"\b(\d+)\s*l\b", s)
            if m:
                return int(m.group(1)), "buc"
        s = re.sub(r"\b\d+\s*/?\s*l\b", " ", s)
    s = re.sub(r"\b(\d+)\s*l\s+(?=\d+\s*(?:g|gr)\b)", "", s)  # baby food "7l 160g": 7 months, then the weight
    m = re.search(r"(?<!cod )\b(\d+)\s*[x*]\s*" + _NUM + r"\s*(l|ml|kg|gr|g|buc|bucati)\b", s)  # 6x0.5l, 10*10g, 6x30buc
    if m:
        f, unit = _FACTOR[m.group(3)]
        return int(round(int(m.group(1)) * _num(m.group(2)) * f)), unit
    m = re.search(r"(?<![\d.,])\b(\d) {1,2}(\d)\s*(l|kg)\b", s)  # "1 8l": a decimal point lost in the official name = 1,8 l
    if m and not re.search(r"cod\s*$", s[:m.start()]):
        f, unit = _FACTOR[m.group(3)]
        return int(round(float(m.group(1) + "." + m.group(2)) * f)), unit
    m = re.search(r"(?<![\d.,%])(?<!cod )" + _NUM + r"\s*(kg|ml|litri|litru|l|grame|gr|g)\b", s)  # "cod 2 l": egg code 2, size L
    if m:
        f, unit = _FACTOR[m.group(2)]
        return int(round(_num(m.group(1)) * f)), unit
    m = re.search(r"(?<![\d.,%])(\d{2,4})(ml|gr|g|kg)(?=[a-z]{3,})", s)  # glued to the next word: "264goreo", "350gpronat"
    if m:
        f, unit = _FACTOR[m.group(2)]
        return int(round(int(m.group(1)) * f)), unit
    m = re.search(r"\b(\d+)\s*(?:buc|bucati)\b", s) or re.search(r"\*\s*(\d+)\b", s)
    if m:
        return int(m.group(1)), "buc"
    if re.search(r"(?:\bkg|\bvrac)\s*$|/\s*kg\b|\bla kg\b|\bper kg\b", s):  # sold by weight: the price is per kg
        return 1000, "g"
    return None


def priced_per_piece(size, price_bani, cheap: int = 35) -> bool:
    """A pack of N pieces whose price is under 0,35 lei a piece (eggs): the shop gave the price of one piece."""
    return bool(size) and size[1] == "buc" and size[0] > 1 and price_bani is not None and price_bani / size[0] < cheap


def portion_size(name: str):
    """One portion of a multipack ("100x10g" -> (10, "g")); None when the name has no NxM size."""
    m = re.search(r"(?<!cod )\b(\d+)\s*[x*]\s*" + _NUM + r"\s*(l|ml|kg|gr|g)\b", name.lower())
    if not m or int(m.group(1)) < 2:
        return None
    f, unit = _FACTOR[m.group(3)]
    return int(round(_num(m.group(2)) * f)), unit


def by_weight(name: str) -> bool:
    """Sold at the counter, priced per kg: "... vrac", "... kg" (no number before it), "/kg", "la kg", "per kg"."""
    return bool(re.search(r"(?:(?<![\d.,])\s+kg|\bvrac)\s*$|/\s*kg\b|\bla kg\b|\bper kg\b", name.lower()))
