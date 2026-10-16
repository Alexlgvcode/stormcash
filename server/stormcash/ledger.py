"""Double-entry ledger (spec §11.3). Every movement is one debit and one credit
under one txn_id. An account's balance is Σ debit − Σ credit, so money moving
into escrow is a debit on `escrow:<cert>` and a credit on `checking:<res>`.
"""

from __future__ import annotations

import uuid

import psycopg

from .db import all_rows, scalar

POOL = "pool"
POOL_RECOVERIES = "pool_recoveries"


def checking(resident_id: uuid.UUID | str) -> str:
    return f"checking:{resident_id}"


def escrow(cert_id: bytes) -> str:
    return f"escrow:{cert_id.hex()}"


def merchant(merchant_id: bytes) -> str:
    return f"merchant:{merchant_id.hex()}"


def fraud_receivable(cert_id: bytes) -> str:
    return f"fraud_receivable:{cert_id.hex()}"


def post(
    conn: psycopg.Connection,
    debit: str,
    credit: str,
    cents: int,
    ref: str,
    txn_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Write one balanced pair and return its txn_id."""
    if cents <= 0:
        raise ValueError("ledger amounts are positive cents")
    txn_id = txn_id or uuid.uuid4()
    conn.execute(
        """INSERT INTO ledger_entries (txn_id, account, debit_cents, credit_cents, ref)
           VALUES (%s, %s, %s, 0, %s), (%s, %s, 0, %s, %s)""",
        (txn_id, debit, cents, ref, txn_id, credit, cents, ref),
    )
    return txn_id


def balance(conn: psycopg.Connection, account: str) -> int:
    return scalar(
        conn,
        "SELECT COALESCE(SUM(debit_cents - credit_cents), 0) AS b FROM ledger_entries WHERE account = %s",
        (account,),
    )


def unbalanced_txns(conn: psycopg.Connection) -> list[uuid.UUID]:
    """Invariant check: txn_ids whose debits and credits differ (should be none)."""
    rows = all_rows(
        conn,
        """SELECT txn_id FROM ledger_entries GROUP BY txn_id
           HAVING SUM(debit_cents) <> SUM(credit_cents)""",
    )
    return [r["txn_id"] for r in rows]
