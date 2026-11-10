"""Products in a Dr. Max page's __NUXT_DATA__ block (values are positions in one flat JSON array).
Written by the local model from tasks/local/drmax-nuxt.md (passed on the first try); reviewed by Claude."""
import json
import re

def products(html):
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(1))
    except ValueError:
        return []
    if not isinstance(arr, list):
        return []

    def val(obj, key):
        v = obj.get(key)
        if isinstance(v, bool):
            return None
        if isinstance(v, int) and 0 <= v < len(arr):
            return arr[v]
        return None

    seen_skus = set()
    result = []

    for p in arr:
        if not isinstance(p, dict):
            continue
        
        name_val = val(p, "name")
        if not isinstance(name_val, str):
            continue

        price_val = val(p, "finalPrice")
        if not isinstance(price_val, (int, float)) or isinstance(price_val, bool) or price_val <= 0:
            continue

        sku_val = val(p, "sku")
        if sku_val is None:
            continue

        if sku_val in seen_skus:
            continue
        
        seen_skus.add(sku_val)

        regular_val = val(p, "regularPrice")
        if not isinstance(regular_val, (int, float)) or isinstance(regular_val, bool):
            regular_val = None

        low30_val = val(p, "drmaxLowestPrice30")
        if not isinstance(low30_val, (int, float)) or isinstance(low30_val, bool):
            low30_val = None

        result.append({
            "sku": str(sku_val),
            "name": name_val,
            "brand": val(p, "brandName"),
            "price": price_val,
            "regular": regular_val,
            "low30": low30_val,
            "url_key": val(p, "urlKey"),
            "rx": val(p, "drmaxRxProduct") is True
        })

    return result
