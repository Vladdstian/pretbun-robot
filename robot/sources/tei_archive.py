"""Farmacia Tei online prices from the Wayback Machine's copies (its robots.txt shuts out robots like ours, so we
never read its site). An archived category page shows each product's price and, on offers, the old price."""
from __future__ import annotations

from .. import channels
from . import archive
from .tei_html import products


def _parse(html):
    return [(p["pid"], p["name"], p["brand"], p["price"], p["old"], None) for p in products(html)]


def run(conn, web, today: int, cap: int = channels.DAILY_CAP) -> dict:
    return archive.run(conn, web, today, "comenzi.farmaciatei.ro", _parse,
                       ("Farmacia Tei", "https://comenzi.farmaciatei.ro"), "tei", "tei_archive_last", cap)
