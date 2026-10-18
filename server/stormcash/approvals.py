"""Operator decisions on StormDesk flags (spec §14.6). Deterministic: the agent
only proposed; a person approves, and this code does exactly what the table says.

| Action | Effect |
|---|---|
| hold_pool_payout | the shop's pool-funded payouts that haven't reached Nessie are held (ledger reversed, queued Nessie move cancelled); future pool money held (pool_eligible = false) |
| lower_merchant_limit | merchants.per_payment_limit_cents = action_params.limit_cents; new POLICY |
| freeze_cert | cert_status = frozen; new POLICY |
| dispatch_relay | a task "Send a relay to <region>" for the operator (no money, no messages) |
| none | nothing |

Every decision writes an `approvals` row and an `approval` SSE event.
"""

from __future__ import annotations

import time

from psycopg.types.json import Jsonb

from . import cases, ledger
from .db import all_rows, one, scalar
from .deps import Deps
from .settlement import _Ctx


class ApprovalError(ValueError):
    status = 400


class FlagNotFound(ApprovalError):
    status = 404


class AlreadyDecided(ApprovalError):
    status = 409


def _load_flag(conn, flag_id: int) -> dict:
    flag = one(conn, "SELECT * FROM flags WHERE flag_id = %s FOR UPDATE", (flag_id,))
    if flag is None:
        raise FlagNotFound(f"no flag {flag_id}")
    if flag["status"] != "open":
        raise AlreadyDecided(f"flag {flag_id} is {flag['status']}, not open")
    return flag


def _merchant(conn, flag: dict) -> dict:
    try:
        merchant = one(conn, "SELECT * FROM merchants WHERE merchant_id = %s", (bytes.fromhex(flag["subject_id"]),))
    except ValueError:
        merchant = None
    if merchant is None:
        raise ApprovalError(f"{flag['proposed_action']} needs a shop, but the flag's subject is {flag['subject_id']}")
    return merchant


def hold_pool_payouts(conn, merchant: dict) -> dict:
    """Hold the shop's pool money that hasn't reached Nessie yet, and all future pool money."""
    mid = bytes(merchant["merchant_id"])
    conn.execute("UPDATE merchants SET pool_eligible = FALSE WHERE merchant_id = %s", (mid,))
    rows = all_rows(
        conn,
        """SELECT o.payout_id, o.amount_cents, o.tag_hash, p.cert_id FROM payouts o JOIN payments p USING (tag_hash)
           WHERE o.merchant_id = %s AND o.source = 'pool' AND o.status IN ('queued', 'pending', 'ledger_only')
           FOR UPDATE OF o""",
        (mid,),
    )
    held = 0
    for r in rows:
        cert_id, cents = bytes(r["cert_id"]), r["amount_cents"]
        conn.execute("DELETE FROM nessie_moves WHERE payout_id = %s AND status = 'queued'", (r["payout_id"],))
        conn.execute("UPDATE payouts SET status = 'held' WHERE payout_id = %s", (r["payout_id"],))
        conn.execute("UPDATE payments SET status = 'held' WHERE tag_hash = %s", (r["tag_hash"],))
        # Undo the pool payout and the matching receivable: the pool hasn't paid, so the cheater owes it nothing yet.
        ledger.post(conn, ledger.POOL, ledger.merchant(mid), cents, "pool payout held")
        ledger.post(conn, ledger.POOL_RECOVERIES, ledger.fraud_receivable(cert_id), cents, "pool payout held")
        held += cents
    return {"action": "hold_pool_payout", "merchant": merchant["display_name"], "payouts_held": len(rows),
            "held_cents": held, "future_pool_payouts": "held"}


def decide(deps: Deps, flag_id: int, operator: str, approve: bool, note: str | None = None,
           now: int | None = None) -> dict:
    """Approve (run the action) or reject (nothing runs) an open flag."""
    now = int(time.time()) if now is None else now
    ctx = _Ctx(deps, b"", now, False)
    with deps.pool.connection() as conn:
        flag = _load_flag(conn, flag_id)
        if approve and not flag["citations_valid"]:
            raise ApprovalError("a flag with invalid citations can't be approved")
        params = (flag.get("agent_transcript") or {}).get("action_params") or {}
        action = flag["proposed_action"] if approve else None
        executed: dict = {"action": action or "none"}
        if action == "hold_pool_payout":
            executed = hold_pool_payouts(conn, _merchant(conn, flag))
        elif action == "lower_merchant_limit":
            merchant = _merchant(conn, flag)
            limit = params.get("limit_cents")
            if not isinstance(limit, int) or limit <= 0:
                raise ApprovalError("lower_merchant_limit needs a positive action_params.limit_cents")
            conn.execute("UPDATE merchants SET per_payment_limit_cents = %s WHERE merchant_id = %s",
                         (limit, merchant["merchant_id"]))
            policy = cases.publish_policy(ctx, conn)
            executed = {"action": action, "merchant": merchant["display_name"], "limit_cents": limit,
                        "policy_ver": policy.policy_ver}
        elif action == "freeze_cert":
            cert_id = bytes.fromhex(flag["subject_id"])
            if scalar(conn, "SELECT 1 FROM cert_status WHERE cert_id = %s", (cert_id,)) is None:
                raise ApprovalError(f"freeze_cert needs a cert, but the flag's subject is {flag['subject_id']}")
            cases.freeze_cert(ctx, conn, cert_id)
            executed = {"action": action, "cert_id": flag["subject_id"],
                        "policy_ver": scalar(conn, "SELECT max(policy_ver) FROM policy_versions")}
        elif action == "dispatch_relay":
            executed = {"action": action, "task": f"Send a relay to {flag['subject_id']}"}
        conn.execute("UPDATE flags SET status = %s WHERE flag_id = %s",
                     ("approved" if approve else "rejected", flag_id))
        approval = one(
            conn,
            """INSERT INTO approvals (flag_id, decision, operator, note, executed_actions)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (flag_id, "approve" if approve else "reject", operator, note, Jsonb(executed)),
        )
    for event, data in ctx.events:
        deps.events.publish(event, data)
    result = {"approval": approval, "flag_id": flag_id, "status": "approved" if approve else "rejected",
              "executed_actions": executed}
    deps.events.publish("approval", result)
    deps.events.publish("accounts", {"approval": flag_id})
    return result
