"""Dr. Max online prices from the Wayback Machine's copies of drmax.ro (its own site turns robots away).
Each archived category page carries the products' current price, regular price and lowest price in the last 30 days."""
from __future__ import annotations

from .. import channels
from . import archive
from .drmax_nuxt import products


def _parse(html):
    return [(p["sku"], p["name"], p["brand"], p["price"], p["regular"], p["low30"]) for p in products(html)]


def run(conn, web, today: int, cap: int = channels.DAILY_CAP) -> dict:
    return archive.run(conn, web, today, "www.drmax.ro", _parse, ("Dr. Max", "https://www.drmax.ro"), "drmax",
                       "drmax_archive_last", cap)
