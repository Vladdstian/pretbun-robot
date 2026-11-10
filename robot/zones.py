"""Price zones: stores of the same chain and format charge the same price; only stores that differ are stored apart."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# Store-format words in names, including the short forms seen in live data ("SG" = Mega Image Shop&Go, "EXPR").
FORMATS = {"express": "express", "expr": "express", "market": "market", "city": "city",
           "sg": "shopgo", "go": "shopgo", "shop": "shopgo", "atac": "atac"}  # ATAC: Auchan's discount format


def zone_key(store) -> str:
    words = re.findall(r"[a-z]+", store.name.lower())
    fmt = next((FORMATS[w] for w in words if w in FORMATS), "")
    return "%s|%d|%s" % (store.chain_key, store.type, fmt)


# Formats that are a different shop for the user, though the official data reports them under a parent network:
# they become their own chain in the app ("ATAC" is Auchan's discount format; the user wants it apart, 2026-11-09).
BANNERS = {"atac": "ATAC"}


def chain_of_store(store) -> tuple:
    """(chain key, chain name or None): 'AUCHAN|atac' / 'ATAC' for ATAC stores, else the network's own key."""
    fmt = zone_key(store).rsplit("|", 1)[1]
    return ("%s|%s" % (store.chain_key, fmt), BANNERS[fmt]) if fmt in BANNERS else (store.chain_key, None)


def network(chain_key: str) -> str:
    """The official network a chain is requested under: 'AUCHAN|atac' -> 'AUCHAN'."""
    return chain_key.split("|", 1)[0]


def split(obs: list, zone_of: dict, differ=frozenset(), current=None):
    """Zone value = most common price (ties -> lowest) among stores not already known to differ (`differ`: store,
    product pairs); if only such stores were checked, the zone keeps its `current` value. Every store that differs
    (incl. not selling) is an exception."""
    groups = defaultdict(list)
    for o in obs:
        groups[(zone_of[o.store_id], o.product_id)].append(o)
    zones, exceptions = {}, {}
    for key, lst in groups.items():
        usual = [o for o in lst if (o.store_id, o.product_id) not in differ]
        if not usual and current and key in current:
            zones[key] = current[key]  # e.g. only the representative store was checked, and it differs here
        else:
            usual = usual or lst
            counts = Counter(o.price_bani for o in usual if o.price_bani is not None)
            if counts:
                top = max(counts.values())
                price = min(p for p, c in counts.items() if c == top)
                zones[key] = (price, 1 if any(o.promo for o in usual if o.price_bani == price) else 0)
            else:
                zones[key] = (None, 0)
        for o in lst:
            if o.price_bani != zones[key][0]:
                exceptions[(o.store_id, o.product_id)] = (o.price_bani, o.promo if o.price_bani is not None else 0)
    return zones, exceptions


def pick_rep(stores_in_zone: list, obs_count: dict) -> int:
    return min(stores_in_zone, key=lambda s: (-obs_count.get(s, 0), s))
