"""Demo reset (spec §12.1, §21.1): back to a clean table in seconds.

Clears everything the real phones did (payments, tags, cases, logs, contacts,
uploads, payouts, ledger and queued Nessie moves that touch a real entity),
opens fresh Nessie accounts so the Accounts tab starts from known numbers
(checking $500, escrow $0, shops $0), reissues each real resident a new
certificate with the $20 lock, and publishes a POLICY without the old certs.
The simulated town is untouched. The guarantee pool keeps its account.
"""

from __future__ import annotations

import time
import uuid

from . import cases, ledger, registry
from .db import all_rows
from .deps import Deps
from .nessie import NessieError
from .protocol import crypto
from .protocol.objects import Cert
from .settlement import _Ctx


def reset_demo(deps: Deps, storm_cap_cents: int | None = None, now: int | None = None) -> dict:
    started = time.monotonic()
    now = int(time.time()) if now is None else now
    with deps.pool.connection() as conn:
        residents = all_rows(conn, "SELECT * FROM residents WHERE NOT simulated ORDER BY created_at")
        merchants = all_rows(conn, "SELECT * FROM merchants WHERE NOT simulated ORDER BY display_name")

    # Fresh Nessie accounts first (outside the DB transaction): balances can't be
    # edited in Nessie, so a clean table means new accounts under the same customers.
    fresh: dict = {}
    if deps.nessie is not None:
        try:
            for r in residents:
                if r["nessie_customer_id"]:
                    name = r["display_name"]
                    fresh[r["resident_id"]] = (
                        deps.nessie.create_account(r["nessie_customer_id"], f"{name} Checking",
                                                   registry.CHECKING_OPENING_DOLLARS),
                        deps.nessie.create_account(r["nessie_customer_id"], f"{name} StormCash Escrow", 0),
                    )
            for m in merchants:
                if m["nessie_account_id"]:
                    customer = _customer_of(deps, m["nessie_account_id"])
                    if customer:
                        fresh[bytes(m["merchant_id"])] = deps.nessie.create_account(customer, m["display_name"], 0)
        except NessieError as exc:
            raise registry.Unavailable(f"Nessie unavailable ({exc}); retry, or set NESSIE_DISABLED=1") from exc

    certs: list[Cert] = []
    moves: list[uuid.UUID] = []
    ctx = _Ctx(deps, b"", now, False)
    with deps.pool.connection() as conn:
        old_certs = [bytes(r["cert_id"]) for r in all_rows(
            conn, "SELECT DISTINCT cert_id FROM certificates WHERE resident_id = ANY(%s)",
            ([r["resident_id"] for r in residents],))]
        merchant_ids = [bytes(m["merchant_id"]) for m in merchants]
        devices = [bytes(r["holder_pub"]) for r in residents] + [bytes(m["merchant_pub"]) for m in merchants]
        accounts = ([ledger.checking(r["resident_id"]) for r in residents]
                    + [ledger.escrow(c) for c in old_certs] + [ledger.fraud_receivable(c) for c in old_certs]
                    + [ledger.merchant(m) for m in merchant_ids])

        tags = [bytes(r["tag_hash"]) for r in all_rows(
            conn, "SELECT tag_hash FROM tags WHERE cert_id = ANY(%s) UNION "
                  "SELECT tag_hash FROM payments WHERE merchant_id = ANY(%s)", (old_certs, merchant_ids))]
        conn.execute("DELETE FROM nessie_moves WHERE payout_id IN (SELECT payout_id FROM payouts WHERE tag_hash = ANY(%s))",
                     (tags,))
        conn.execute("DELETE FROM payouts WHERE tag_hash = ANY(%s) OR merchant_id = ANY(%s)", (tags, merchant_ids))
        conn.execute("DELETE FROM payments WHERE tag_hash = ANY(%s)", (tags,))
        conn.execute("DELETE FROM tags WHERE tag_hash = ANY(%s)", (tags,))
        conn.execute(
            "DELETE FROM cases WHERE cert_id = ANY(%s) OR merchant_id = ANY(%s) OR device_pub = ANY(%s)",
            (old_certs, merchant_ids, devices),
        )
        conn.execute(
            "DELETE FROM candidates WHERE subject_id = ANY(%s)",
            ([c.hex() for c in old_certs] + [m.hex() for m in merchant_ids],),
        )
        conn.execute("DELETE FROM device_log WHERE device_pub = ANY(%s)", (devices,))
        conn.execute("DELETE FROM contacts WHERE device_pub = ANY(%s) OR peer_pub = ANY(%s)", (devices, devices))
        conn.execute("DELETE FROM uploads WHERE device_pub = ANY(%s)", (devices,))
        # Whole transactions, so the ledger stays balanced.
        conn.execute(
            """DELETE FROM ledger_entries WHERE txn_id IN
               (SELECT txn_id FROM ledger_entries WHERE account = ANY(%s))""",
            (accounts,),
        )
        conn.execute(
            """DELETE FROM nessie_moves WHERE status = 'queued' AND (from_account_id = ANY(%s) OR to_account_id = ANY(%s))""",
            ([a for r in residents for a in (r["checking_account_id"], r["escrow_account_id"]) if a]
             + [m["nessie_account_id"] for m in merchants if m["nessie_account_id"]],) * 2,
        )
        conn.execute("DELETE FROM cert_status WHERE cert_id = ANY(%s)", (old_certs,))
        conn.execute("DELETE FROM certificates WHERE cert_id = ANY(%s)", (old_certs,))
        conn.execute(
            "UPDATE merchants SET pool_eligible = TRUE, per_payment_limit_cents = NULL WHERE merchant_id = ANY(%s)",
            (merchant_ids,),
        )
        for m in merchants:
            new_account = fresh.get(bytes(m["merchant_id"]))
            if new_account:
                conn.execute("UPDATE merchants SET nessie_account_id = %s WHERE merchant_id = %s",
                             (new_account, m["merchant_id"]))

        for r in residents:
            checking_id, escrow_id = fresh.get(r["resident_id"], (r["checking_account_id"], r["escrow_account_id"]))
            conn.execute(
                "UPDATE residents SET checking_account_id = %s, escrow_account_id = %s WHERE resident_id = %s",
                (checking_id, escrow_id, r["resident_id"]),
            )
            cert_id = crypto.random_id()
            cert = registry.issue_cert(
                conn, deps.server_key, cert_id=cert_id, cert_ver=1, holder_pub=bytes(r["holder_pub"]),
                cap_cents=registry.BASE_CAP_CENTS, now=now, escrow_ref=escrow_id or "ledger-only",
                resident_id=r["resident_id"],
            )
            conn.execute("INSERT INTO cert_status (cert_id, status, max_cap_cents) VALUES (%s, 'active', %s)",
                         (cert_id, registry.BASE_CAP_CENTS))
            nessie_on = deps.nessie is not None and r["resident_id"] in fresh
            txn = registry._move(
                conn, debit=ledger.escrow(cert_id), credit=ledger.checking(r["resident_id"]),
                cents=registry.BASE_CAP_CENTS, ref="lock escrow",
                nessie_from=checking_id if nessie_on else None, nessie_to=escrow_id if nessie_on else None,
                summary=f"Lock escrow, {r['display_name']} checking → escrow",
            )
            if txn:
                moves.append(txn)
            certs.append(cert)
        cases.publish_policy(ctx, conn)  # the old certs leave the frozen list

    for txn in moves:
        deps.mover.execute(txn)
    if storm_cap_cents:
        certs = [registry.raise_storm_mode(deps, c.cert_id, storm_cap_cents, now=now) for c in certs]
    for event, data in ctx.events:
        deps.events.publish(event, data)
    deps.events.publish("accounts", {"reset": True})
    return {
        "ok": True,
        "seconds": round(time.monotonic() - started, 2),
        "residents": [{"display_name": r["display_name"], "cert": c.to_json()} for r, c in zip(residents, certs,
                                                                                             strict=True)],
        "merchants": [m["display_name"] for m in merchants],
        "nessie_accounts_opened": sum(2 if isinstance(v, tuple) else 1 for v in fresh.values()),
    }


def _customer_of(deps: Deps, account_id: str) -> str | None:
    try:
        return deps.nessie.get_account(account_id).get("customer_id")
    except NessieError:
        return None
