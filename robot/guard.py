"""Free-plan guard: before each robot run, compare usage with the free limits. Warn at 75%, stop at 90%.

python3 -m robot.guard --r2-size "12.3 MB" --d1-json d1.json --gh-minutes 340 --report guard.md
Exit 0 = fine, 10 = warn (the run continues and an issue emails you), 20 = stop (the run skips Cloudflare entirely).
"""
from __future__ import annotations

import argparse
import json
import re

# free limits, in decimal units as Cloudflare quotes them; GitHub's 2,000 minutes are per month for private repos
LIMITS = {
    "r2_bytes": (10 * 10**9, "R2 storage"),
    "d1_bytes": (5 * 10**9, "D1 storage"),
    "d1_written": (100_000, "D1 rows written in the last 24 h"),
    "d1_read": (5_000_000, "D1 rows read in the last 24 h"),
    "gh_minutes": (2_000, "GitHub Actions minutes this month"),
}
WARN, STOP = 0.75, 0.90
EXIT = {"ok": 0, "warn": 10, "stop": 20}
_UNITS = {"b": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12,
          "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40}


def parse_size(text: str) -> int:
    """'12.3 MB' (as wrangler prints a bucket's size) -> bytes."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([kmgt]?i?b)\s*", text or "", re.I)
    if not m:
        raise ValueError("unreadable size: %r" % text)
    return int(round(float(m.group(1)) * _UNITS[m.group(2).lower()]))


def measure(usage: dict) -> list:
    """(name, value, limit, share, level) for every value we could read; None = unknown, skipped."""
    rows = []
    for name, value in usage.items():
        if value is None:
            continue
        limit = LIMITS[name][0]
        share = value / limit
        rows.append((name, value, limit, share, "stop" if share >= STOP else "warn" if share >= WARN else "ok"))
    return rows


def verdict(rows: list) -> str:
    levels = {r[4] for r in rows}
    return "stop" if "stop" in levels else "warn" if "warn" in levels else "ok"


def _fmt(name: str, n: int) -> str:
    if name.endswith("bytes"):
        return "%.1f MB" % (n / 10**6) if n < 10**9 else "%.2f GB" % (n / 10**9)
    return "{:,}".format(n)


def report(rows: list, problems: list, level: str) -> str:
    lines = ["**Free limits check: %s** (warn at 75%%, stop at 90%%)" % level.upper(), "",
             "| | Used | Free limit | Share |", "|---|---|---|---|"]
    for name, value, limit, share, lvl in sorted(rows, key=lambda r: -r[3]):
        pct = "%d%%" % int(share * 100)
        lines.append("| %s | %s | %s | %s |" % (LIMITS[name][1], _fmt(name, value), _fmt(name, limit),
                                                "**%s**" % pct if lvl != "ok" else pct))
    lines += ["- could not measure: %s" % p for p in problems]
    lines += ["", "At 75% the robot keeps running and this issue warns you; at 90% it skips everything that uses "
              "Cloudflare until usage drops, so nothing can ever be billed."]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check usage against the free limits")
    ap.add_argument("--r2-size", help="bucket_size as printed by `wrangler r2 bucket info`")
    ap.add_argument("--d1-json", help="output of `wrangler d1 info <db> --json`")
    ap.add_argument("--gh-minutes", type=int, help="billable GitHub Actions minutes this month")
    ap.add_argument("--report", help="write the report (Markdown) here")
    args = ap.parse_args(argv)
    usage, problems = {}, []
    if args.r2_size is not None:
        try:
            usage["r2_bytes"] = parse_size(args.r2_size)
        except ValueError as e:
            problems.append(str(e))
    if args.d1_json:
        try:
            with open(args.d1_json, encoding="utf-8") as f:
                d = json.load(f)
            usage.update(d1_bytes=d["database_size"], d1_written=d["rows_written_24h"], d1_read=d["rows_read_24h"])
        except (OSError, ValueError, KeyError) as e:
            problems.append("D1 info: %s" % e)
    if args.gh_minutes is not None:
        usage["gh_minutes"] = args.gh_minutes
    rows = measure(usage)
    level = verdict(rows)
    if problems and level == "ok":
        level = "warn"  # never block the robot over a number we could not read, but say so
    text = report(rows, problems, level)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return EXIT[level]


if __name__ == "__main__":
    raise SystemExit(main())
