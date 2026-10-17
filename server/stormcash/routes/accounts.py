"""GET /v1/accounts (spec §12.1, §18.2) and GET /v1/health.

Balances of the real demo entities come live from Nessie (opening balance +
deposits − withdrawals, §11.4); the ledger is shown beside them. Simulated
entities are ledger-only and only appear as town totals.
GET /v1/accounts/reconcile checks the ledger against Nessie's records (reconcile.py).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request

from .. import ledger, reconcile
from ..db import all_rows, scalar
from ..deps import Deps
from ..jsonutil import jsonable
from ..nessie import NessieError
from ..protocol.objects import b64u_encode

router = APIRouter()


def _ledger_balances(conn) -> dict[str, int]:
    rows = all_rows(conn, "SELECT account, SUM(debit_cents - credit_cents) AS b FROM ledger_entries GROUP BY account")
    return {r["account"]: int(r["b"]) for r in rows}


def accounts_snapshot(deps: Deps) -> dict:
    with deps.pool.connection() as conn:
        residents = all_rows(
            conn,
            """SELECT r.*, (SELECT c.cert_id FROM certificates c WHERE c.resident_id = r.resident_id LIMIT 1) AS cert_id
               FROM residents r WHERE NOT r.simulated ORDER BY r.created_at""",
        )
        merchants = all_rows(conn, "SELECT * FROM merchants WHERE NOT simulated ORDER BY display_name")
        sim_merchants = [bytes(r["merchant_id"]) for r in
                         all_rows(conn, "SELECT merchant_id FROM merchants WHERE simulated")]
        sim_certs = [bytes(r["cert_id"]) for r in all_rows(
            conn, """SELECT DISTINCT c.cert_id FROM certificates c JOIN residents r ON r.resident_id = c.resident_id
                     WHERE r.simulated""")]
        balances = _ledger_balances(conn)
        unbalanced = ledger.unbalanced_txns(conn)
        queued = scalar(conn, "SELECT count(*) FROM nessie_moves WHERE status = 'queued'")

    cards = []
    for r in residents:
        name = r["display_name"]
        cards.append({"key": ledger.checking(r["resident_id"]), "label": f"{name} Checking", "kind": "checking",
                      "nessie_account_id": r["checking_account_id"]})
        if r["cert_id"] is not None:
            cards.append({"key": ledger.escrow(bytes(r["cert_id"])), "label": f"{name} Escrow", "kind": "escrow",
                          "nessie_account_id": r["escrow_account_id"]})
    for m in merchants:
        cards.append({"key": ledger.merchant(bytes(m["merchant_id"])), "label": m["display_name"], "kind": "merchant",
                      "nessie_account_id": m["nessie_account_id"]})
    cards.append({"key": ledger.POOL, "label": "Guarantee Pool", "kind": "pool",
                  "nessie_account_id": deps.settings.nessie_pool_account_id or None})

    def nessie_balance(card: dict) -> tuple[int | None, str | None]:
        if deps.nessie is None or not card["nessie_account_id"]:
            return None, None
        try:
            return deps.nessie.balance_cents(card["nessie_account_id"]), None
        except (NessieError, KeyError, TypeError) as exc:
            return None, str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(nessie_balance, cards))
    for card, (cents, error) in zip(cards, results, strict=True):
        card.update(nessie_cents=cents, nessie_error=error, ledger_cents=balances.get(card["key"], 0))

    totals: dict[str, int] = {}
    for account, cents in balances.items():
        kind = account.split(":", 1)[0]
        totals[kind] = totals.get(kind, 0) + cents
    return {
        "as_of": int(time.time()),
        "accounts": cards,
        "simulated_town": {
            "label": "Simulated town (ledger only)",
            "merchants": len(sim_merchants),
            "merchant_cents": sum(balances.get(ledger.merchant(m), 0) for m in sim_merchants),
            "escrow_cents": sum(balances.get(ledger.escrow(c), 0) for c in sim_certs),
        },
        "ledger": {"balanced": not unbalanced, "unbalanced_txns": len(unbalanced), "totals": totals},
        "nessie": {"enabled": deps.nessie is not None, "queued": queued},
    }


@router.get("/v1/accounts")
def get_accounts(request: Request) -> dict:
    return jsonable(accounts_snapshot(request.app.state.deps))


@router.get("/v1/accounts/reconcile")
def get_reconcile(request: Request) -> dict:
    """Our ledger against Nessie's own records, per real account (§11.4a). When
    Nessie can't be read, `last_ok_at` is the last check that read every account."""
    state = request.app.state
    result = reconcile.reconcile(state.deps)
    if result["ok"]:
        state.reconcile_last_ok_at = result["checked_at"]
    result["last_ok_at"] = getattr(state, "reconcile_last_ok_at", None)
    return jsonable(result)


@router.get("/v1/health")
def health(request: Request) -> dict:
    deps: Deps = request.app.state.deps
    with deps.pool.connection() as conn:
        conn.execute("SELECT 1")
    s = deps.settings
    return {
        "ok": True,
        "time": int(time.time()),
        "demo_mode": s.demo_mode,
        "nessie_enabled": deps.nessie is not None,
        "api_sig_required": s.api_sig_required,
        "server_pub": b64u_encode(s.server_pub),
        "public_base_url": s.public_base_url,
    }
