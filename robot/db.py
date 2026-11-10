"""Database helpers: open the SQLite copy, convert money and dates, write rows and queue them for D1."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

EPOCH = date(2026, 1, 1)
SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def day_number(d: date) -> int:
    return (d - EPOCH).days


def day_to_date(n: int) -> date:
    return EPOCH + timedelta(days=n)


def to_bani(price) -> int:
    return int((Decimal(str(price)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def remove(conn: sqlite3.Connection, table: str, key: dict) -> None:
    """Delete rows locally and queue the same statement for D1 (deleting twice is harmless)."""
    sql = "DELETE FROM {} WHERE {}".format(table, " AND ".join("%s = %s" % (k, _sql_value(v)) for k, v in key.items()))
    conn.execute(sql)
    conn.execute("INSERT INTO outbox (sql) VALUES (?)", (sql,))


def new_id(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM %s" % table).fetchone()[0]


def brand_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM brands WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    bid = new_id(conn, "brands")
    write(conn, "brands", {"id": bid, "name": name})
    return bid


def write(conn: sqlite3.Connection, table: str, row: dict, replace: bool = False) -> None:
    """Insert a row locally and queue the identical statement for D1, so the two never drift."""
    cols = list(row)
    sql = "INSERT {}INTO {} ({}) VALUES ({})".format(
        "OR REPLACE " if replace else "", table, ", ".join(cols), ", ".join(_sql_value(row[c]) for c in cols))
    conn.execute(sql)
    conn.execute("INSERT INTO outbox (sql) VALUES (?)", (sql,))
