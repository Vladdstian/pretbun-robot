"""The data-cleaning rules set on the admin page (README D6), downloaded before each run to daily/admin/settings.json.
Missing or broken file: the built-in values, so a run never depends on it."""
from __future__ import annotations

import json

DEFAULTS = {"factor": 10, "kind_products": 5, "kind_chains": 2, "hide_no_size": True, "show": []}
PATH = "daily/admin/settings.json"


def load(path: str = PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULTS)
    return {k: got.get(k, v) if isinstance(got.get(k, v), type(v)) or (k == "factor" and isinstance(got.get(k), (int, float))) else v
            for k, v in DEFAULTS.items()}
