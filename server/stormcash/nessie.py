"""Capital One Nessie (spec §11.4, verified v4.2).

- Amounts are whole dollars: `cents_to_dollars` is the only conversion and it
  refuses anything that isn't a whole dollar.
- Money moves as a matched pair: a `completed` withdrawal on the source and a
  `completed` deposit on the destination, both described "SC <txn_id> <summary>".
- Every call is logged to `nessie_calls`; writes are also published as
  `nessie_call` SSE events.
- Fallback: a movement is first written to `nessie_moves` as `queued` inside the
  business transaction, then executed. If Nessie fails, the replay loop retries
  every 10 s and creates only the missing half (found by txn_id in the
  description). A move is `executed` only when both records exist.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
import uuid
from typing import Any

import httpx
import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .db import all_rows
from .sse import Broker

log = logging.getLogger(__name__)

TIMEOUT_S = 3.0
BALANCE_CACHE_S = 10.0
# Customers need an address; the sandbox accepts any strings.
DEMO_ADDRESS = {
    "street_number": "1",
    "street_name": "Patton Ave",
    "city": "Asheville",
    "state": "NC",
    "zip": "28801",
}


class NessieError(RuntimeError):
    pass


def cents_to_dollars(cents: int) -> int:
    """The single cents → Nessie dollars conversion (§0 rule 7). Never rounds."""
    if not isinstance(cents, int) or isinstance(cents, bool):
        raise TypeError("cents must be an int")
    if cents % 100 != 0:
        raise ValueError(f"{cents} cents is not a whole dollar amount")
    return cents // 100


def is_whole_dollars(cents: int) -> bool:
    return cents % 100 == 0


def description(txn_id: uuid.UUID, summary: str) -> str:
    return f"SC {txn_id} {summary}"


class NessieClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        pool: ConnectionPool,
        events: Broker,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self._pool = pool
        self._events = events
        self._http = httpx.Client(base_url=base_url, timeout=TIMEOUT_S, transport=transport)
        self._balance_cache: dict[str, tuple[float, int]] = {}
        self._cache_lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    # Raw calls ------------------------------------------------------------------

    def _call(self, method: str, path: str, body: dict | None = None, summary: str | None = None) -> Any:
        status: int | None = None
        data: Any = None
        try:
            resp = self._http.request(method, path, params={"key": self._key}, json=body)
            status = resp.status_code
            try:
                data = resp.json()
            except ValueError:
                data = {"text": resp.text[:500]}
        except httpx.HTTPError as exc:
            data = {"error": type(exc).__name__}
            raise NessieError(f"{method} {path}: {type(exc).__name__}") from exc
        finally:
            self._log(method, path, body, status, data, summary)
        if status >= 400:
            raise NessieError(f"{method} {path}: HTTP {status}")
        return data

    def _log(self, method, path, body, status, data, summary) -> None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """INSERT INTO nessie_calls (method, path, request, status, response, summary)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                    (method, path, Jsonb(body), status, Jsonb(data), summary),
                ).fetchone()
        except psycopg.Error:
            log.exception("could not log Nessie call")
            return
        if method != "GET":
            self._events.publish("nessie_call", row)

    @staticmethod
    def _created_id(data: Any) -> str:
        try:
            return data["objectCreated"]["_id"]
        except (KeyError, TypeError) as exc:
            raise NessieError(f"unexpected Nessie response: {data!r}") from exc

    # Entities -------------------------------------------------------------------

    def create_customer(self, first_name: str, last_name: str) -> str:
        body = {"first_name": first_name, "last_name": last_name, "address": DEMO_ADDRESS}
        return self._created_id(
            self._call("POST", "/customers", body, f"Create customer {first_name} {last_name}")
        )

    def create_account(self, customer_id: str, nickname: str, balance_dollars: int) -> str:
        body = {"type": "Checking", "nickname": nickname, "rewards": 0, "balance": balance_dollars}
        return self._created_id(
            self._call(
                "POST", f"/customers/{customer_id}/accounts", body, f"Open account {nickname}, ${balance_dollars}"
            )
        )

    def get_account(self, account_id: str) -> dict:
        return self._call("GET", f"/accounts/{account_id}")

    def list_withdrawals(self, account_id: str) -> list[dict]:
        return self._call("GET", f"/accounts/{account_id}/withdrawals")

    def list_deposits(self, account_id: str) -> list[dict]:
        return self._call("GET", f"/accounts/{account_id}/deposits")

    def _record(self, kind: str, account_id: str, dollars: int, desc: str, summary: str) -> str:
        body = {
            "medium": "balance",
            "transaction_date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
            "status": "completed",
            "amount": dollars,
            "description": desc,
        }
        new_id = self._created_id(self._call("POST", f"/accounts/{account_id}/{kind}", body, summary))
        with self._cache_lock:
            self._balance_cache.pop(account_id, None)
        return new_id

    def withdraw(self, account_id: str, dollars: int, desc: str, summary: str) -> str:
        return self._record("withdrawals", account_id, dollars, desc, summary)

    def deposit(self, account_id: str, dollars: int, desc: str, summary: str) -> str:
        return self._record("deposits", account_id, dollars, desc, summary)

    def balance_cents(self, account_id: str) -> int:
        """Opening balance + Σ deposits − Σ withdrawals, cached ≤ 10 s (§11.4)."""
        now = time.monotonic()
        with self._cache_lock:
            hit = self._balance_cache.get(account_id)
        if hit and now - hit[0] < BALANCE_CACHE_S:
            return hit[1]
        opening = self.get_account(account_id)["balance"]
        deposits = sum(d["amount"] for d in self.list_deposits(account_id))
        withdrawals = sum(w["amount"] for w in self.list_withdrawals(account_id))
        cents = round((opening + deposits - withdrawals) * 100)
        with self._cache_lock:
            self._balance_cache[account_id] = (now, cents)
        return cents


