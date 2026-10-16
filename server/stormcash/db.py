"""Postgres access: a psycopg 3 pool and a few plain helpers. No ORM (§0 rule 4).

Use `with pool.connection() as conn:`; the block is one transaction that
commits on exit and rolls back on an exception. Rows come back as dicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def make_pool(url: str, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    pool = ConnectionPool(
        url,
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    pool.open(wait=True, timeout=15)
    return pool


def one(conn: psycopg.Connection, sql: str, params: Sequence[Any] | dict | None = None) -> dict | None:
    return conn.execute(sql, params).fetchone()


def all_rows(conn: psycopg.Connection, sql: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
    return conn.execute(sql, params).fetchall()


def scalar(conn: psycopg.Connection, sql: str, params: Sequence[Any] | dict | None = None) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else next(iter(row.values()))
