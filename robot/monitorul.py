"""Client and parsers for Monitorul Prețurilor (Consiliul Concurenței). Undocumented API: parse strictly, fail loudly."""
from __future__ import annotations

import functools
import gzip
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .db import day_number, to_bani

NS = "{http://schemas.datacontract.org/2004/07/pmonsvc.Models.Protos}"
USER_AGENT = "PretBun-robot/0.1 (family project)"
BATCH = 200
MAX_RADIUS_M = 5000  # the service silently returns no stores above this (measured 2026-11-09)
CERTS = os.path.join(os.path.dirname(__file__), "certs", "monitorul-chain.pem")


def ssl_context() -> ssl.SSLContext:
    """The system's trust store plus the intermediates the site forgets to send (see certs/monitorul-chain.pem)."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=CERTS)
    return ctx


@dataclass
class Store:
    id: int
    chain_key: str
    name: str
    address: str
    lat: float
    lon: float
    type: int


@dataclass
class Obs:
    store_id: int
    product_id: int
    name: str
    brand: str
    price_bani: Optional[int]  # None = not sold (explicit 0.00 in a complete answer)
    promo: int
    day: Optional[int]
    cat_id: Optional[int] = None  # the official category ("FLOAREA SOARELUI"), the same for every shop
    cat_name: str = ""
    odd: bool = False  # the shop's own name describes another product: its price is not this product's


def _words(text: str) -> list:
    return [w for w in re.findall(r"[a-z]+", unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode())]


def same_product(official: str, shop: str) -> bool:
    """False only when the two names share no word: the same word of 3+ letters, or the same first 4 letters
    ("Batoane" ~ "BATON", "Esenta" ~ "Esente"); some shops price their own product under another product's number."""
    ours, theirs = [w for w in _words(official) if len(w) >= 3], [w for w in _words(shop) if len(w) >= 3]
    if not ours or not theirs:
        return True  # nothing to compare
    near = lambda w, t: w == t or (len(w) >= 4 and len(t) >= 4 and w[:4] == t[:4])
    glued = lambda words, other: any(len(w) >= 4 and w[:4] in "".join(other) for w in words)  # "KITKAT" ~ "KIT KAT"
    return any(near(w, t) for w in ours for t in theirs) or glued(ours, _words(shop)) or glued(theirs, _words(official))


@dataclass
class CatalogProduct:
    id: int
    name: str
    category_id: Optional[int]


def _root(xml: bytes, expected: str) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError("bad XML from Monitorul: %s" % e) from e
    if root.tag != NS + expected:
        raise ValueError("unexpected answer from Monitorul: <%s>" % root.tag)
    return root


def _text(el: ET.Element, path: str) -> str:
    node = el.find("/".join(NS + p for p in path.split("/")))
    return (node.text or "").strip() if node is not None else ""


def _day(pricedate: str) -> Optional[int]:
    if not pricedate:
        return None
    d, mth, y = pricedate[:10].split(".")
    return day_number(date(int(y), int(mth), int(d)))


def parse_networks(xml: bytes) -> dict:
    root = _root(xml, "RetailNetworks")
    return {_text(n, "Id"): _text(n, "Name") for n in root.iter(NS + "RetailNetwork")}


def parse_categories(xml: bytes) -> list:
    items = _root(xml, "CatalogProductCategories").find(NS + "Items")
    out = []
    for c in list(items) if items is not None else []:
        parent = _text(c, "ParentId")
        out.append((int(_text(c, "Id")), _text(c, "Name"), int(parent) if parent else None))
    return out


def parse_catalog(xml: bytes) -> list:
    root = _root(xml, "CatalogProducts")
    out = []
    for p in root.iter(NS + "CatalogProduct"):
        cat = _text(p, "Prodcateg/Id")
        out.append(CatalogProduct(int(_text(p, "Id")), _text(p, "Name"), int(cat) if cat else None))
    return out


