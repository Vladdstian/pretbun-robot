"""Products and subcategory slugs in a Freshful page's __NEXT_DATA__ JSON.
Written by the local model from tasks/local/freshful-next.md (passed on the first try); reviewed by Claude."""
import json
import re


def _data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def products(html):
    data = _data(html)
    if data is None:
        return []

    seen_skus = set()
    result = []

    for d in _walk(data):
        if "sku" not in d or "price" not in d:
            continue

        price = _num(d["price"])
        if price is None or price <= 0:
            continue

        sku = str(d["sku"])
        if sku in seen_skus:
            continue
        seen_skus.add(sku)

        result.append({
            "sku": sku,
            "name": d.get("name"),
            "brand": d.get("brand"),
            "price": price,
            "original": _num(d.get("originalPrice")),
            "unit_label": d.get("unitPriceLabel")
        })

    return result


def categories(html):
    data = _data(html)
    if data is None:
        return []

    seen_slugs = set()
    result = []

    for d in _walk(data):
        v = d.get("slug")
        if not isinstance(v, str):
            continue

        if not re.fullmatch(r"\d{1,6}-[a-z0-9-]+", v):
            continue

        if v in seen_slugs:
            continue
        seen_slugs.add(v)

        result.append(v)

    return result
