"""Demo reset (spec §12.1, §21.1): back to a clean table in seconds.

Clears everything the real phones did (payments, tags, cases, logs, contacts,
uploads, payouts, ledger and queued Nessie moves that touch a real entity),
opens fresh Nessie accounts so the Accounts tab starts from known numbers
(checking $500, escrow $0, shops $0), reissues each real resident a new
certificate with the $20 lock, and publishes a POLICY without the old certs.
The simulated town is untouched. The guarantee pool keeps its account.

The demo dry run (`python -m stormcash.dryrun`, §21.6) registers its own test
identities, named with DRY_RUN_PREFIX. StormDesk's worker skips them, and a
reset removes them first (`clear_dry_run`), so they never count as real phones.
"""

from __future__ import annotations

import time
import uuid

from . import cases, ledger, registry
from .db import all_rows, one
from .deps import Deps
from .nessie import NessieError
from .protocol import crypto
from .protocol.objects import Cert
from .settlement import _Ctx


DRY_RUN_PREFIX = "Dry-run "  # display names of the dry run's test identities (§21.6)


def reset_demo(deps: Deps, storm_cap_cents: int | None = None, now: int | None = None) -> dict:
    started = time.monotonic()
    now = int(time.time()) if now is None else now
    dry_run = clear_dry_run(deps, now)  # leftovers of a dry run are not real phones
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
        doomed_cases = [r["case_id"] for r in all_rows(
            conn, "SELECT case_id FROM cases WHERE cert_id = ANY(%s) OR merchant_id = ANY(%s) OR device_pub = ANY(%s)",
            (old_certs, merchant_ids, devices))]
        doomed_candidates = [r["candidate_id"] for r in all_rows(
            conn, "SELECT candidate_id FROM candidates WHERE subject_id = ANY(%s)",
            ([c.hex() for c in old_certs] + [m.hex() for m in merchant_ids],))]
        doomed_flags = [r["flag_id"] for r in all_rows(
            conn, "SELECT flag_id FROM flags WHERE candidate_id = ANY(%s)", (doomed_candidates,))]
        conn.execute("UPDATE messages SET flag_id = NULL WHERE flag_id = ANY(%s)", (doomed_flags,))
        conn.execute("DELETE FROM approvals WHERE flag_id = ANY(%s)", (doomed_flags,))
        conn.execute("DELETE FROM flags WHERE flag_id = ANY(%s)", (doomed_flags,))
        conn.execute("DELETE FROM stormdesk_runs WHERE case_id = ANY(%s) OR candidate_id = ANY(%s)",
                     (doomed_cases, doomed_candidates))
        conn.execute("DELETE FROM cases WHERE case_id = ANY(%s)", (doomed_cases,))
        conn.execute("DELETE FROM candidates WHERE candidate_id = ANY(%s)", (doomed_candidates,))
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
        "dry_run_removed": dry_run,
    }


def _customer_of(deps: Deps, account_id: str) -> str | None:
    try:
        return deps.nessie.get_account(account_id).get("customer_id")
    except NessieError:
        return None


