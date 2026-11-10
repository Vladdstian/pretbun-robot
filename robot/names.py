"""Shop names -> comparable text, and the attributes item rules need (fat %, egg size and code, flour type).

Readers return a value only when the name is unambiguous: a missing attribute is better than a wrong one.
"""
from __future__ import annotations

import re
import unicodedata

_FAT_WORDS = {"gr", "grs", "gras", "grasime", "grasimi", "fat"}
_NOT_FAT = {"proteine", "protein", "cacao", "cocoa", "alcool", "alc", "vol", "zahar", "fructe", "carne", "suc", "si"}
_PCT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%\s*([a-z]*)")
_EGG_SIZES = {"s": "S", "m": "M", "l": "L", "xl": "XL"}


def _expand(words: list, abbrev: dict) -> list:
    """Replace abbreviations (one or more whole words, longest first)."""
    if not abbrev:
        return words
    keys = sorted((tuple(k.split()) for k in abbrev), key=len, reverse=True)
    out, i = [], 0
    while i < len(words):
        for k in keys:
            if tuple(words[i:i + len(k)]) == k:
                out += abbrev[" ".join(k)].split()
                i += len(k)
                break
        else:
            out.append(words[i])
            i += 1
    return out


def normalize(name: str, abbrev: dict = None) -> str:
    s = unicodedata.normalize("NFKD", (name or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))       # ș->s, ț->t, ă/â->a, î->i, ö->o
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)                           # 1,5 -> 1.5
    s = re.sub(r"\b(\d) (\d)%", r"\1.\2%", s)                        # "3 5%" (missing comma) -> 3.5%
    s = re.sub(r"\d\s*\+\s*\(?\s*\d\s*-\s*\d+(?:\.\d+)?\s*%\s*\)?", " ", s)  # promo "1+(1-40%)", "1+1-50%"
    s = re.sub(r"(?:^|(?<=\s))[-+]\s*\d+(?:\.\d+)?\s*%", " ", s)     # discount "-20%", bonus "+ 10%"
    s = re.sub(r"([a-z])(\d)", r"\1 \2", s)                          # cio280g -> cio 280g, cod2 -> cod 2
    s = re.sub(r"%(?=\S)", "% ", s)                                  # 3.5%1000 -> 3.5% 1000
    s = re.sub(r"(\d)(ml|gr|g|kg)(?=[a-z]{3,})", r"\1\2 ", s)          # 500gboromir -> 500g boromir (the brand)
    s = re.sub(r"[^a-z0-9.%*\s]", " ", s)                            # punctuation -> space
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)                        # dots that aren't decimal points
    s = s.replace("*", " * ")                                        # oua*10 -> oua * 10
    return " ".join(_expand(s.split(), abbrev or {}))


def _fat(norm: str):
    found = [(float(m.group(1)), m.group(2)) for m in _PCT.finditer(norm)]
    marked = [v for v, w in found if w in _FAT_WORDS]
    if marked:
        return marked[0]
    if len(found) == 1 and found[0][1] not in _NOT_FAT:
        return found[0][0]
    return None  # none, or several without a fat word: don't guess


def attrs(norm: str) -> dict:
    """Attributes read from a normalized name; a key is present only when its value is certain."""
    out, words = {}, norm.split()
    fat = _fat(norm)
    if fat is not None:
        out["fat"] = int(fat) if fat == int(fat) else fat
    if "oua" in words:
        tokens = re.split(r"[\s*]+", norm)
        sizes = {_EGG_SIZES[t] for i, t in enumerate(tokens) if t in _EGG_SIZES   # "1 l" would be litres,
                 and not (i and re.fullmatch(r"\d+(?:\.\d+)?", tokens[i - 1])     # but "cod 2 l" is code 2, size L
                          and not (i > 1 and tokens[i - 2] == "cod"))}
        if len(sizes) == 1:
            out["egg"] = sizes.pop()
        m = re.search(r"\bcod\s*([0-3])\b", norm)
        if m:
            out["code"] = int(m.group(1))
    if "faina" in words:
        types = set(re.findall(r"\b(000|00|480|650|1250)\b", norm))
        if len(types) == 1:
            out["flour"] = types.pop()
        elif not types and "integrala" in words:
            out["flour"] = "integrala"
    return out