class MoneyMover:
    """Executes and replays queued `nessie_moves` rows."""

    def __init__(self, pool: ConnectionPool, nessie: NessieClient | None, events: Broker | None = None) -> None:
        self._pool = pool
        self._nessie = nessie
        self._events = events
        self.on_payout_executed = None  # callback(payout_id), e.g. the Photon settled notice

    @staticmethod
    def queue(
        conn: psycopg.Connection,
        txn_id: uuid.UUID,
        from_account_id: str,
        to_account_id: str,
        cents: int,
        summary: str,
        payout_id: int | None = None,
    ) -> None:
        """Record a whole-dollar movement to execute after the caller commits."""
        cents_to_dollars(cents)
        conn.execute(
            """INSERT INTO nessie_moves (txn_id, from_account_id, to_account_id, amount_cents, summary, payout_id, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'queued')""",
            (txn_id, from_account_id, to_account_id, cents, summary, payout_id),
        )

    def execute(self, txn_id: uuid.UUID) -> bool:
        """Create whichever half of the pair is missing. True once both exist."""
        if self._nessie is None:
            return False
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM nessie_moves WHERE txn_id = %s FOR UPDATE SKIP LOCKED", (txn_id,)
            ).fetchone()
            if row is None:  # another worker holds it
                return False
            if row["status"] == "executed":
                return True
            done = self._execute_row(conn, row)
        if done and self._events is not None:
            # Hint for the Accounts tab to refetch balances (§12.3 `accounts`).
            self._events.publish("accounts", {"changed": [row["from_account_id"], row["to_account_id"]],
                                              "txn_id": str(txn_id)})
        if done and row["payout_id"] is not None and self.on_payout_executed is not None:
            self.on_payout_executed(row["payout_id"])
        return done

    def _execute_row(self, conn: psycopg.Connection, row: dict) -> bool:
        nessie = self._nessie
        txn_id = row["txn_id"]
        desc = description(txn_id, row["summary"])
        dollars = cents_to_dollars(row["amount_cents"])
        retry = row["attempts"] > 0
        withdrawal_id, deposit_id = row["withdrawal_id"], row["deposit_id"]
        try:
            if withdrawal_id is None and retry:
                withdrawal_id = _find(nessie.list_withdrawals(row["from_account_id"]), txn_id)
            if withdrawal_id is None:
                withdrawal_id = nessie.withdraw(
                    row["from_account_id"], dollars, desc, f"{row['summary']}, ${dollars} (withdrawal)"
                )
            if deposit_id is None and retry:
                deposit_id = _find(nessie.list_deposits(row["to_account_id"]), txn_id)
            if deposit_id is None:
                deposit_id = nessie.deposit(
                    row["to_account_id"], dollars, desc, f"{row['summary']}, ${dollars} (deposit)"
                )
        except NessieError as exc:
            log.warning("Nessie move %s queued: %s", txn_id, exc)
        executed = withdrawal_id is not None and deposit_id is not None
        conn.execute(
            """UPDATE nessie_moves SET withdrawal_id = %s, deposit_id = %s, attempts = attempts + 1,
                      status = %s, updated_at = now() WHERE txn_id = %s""",
            (withdrawal_id, deposit_id, "executed" if executed else "queued", txn_id),
        )
        if executed and row["payout_id"] is not None:
            conn.execute(
                "UPDATE payouts SET status = 'executed', nessie_transfer_id = %s WHERE payout_id = %s",
                (deposit_id, row["payout_id"]),
            )
        return executed

    def replay_queued(self, limit: int = 20) -> int:
        """Retry queued moves (oldest first). Returns how many are now executed."""
        if self._nessie is None:
            return 0
        with self._pool.connection() as conn:
            ids = [
                r["txn_id"]
                for r in all_rows(
                    conn,
                    "SELECT txn_id FROM nessie_moves WHERE status = 'queued' ORDER BY created_at LIMIT %s",
                    (limit,),
                )
            ]
        return sum(1 for txn_id in ids if self.execute(txn_id))


def _find(records: list[dict], txn_id: uuid.UUID) -> str | None:
    prefix = f"SC {txn_id}"
    for r in records:
        if str(r.get("description", "")).startswith(prefix):
            return r["_id"]
    return None
