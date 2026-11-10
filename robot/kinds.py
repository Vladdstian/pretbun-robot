"""General kinds learned from the data (asked 2026-11-10: "Șuncă de curcan, the rest under that general name").

The catalog's hand-written items cover only the staples. For every other product, the name without its brand, size and
filler words starts with the kind ("sunca de curcan feliata 100g fox" -> "sunca de curcan"). When enough products of
the same official category share that start, it becomes a kind of its own.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# words that say how it is packed or sold, never what it is
FILLER = set("""feliat feliata feliate vrac kg gastro ambalat ambalata atm vid punga caserola tava bax pet doza sticla
cutie borcan buc bucata bucati set pachet promo oferta nou noua extra premium clasic clasica traditional traditionala
superior superioara fa cu ia cu/ia aprox pret sgr pv dz act bio eco organic ecologic ecologica uht""".split())
JOIN = {"de", "din", "cu", "si", "in", "la", "pentru", "fara"}
# common words, written with their diacritics for the kind's name
PRETTY = {"sunca": "șuncă", "branza": "brânză", "paine": "pâine", "piine": "pâine", "carnati": "cârnați", "muschi": "mușchi",
          "pastrama": "pastramă", "slanina": "slănină", "smantana": "smântână", "faina": "făină", "malai": "mălai",
          "zahar": "zahăr", "salata": "salată", "rosii": "roșii", "castraveti": "castraveți", "ceapa": "ceapă",
          "varza": "varză", "ciuperci": "ciuperci", "masline": "măsline", "mazare": "mazăre", "fasole": "fasole",
          "porc": "porc", "vita": "vită", "oaie": "oaie", "capra": "capră", "telemea": "telemea", "cascaval": "cașcaval",
          "iaurt": "iaurt", "napolitane": "napolitane", "ciocolata": "ciocolată", "bauturi": "băuturi", "apa": "apă",
          "minerala": "minerală", "plata": "plată", "suc": "suc", "cafea": "cafea", "ceai": "ceai", "macinata": "măcinată",
          "taitei": "tăiței", "paste": "paste", "biscuiti": "biscuiți", "covrigi": "covrigi", "carne": "carne",
          "tocata": "tocată", "afumat": "afumat", "afumata": "afumată", "pui": "pui", "curcan": "curcan", "rata": "rață",
          "peste": "pește", "somon": "somon", "pastrav": "păstrăv", "crap": "crap", "ton": "ton", "pate": "pateu",
          "ficat": "ficat", "inghetata": "înghețată", "dulceata": "dulceață", "miere": "miere", "otet": "oțet",
          "mustar": "muștar", "maioneza": "maioneză", "ketchup": "ketchup", "sos": "sos", "spanac": "spanac",
          "dovlecei": "dovlecei", "vinete": "vinete", "cartofi": "cartofi", "morcovi": "morcovi", "mere": "mere",
          "pere": "pere", "struguri": "struguri", "lamai": "lămâi", "portocale": "portocale", "banane": "banane",
          "detergent": "detergent", "sapun": "săpun", "hartie": "hârtie", "igienica": "igienică", "sampon": "șampon",
          "crenvursti": "crenvurști", "parizer": "parizer", "salam": "salam", "alba": "albă", "neagra": "neagră",
          "verde": "verde", "rosie": "roșie", "dulce": "dulce", "sarat": "sărat", "sarata": "sărată", "proaspat": "proaspăt",
          "proaspata": "proaspătă", "congelat": "congelat", "congelata": "congelată", "maslinе": "măsline", "nuca": "nucă",
          "alune": "alune", "migdale": "migdale", "seminte": "semințe", "floarea": "floarea", "soarelui": "soarelui",
          "dovleac": "dovleac", "branzica": "brânzică", "budinca": "budincă", "prajitura": "prăjitură", "tort": "tort",
          "cozonac": "cozonac", "chec": "chec", "piept": "piept", "pulpe": "pulpe", "pulpa": "pulpă", "aripi": "aripi",
          "ceafa": "ceafă", "cotlet": "cotlet", "coaste": "coaste", "fructe": "fructe", "legume": "legume", "mix": "mix",
          "bautura": "băutură", "blonda": "blondă", "bruna": "brună", "rosu": "roșu", "topita": "topită", "prajita": "prăjită",
          "padure": "pădure", "fructata": "fructată", "macinat": "măcinat", "solutie": "soluție", "vaca": "vacă",
          "ochelari": "ochelari", "sapunul": "săpunul", "gris": "griș", "orez": "orez", "mamaliga": "mămăligă", "sare": "sare", "mici": "mici",
          "umpluta": "umplută", "cremoasa": "cremoasă", "zacusca": "zacuscă", "napolitana": "napolitană", "ciorba": "ciorbă"}

_DIGIT = re.compile(r"\d")


def kind_words(norm: str, brand_words: set, leading: frozenset = frozenset()) -> list:
    """The words that say what it is: no brand, no size, no packing words; joins ("de", "cu") only between two words.
    `leading`: words known as brands elsewhere ("ariel", "colgate"), skipped only before the kind starts."""
    out = []
    for w in norm.split():
        if _DIGIT.search(w) or w in FILLER or w in brand_words or (len(w) < 3 and w not in JOIN) or (not out and w in leading):
            if out:  # the kind is the start of the name; a size or packing word ends it
                break
            continue
        out.append(w)
    while out and out[-1] in JOIN:
        out.pop()
    return out


def key_of(words: list) -> str:
    """The first two words that are not joins: "sunca de curcan feliata" -> "sunca curcan"."""
    core = [w for w in words if w not in JOIN]
    return " ".join(core[:2])


def pretty(phrase: str) -> str:
    text = " ".join(PRETTY.get(w, w) for w in phrase.split())
    return text[:1].upper() + text[1:]


def brand_starts(brand_names) -> frozenset:
    """The first word of every brand name (normalized), except the words that name a kind themselves ("pui", "lapte")."""
    out = set()
    for n in brand_names:
        w = (n or "").split()
        if w and len(w[0]) >= 3 and w[0] not in PRETTY and w[0] not in JOIN and w[0] not in BROAD:  # "Bere Ciuc": bere stays a kind word
            out.add(w[0])
    return frozenset(out)


# words too broad to be a kind alone: "Piept" needs "pui", "Sos" needs "tomate"
BROAD = set("""salata sos crema piept pulpe pulpa mix baton bautura ulei apa pasta paste glob set ornament spray solutie
gel cutie punga file fructe legume carne branza suc ceai cafea vin bere sirop tort""".split())


def middle_words(norms) -> Counter:
    """How often each word sits inside a name (not first, not last): kind words do ("danone iaurt natural"),
    brand words don't (first or last: "ariel detergent", "sunca curcan pikok")."""
    c = Counter()
    for n in norms:
        w = n.split()
        for x in w[1:-1]:
            c[x] += 1
    return c


