"""A product's brand: the longest known alias found on word boundaries in its normalized name, else the brand the
shop reports. An alias starting with ^ counts only at the start of the name (brands that are ordinary words: Ferma)."""
from __future__ import annotations

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
        if reported and reported.strip():
            return self.known.get(normalize(reported)) or reported.strip().title()
        return None
