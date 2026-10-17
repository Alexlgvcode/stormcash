"""Postgres access: a psycopg 3 pool and a few plain helpers. No ORM (§0 rule 4).

Use `with pool.connection() as conn:`; the block is one transaction that
commits on exit and rolls back on an exception. Rows come back as dicts.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus
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


@contextmanager
def pipelined(pool: ConnectionPool) -> Iterator[psycopg.Connection]:
    """One transaction in pipeline mode: statements whose results nobody reads
    yet don't wait for the server, so a transaction costs one round trip per
    point where the code needs a result (plus one at the end), not one per
    statement. That matters on a hosted database (~35 ms a round trip).

    psycopg waits for BEGIN's reply before it pipelines anything, so BEGIN and
    COMMIT go as plain statements on an autocommit connection. Inside the block,
    use conn.execute; don't open conn.transaction() (it can't see this one).
    Results of cursors not fetched inside the block can be read after it."""
    with pool.connection() as conn:
        conn.autocommit = True
        try:
            with conn.pipeline():
                conn.execute("BEGIN")
                yield conn
                conn.execute("COMMIT")
        except BaseException:
            if not conn.closed and conn.info.transaction_status != TransactionStatus.IDLE:
                try:
                    conn.execute("ROLLBACK")
                except psycopg.Error:
                    pass  # closed below
            raise
        finally:
            if not conn.closed:
                if conn.info.transaction_status == TransactionStatus.IDLE:
                    conn.autocommit = False
                else:
                    conn.close()  # unknown state: the pool replaces a closed connection


def one(conn: psycopg.Connection, sql: str, params: Sequence[Any] | dict | None = None) -> dict | None:
    return conn.execute(sql, params).fetchone()


def all_rows(conn: psycopg.Connection, sql: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
    return conn.execute(sql, params).fetchall()


def scalar(conn: psycopg.Connection, sql: str, params: Sequence[Any] | dict | None = None) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else next(iter(row.values()))