def learn(rows, at_least: int = 5, min_sources: int = 2, leading: frozenset = frozenset(), middle: Counter = None) -> dict:
    """rows: (product id, category id, normalized name, brand words, set of chains selling it).
    -> {product id: (slug, name)} for products whose kind is shared by `at_least` products of one category, sold in at
    least `min_sources` chains (one shop's abbreviation or private range is not a kind)."""
    groups, phrases = defaultdict(list), defaultdict(Counter)
    for pid, cid, norm, brand_words, source in rows:
        words = kind_words(norm, brand_words, leading)
        key = key_of(words)
        if len(key.split()) < 1 or cid is None:
            continue
        groups[(cid, key)].append((pid, source))
        # the phrase as most products write it, "sunca de curcan" rather than "sunca curcan"
        core = [w for w in words if w not in JOIN][:2]
        end = words.index(core[-1]) + 1
        phrases[(cid, key)][" ".join(words[:end])] += 1
    out = {}
    for (cid, key), members in groups.items():
        chains = set().union(*(s for _, s in members))  # a kind is sold by more than one chain
        first, n_core = key.split()[0], len(key.split())
        if len(members) < at_least or len(chains) < min_sources or (n_core == 1 and first in BROAD) \
                or (middle is not None and first not in PRETTY and (middle[first] < 3 or len(first) < 4)):
            continue
        name = pretty(phrases[(cid, key)].most_common(1)[0][0])
        slug = "auto-" + key.replace(" ", "-")
        for pid, _ in members:
            out[pid] = (slug, name)
    return out
