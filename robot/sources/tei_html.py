"""Products in an archived Farmacia Tei category page (price box + add-to-cart button).
Written by the local model from tasks/local/tei-listing.md (passed on the first try); reviewed by Claude."""
import html as htmlmod
import re

BLOCK = re.compile(r'<div class="price-box">(.*?)</div>\s*<button[^>]*cd-add-to-cart([^>]*)>', re.S)
ATTR = re.compile(r'data-([a-z-]+)="([^"]*)"')
CURRENT = re.compile(r'class="regular-price">.*?(\d[\d.]*,\d{2})\s*LEI', re.S)
OLD = re.compile(r'class="old-price">.*?(\d[\d.]*,\d{2})\s*LEI', re.S)


def lei(text):
    """'1.099,50' -> 1099.5 (dots are thousands, the comma is the decimal point)."""
    return float(text.replace(".", "").replace(",", "."))


def products(page):
    seen_pids = set()
    result = []
    for m in BLOCK.finditer(page):
        box = m.group(1)
        attrs = dict(ATTR.findall(m.group(2)))
        cur = CURRENT.search(box)
        if cur is None:
            continue
        pid = attrs.get("pid")
        if not pid or pid in seen_pids:
            continue
        seen_pids.add(pid)
        old = OLD.search(box)
        result.append({"pid": pid, "name": htmlmod.unescape(attrs.get("product-name", "")),
                      "brand": htmlmod.unescape(attrs.get("product-brand", "")) or None, "price": lei(cur.group(1)),
                      "old": lei(old.group(1)) if old else None})
    return result
