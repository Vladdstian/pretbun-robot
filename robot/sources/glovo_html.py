"""Product tiles in a Glovo store page's Next.js payload.
Written by the local model from tasks/local/glovo-tiles.md (passed on the first try); reviewed by Claude."""
import json
import re


def num(v):
    """A price as float: numbers stay, "8,99" becomes 8.99, anything else (bool, None, junk) is None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def tiles(html):
    parts = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    if not parts:
        return []
    try:
        text = json.loads('"' + "".join(parts) + '"')
    except ValueError:
        return []
    dec = json.JSONDecoder()
    out, seen = [], set()
    for m in re.finditer(r'\{"type":"PRODUCT_TILE","data":', text):
        try:
            data, _ = dec.raw_decode(text, m.end())
        except ValueError:
            continue
        price = num(data.get("price"))
        if price is None or price <= 0:
            continue
        tid = str(data.get("id"))
        if tid in seen:
            continue
        seen.add(tid)
        promo = data.get("promotion") or {}
        if not isinstance(promo, dict):
            promo = {}
        out.append({"id": tid, "ext": str(data.get("externalId")), "name": data.get("name"), "price": price,
                    "promo_price": num(promo.get("price")), "percent": num(promo.get("percentage"))})
    return out