def parse_stores_with_prices(xml: bytes):
    root = _root(xml, "RetailStores")
    items = root.find(NS + "Items")
    stores, obs = [], {}
    for s in list(items) if items is not None else []:
        sid = int(_text(s, "Id"))
        stores.append(Store(sid, _text(s, "Retailnetwork/Id"), _text(s, "Name"), _text(s, "Addr/Addrstring"),
                            float(_text(s, "Addr/Location/Lat")), float(_text(s, "Addr/Location/Lon")),
                            int(_text(s, "Type/Id") or 3)))
        for p in s.iter(NS + "Product"):
            pid = int(_text(p, "Catprod/Id"))
            price = float(_text(p, "Price") or 0)
            official, cat = _text(p, "Catprod/Name"), _text(p, "Catprod/Prodcateg/Id")
            o = Obs(sid, pid, official or _text(p, "Name"), _text(p, "Brand"),
                    to_bani(_text(p, "Price")) if price > 0 else None, 1 if _text(p, "Promo") else 0,
                    _day(_text(p, "Pricedate")), int(cat) if cat.isdigit() else None, _text(p, "Catprod/Prodcateg/Name").strip(),
                    not same_product(official, _text(p, "Name")))
            old = obs.get((sid, pid))
            # the same product twice in one store: the lowest price wins
            if old is None or (o.price_bani is not None and (old.price_bani is None or o.price_bani < old.price_bani)):
                obs[(sid, pid)] = o
    return stores, list(obs.values())


class Client:
    def __init__(self, base: str = "https://monitorulpreturilor.info/pmonsvc/Retail", min_interval: float = 1.0,
                 raw_dir: Optional[str] = None, opener=None, sleep=time.sleep):
        self.base, self.min_interval, self.raw_dir = base, min_interval, raw_dir
        self.opener = opener or functools.partial(urllib.request.urlopen, context=ssl_context())
        self.sleep, self._last, self._n = sleep, 0.0, 0

    def get(self, path: str) -> bytes:
        for attempt, wait in enumerate((2, 4, 8, None)):
            gap = self.min_interval - (time.monotonic() - self._last)
            if gap > 0:
                self.sleep(gap)
            self._last = time.monotonic()
            req = urllib.request.Request(self.base + path, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            try:
                with self.opener(req, timeout=120) as r:
                    data = r.read()
                    if (r.headers.get("Content-Encoding") or "") == "gzip":
                        data = gzip.decompress(data)
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 or wait is None:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if wait is None:
                    raise
            self.sleep(wait)
        if self.raw_dir:
            self._n += 1
            os.makedirs(self.raw_dir, exist_ok=True)
            with open(os.path.join(self.raw_dir, "%04d.xml" % self._n), "wb") as f:
                f.write(data)
        return data

    def networks(self) -> dict:
        return parse_networks(self.get("/GetRetailNetworks"))

    def categories(self) -> list:
        return parse_categories(self.get("/GetProductCategoriesNetwork"))

    def catalog(self, category_id: int) -> list:
        return parse_catalog(self.get("/GetCatalogProductsByNameNetwork?CSVcategids=%d" % category_id))

    def chain_catalog(self, chain_key: str, categories=None) -> list:
        """Every product one chain sells, in a single request (Penny ~5,700, Kaufland ~10,400 in Nov 2026)."""
        q = {"chain": chain_key}
        if categories:
            q["CSVcategids"] = ",".join(str(c) for c in categories)
        return parse_catalog(self.get("/GetCatalogProductsByNameNetwork?" + urllib.parse.urlencode(q, safe=",")))

    def stores_prices(self, lat: float, lon: float, radius_m: int, product_ids: list, chain_key: str):
        """Prices for product_ids in this chain's stores within radius_m. Returns (stores, obs, capped)."""
        if not product_ids:
            raise ValueError("Monitorul needs product ids in every store search (it answers 404 without them)")
        if radius_m > MAX_RADIUS_M:
            raise ValueError("Monitorul returns no stores above 5 km (asked %d m); cover a bigger area with several "
                             "areas of at most 5 km" % radius_m)
        stores, obs, capped = {}, [], False
        for i in range(0, len(product_ids), BATCH):
            q = urllib.parse.urlencode({"lat": lat, "lon": lon, "buffer": radius_m, "csvnetworkids": chain_key,
                                        "csvprodids": ",".join(str(p) for p in product_ids[i:i + BATCH])}, safe=",")
            st, ob = parse_stores_with_prices(self.get("/GetStoresForProductsByLatLon?" + q))
            capped = capped or len(st) >= 50  # the API returns at most 50 stores
            for s in st:
                stores[s.id] = s
            obs.extend(ob)
        return list(stores.values()), obs, capped
