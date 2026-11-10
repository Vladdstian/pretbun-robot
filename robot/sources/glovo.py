"""Glovo prices from its public store pages (featured products and promotions); see apps.py."""
from __future__ import annotations

from .. import channels
from . import apps
from .glovo_html import tiles

CITY = {"brasov": "brasov", "bucuresti": "bucharest"}  # Glovo's own city slugs (checked 2026-11-09)
read_apps = apps.read_apps


def _parse(html):
    out = []
    for t in tiles(html):
        offer = bool(t["promo_price"]) and t["promo_price"] < t["price"]
        out.append((t["ext"], t["name"], t["promo_price"] if offer else t["price"], t["price"] if offer else None))
    return out


def run(conn, web, today: int, areas: list, rows: list, cap: int = channels.DAILY_CAP) -> dict:
    return apps.run(conn, web, today, areas, rows, "glovo",
                    lambda area, store: "https://glovoapp.com/ro/ro/%s/stores/%s" % (CITY.get(area, area), store), _parse, cap)