def clear_dry_run(deps: Deps, now: int | None = None) -> dict:
    """Remove what demo dry runs created (§21.6): the residents and shops whose
    display name starts with DRY_RUN_PREFIX (never simulated ones) and everything
    that touches them, as clear_town does for the town: certificates, tags,
    payments, payouts, Nessie moves and call-log lines, cases, candidates, flags,
    StormDesk runs, logs, contacts, uploads and whole ledger transactions. Their
    Nessie records stay in the sandbox, under customers nothing points to any more.
    Publishes a POLICY when the latest one lists a removed certificate."""
    now = int(time.time()) if now is None else now
    ctx = _Ctx(deps, b"", now, False)
    with deps.pool.connection() as conn:
        residents = all_rows(conn, "SELECT * FROM residents WHERE NOT simulated AND starts_with(display_name, %s)",
                             (DRY_RUN_PREFIX,))
        shops = all_rows(conn, "SELECT * FROM merchants WHERE NOT simulated AND starts_with(display_name, %s)",
                         (DRY_RUN_PREFIX,))
        if not residents and not shops:
            return {"residents": 0, "shops": 0, "tags": 0, "cases": 0}
        resident_ids = [r["resident_id"] for r in residents]
        merchant_ids = [bytes(m["merchant_id"]) for m in shops]
        certs = [bytes(r["cert_id"]) for r in all_rows(
            conn, "SELECT DISTINCT cert_id FROM certificates WHERE resident_id = ANY(%s)", (resident_ids,))]
        devices = [bytes(r["holder_pub"]) for r in residents] + [bytes(m["merchant_pub"]) for m in shops]
        nessie_ids = [i for r in residents for i in (r["nessie_customer_id"], r["checking_account_id"],
                                                     r["escrow_account_id"]) if i]
        nessie_ids += [m["nessie_account_id"] for m in shops if m["nessie_account_id"]]
        accounts = ([ledger.checking(r) for r in resident_ids] + [ledger.escrow(c) for c in certs]
                    + [ledger.fraud_receivable(c) for c in certs] + [ledger.merchant(m) for m in merchant_ids])

        tags = [bytes(r["tag_hash"]) for r in all_rows(
            conn, "SELECT tag_hash FROM tags WHERE cert_id = ANY(%s) UNION "
                  "SELECT tag_hash FROM payments WHERE merchant_id = ANY(%s)", (certs, merchant_ids))]
        cases_ = [r["case_id"] for r in all_rows(
            conn, """SELECT case_id FROM cases WHERE cert_id = ANY(%s) OR merchant_id = ANY(%s) OR device_pub = ANY(%s)
                     OR tag_a = ANY(%s) OR tag_b = ANY(%s)""", (certs, merchant_ids, devices, tags, tags))]
        candidates = [r["candidate_id"] for r in all_rows(
            conn, "SELECT candidate_id FROM candidates WHERE subject_id = ANY(%s)",
            ([c.hex() for c in certs] + [m.hex() for m in merchant_ids],))]
        flags = [r["flag_id"] for r in all_rows(
            conn, "SELECT flag_id FROM flags WHERE candidate_id = ANY(%s)", (candidates,))]
        latest = one(conn, "SELECT frozen_certs FROM policy_versions ORDER BY policy_ver DESC LIMIT 1")
        listed = latest is not None and any(bytes(c) in certs for c in latest["frozen_certs"])

        conn.execute("""DELETE FROM nessie_moves WHERE payout_id IN (SELECT payout_id FROM payouts WHERE tag_hash = ANY(%s)
                        OR merchant_id = ANY(%s)) OR from_account_id = ANY(%s) OR to_account_id = ANY(%s)""",
                     (tags, merchant_ids, nessie_ids, nessie_ids))
        conn.execute("DELETE FROM payouts WHERE tag_hash = ANY(%s) OR merchant_id = ANY(%s)", (tags, merchant_ids))
        conn.execute("DELETE FROM payments WHERE tag_hash = ANY(%s)", (tags,))
        conn.execute("DELETE FROM stormdesk_runs WHERE case_id = ANY(%s) OR candidate_id = ANY(%s) OR merchant_id = ANY(%s)",
                     (cases_, candidates, merchant_ids))
        conn.execute("DELETE FROM messages WHERE merchant_id = ANY(%s) OR resident_id = ANY(%s) OR flag_id = ANY(%s)",
                     (merchant_ids, resident_ids, flags))
        conn.execute("DELETE FROM approvals WHERE flag_id = ANY(%s)", (flags,))
        conn.execute("DELETE FROM flags WHERE flag_id = ANY(%s)", (flags,))
        conn.execute("DELETE FROM cases WHERE case_id = ANY(%s)", (cases_,))
        conn.execute("DELETE FROM candidates WHERE candidate_id = ANY(%s)", (candidates,))
        conn.execute("DELETE FROM tags WHERE tag_hash = ANY(%s)", (tags,))
        conn.execute("DELETE FROM device_log WHERE device_pub = ANY(%s)", (devices,))
        conn.execute("DELETE FROM contacts WHERE device_pub = ANY(%s) OR peer_pub = ANY(%s)", (devices, devices))
        conn.execute("DELETE FROM uploads WHERE device_pub = ANY(%s)", (devices,))
        conn.execute("DELETE FROM ledger_entries WHERE txn_id IN (SELECT txn_id FROM ledger_entries WHERE account = ANY(%s))",
                     (accounts,))
        # The dashboard's Nessie call log: lines naming a dry-run entity or one of its Nessie ids.
        conn.execute("""DELETE FROM nessie_calls WHERE strpos(COALESCE(summary, ''), %s) > 0
                        OR EXISTS (SELECT 1 FROM unnest(%s::text[]) AS n(id) WHERE strpos(COALESCE(path, ''), n.id) > 0)""",
                     (DRY_RUN_PREFIX, nessie_ids))
        conn.execute("DELETE FROM merchant_contacts WHERE merchant_id = ANY(%s)", (merchant_ids,))
        conn.execute("DELETE FROM resident_contacts WHERE resident_id = ANY(%s)", (resident_ids,))
        conn.execute("DELETE FROM cert_status WHERE cert_id = ANY(%s)", (certs,))
        conn.execute("DELETE FROM certificates WHERE cert_id = ANY(%s)", (certs,))
        conn.execute("DELETE FROM residents WHERE resident_id = ANY(%s)", (resident_ids,))
        conn.execute("DELETE FROM merchants WHERE merchant_id = ANY(%s)", (merchant_ids,))
        if listed:
            cases.publish_policy(ctx, conn)  # the dry run's frozen cert leaves the policy
    for event, data in ctx.events:
        deps.events.publish(event, data)
    return {"residents": len(residents), "shops": len(shops), "tags": len(tags), "cases": len(cases_)}


