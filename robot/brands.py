"""A product's brand: the longest known alias found on word boundaries in its normalized name, else the brand the
shop reports. An alias starting with ^ counts only at the start of the name (brands that are ordinary words: Ferma)."""
from __future__ import annotations

import re

from .names import normalize


class BrandIndex:
    def __init__(self, brands: list):
        self.aliases = []   # (words, anchored, display), longest first
        self.known = {}     # normalized alias or display -> display, for shop-reported brands
        for display, aliases, _label in brands:
            for a in aliases:
                words = tuple(a.lstrip("^").split())
                self.aliases.append((words, a.startswith("^"), display))
                self.known[" ".join(words)] = display
            self.known[normalize(display)] = display
        self.aliases.sort(key=lambda x: -len(x[0]))

    def find(self, norm: str, reported: str = None):
        words = norm.split()
        for wanted, anchored, display in self.aliases:
            n = len(wanted)
            if any(tuple(words[i:i + n]) == wanted for i in ([0] if anchored else range(len(words) - n + 1))):
                return display
        clean = re.sub(r"^[\W_]+|[\W_]+$", "", reported or "").strip()  # "Crf***" -> "Crf", "(Vrac)" -> "Vrac"
        if clean and normalize(clean) not in JUNK_BRANDS and normalize(clean) not in NOT_BRANDS:
            return self.known.get(normalize(clean)) or clean.title()
        return None


# Values shops put in the brand field meaning "no brand" (seen 2026-11-10)
JUNK_BRANDS = {"none", "null", "keine markennr vorhanden", "mn int", "mn ext", "fara marca", "fara brand", "nespecificat", "n a"}

# Words shops put in the brand field that aren't brands, and generic words that would match half the shelf
NOT_BRANDS = {"vrac", "kg", "bio", "eco", "buc", "pet", "nou", "promo", "oferta", "diverse", "fara marca", "generic", "import"}


def learned_brands(counts, at_least: int = 3) -> dict:
    """[(brand as reported, products)] -> {normalized name: display}: brands seen on enough products to trust."""
    out = {}
    for display, n in counts:
        key = normalize(display)
        if n >= at_least and len(key) >= 3 and key not in NOT_BRANDS and any(c.isalpha() for c in key):
            out.setdefault(key, display.strip())
    return out


def find_learned(norm: str, known: dict):
    """A learned brand in the first or last two words of a name (where shops put the brand), longest first."""
    words = norm.split()
    for k in (3, 2, 1):
        spots = [i for i in range(len(words) - k + 1) if i <= 1 or i + k >= len(words) - 1]
        for i in spots:
            hit = known.get(" ".join(words[i:i + k]))
            if hit:
                return hit
    return None