def clear_town(deps: Deps, now: int | None = None) -> dict:
    """Remove the simulated town so `seed-town` can run a seed again (§16.4).

    Deletes every simulated resident and shop and everything that touches them:
    certificates, tags, payments, payouts, cases, candidates (and every
    region_dark candidate, which only the town raises), flags, StormDesk runs,
    logs, contacts, uploads, ledger transactions (whole ones, so the ledger stays
    balanced) and the shops' Photon threads. Real-device data stays. The shops'
    Photon contacts are returned so the caller can restore them on the new town
    (seeds derive shop ids, so the same seed gives the same shop ids).
    """
    now = int(time.time()) if now is None else now
    ctx = _Ctx(deps, b"", now, False)
    with deps.pool.connection() as conn:
        residents = [r["resident_id"] for r in all_rows(conn, "SELECT resident_id FROM residents WHERE simulated")]
        shops = all_rows(conn, "SELECT merchant_id, merchant_pub FROM merchants WHERE simulated")
        merchant_ids = [bytes(m["merchant_id"]) for m in shops]
        certs = [bytes(r["cert_id"]) for r in all_rows(
            conn, "SELECT DISTINCT cert_id FROM certificates WHERE resident_id = ANY(%s)", (residents,))]
        devices = [bytes(r["holder_pub"]) for r in all_rows(
            conn, "SELECT holder_pub FROM residents WHERE simulated")] + [bytes(m["merchant_pub"]) for m in shops]
        contacts = all_rows(conn, "SELECT merchant_id, channel, handle FROM merchant_contacts WHERE merchant_id = ANY(%s)",
                            (merchant_ids,))
        accounts = ([ledger.checking(r) for r in residents] + [ledger.escrow(c) for c in certs]
                    + [ledger.fraud_receivable(c) for c in certs] + [ledger.merchant(m) for m in merchant_ids])

        tags = [bytes(r["tag_hash"]) for r in all_rows(
            conn, "SELECT tag_hash FROM tags WHERE cert_id = ANY(%s) UNION "
                  "SELECT tag_hash FROM payments WHERE merchant_id = ANY(%s)", (certs, merchant_ids))]
        cases_ = [r["case_id"] for r in all_rows(
            conn, """SELECT case_id FROM cases WHERE cert_id = ANY(%s) OR merchant_id = ANY(%s) OR device_pub = ANY(%s)
                     OR tag_a = ANY(%s) OR tag_b = ANY(%s)""", (certs, merchant_ids, devices, tags, tags))]
        candidates = [r["candidate_id"] for r in all_rows(
            conn, "SELECT candidate_id FROM candidates WHERE subject_id = ANY(%s) OR kind = 'region_dark'",
            ([c.hex() for c in certs] + [m.hex() for m in merchant_ids],))]
        flags = [r["flag_id"] for r in all_rows(
            conn, "SELECT flag_id FROM flags WHERE candidate_id = ANY(%s)", (candidates,))]

        conn.execute("DELETE FROM nessie_moves WHERE payout_id IN (SELECT payout_id FROM payouts WHERE tag_hash = ANY(%s) "
                     "OR merchant_id = ANY(%s))", (tags, merchant_ids))
        conn.execute("DELETE FROM payouts WHERE tag_hash = ANY(%s) OR merchant_id = ANY(%s)", (tags, merchant_ids))
        conn.execute("DELETE FROM payments WHERE tag_hash = ANY(%s)", (tags,))
        conn.execute("DELETE FROM stormdesk_runs WHERE case_id = ANY(%s) OR candidate_id = ANY(%s) OR merchant_id = ANY(%s)",
                     (cases_, candidates, merchant_ids))
        conn.execute("DELETE FROM messages WHERE merchant_id = ANY(%s) OR flag_id = ANY(%s)", (merchant_ids, flags))
        conn.execute("DELETE FROM approvals WHERE flag_id = ANY(%s)", (flags,))
        conn.execute("DELETE FROM flags WHERE flag_id = ANY(%s)", (flags,))
        conn.execute("DELETE FROM cases WHERE case_id = ANY(%s)", (cases_,))
        conn.execute("DELETE FROM candidates WHERE candidate_id = ANY(%s)", (candidates,))
        conn.execute("DELETE FROM tags WHERE tag_hash = ANY(%s)", (tags,))
        conn.execute("DELETE FROM device_log WHERE device_pub = ANY(%s)", (devices,))
        conn.execute("DELETE FROM contacts WHERE device_pub = ANY(%s) OR peer_pub = ANY(%s)", (devices, devices))
        conn.execute("DELETE FROM uploads WHERE simulated OR device_pub = ANY(%s)", (devices,))
        conn.execute("DELETE FROM ledger_entries WHERE txn_id IN (SELECT txn_id FROM ledger_entries WHERE account = ANY(%s))",
                     (accounts,))
        conn.execute("DELETE FROM merchant_contacts WHERE merchant_id = ANY(%s)", (merchant_ids,))
        conn.execute("DELETE FROM resident_contacts WHERE resident_id = ANY(%s)", (residents,))
        conn.execute("DELETE FROM messages WHERE resident_id = ANY(%s)", (residents,))
        conn.execute("DELETE FROM cert_status WHERE cert_id = ANY(%s)", (certs,))
        conn.execute("DELETE FROM certificates WHERE cert_id = ANY(%s)", (certs,))
        conn.execute("DELETE FROM residents WHERE resident_id = ANY(%s)", (residents,))
        conn.execute("DELETE FROM merchants WHERE merchant_id = ANY(%s)", (merchant_ids,))
        cases.publish_policy(ctx, conn)  # the town's frozen certs and shop limits leave the policy
    for event, data in ctx.events:
        deps.events.publish(event, data)
    return {"residents": len(residents), "shops": len(shops), "payments": len(tags), "cases": len(cases_),
            "candidates": len(candidates), "contacts": contacts}
