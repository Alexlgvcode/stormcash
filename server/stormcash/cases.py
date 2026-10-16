"""Hard cases (spec §8.3, §9.4, §9.5, §11.2): R1–R6, freezes and POLICY versions.

Deterministic only: no AI decides anything here. R1–R4 freeze the certificate
and publish a new signed POLICY; R5 and R6 take away the merchant's guarantee
pool eligibility. Cases are deduplicated, so re-ingesting opens nothing new.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from . import registry
from .db import all_rows, one, scalar
from .protocol import rules
from .protocol.objects import Dlog, Policy, Tag, b64u_encode, proof_id

EQUIVOCATION_RULES = (rules.SAME_COUNTER, rules.BROKEN_LINK, rules.TOTAL_BACKWARDS)
POLICY_LOCK = 0x5C_9011C7  # pg_advisory_xact_lock key serializing POLICY versions


def _tag_from_row(row: dict) -> Tag:
    return Tag(
        bytes(row["cert_id"]), row["counter"], bytes(row["prev_hash"]), row["amount_cents"], row["cum_cents"],
        bytes(row["details_hash"]), bytes(row["sig"]),
    )


def cert_tags(conn: psycopg.Connection, cert_id: bytes) -> list[Tag]:
    return [_tag_from_row(r) for r in all_rows(conn, "SELECT * FROM tags WHERE cert_id = %s", (cert_id,))]


def _insert_case(ctx, conn: psycopg.Connection, rule: str, *, evidence: dict, detected_where: str = "server",
                 exposure_cents: int = 0, cert_id=None, merchant_id=None, device_pub=None,
                 tag_a=None, tag_b=None) -> dict:
    row = one(
        conn,
        """INSERT INTO cases (rule, cert_id, merchant_id, device_pub, tag_a, tag_b, evidence, detected_where,
                              exposure_cents)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (rule, cert_id, merchant_id, device_pub, tag_a, tag_b, Jsonb(evidence), detected_where, exposure_cents),
    )
    ctx.events.append(("case_opened", case_summary(row)))
    return row


def case_summary(row: dict) -> dict:
    return {k: row[k] for k in ("case_id", "rule", "cert_id", "merchant_id", "device_pub", "tag_a", "tag_b",
                                "detected_where", "exposure_cents", "created_at")}


# POLICY ----------------------------------------------------------------------------


def publish_policy(ctx, conn: psycopg.Connection) -> Policy:
    """Sign and store the next POLICY version: every frozen cert and every
    merchant per-payment limit."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (POLICY_LOCK,))
    ver = scalar(conn, "SELECT COALESCE(MAX(policy_ver), 0) + 1 AS v FROM policy_versions")
    frozen = [bytes(r["cert_id"]) for r in all_rows(conn, "SELECT cert_id FROM cert_status WHERE status = 'frozen'")]
    limits = [
        f"{bytes(r['merchant_id']).hex()}:{r['per_payment_limit_cents']}"
        for r in all_rows(conn, "SELECT merchant_id, per_payment_limit_cents FROM merchants "
                                "WHERE per_payment_limit_cents IS NOT NULL")
    ]
    policy = Policy(ver, ctx.now, tuple(frozen), tuple(limits)).signed(ctx.deps.server_key)
    conn.execute(
        """INSERT INTO policy_versions (policy_ver, issued_at, frozen_certs, merchant_limits, server_sig)
           VALUES (%s, %s, %s, %s, %s)""",
        (ver, ctx.now, frozen, limits, policy.sig),
    )
    ctx.events.append(("policy", policy.to_json()))
    return policy


def freeze_cert(ctx, conn: psycopg.Connection, cert_id: bytes) -> None:
    updated = scalar(
        conn,
        """UPDATE cert_status SET status = 'frozen', frozen_at = %s
           WHERE cert_id = %s AND status <> 'frozen' RETURNING cert_id""",
        (ctx.now, cert_id),
    )
    if updated is not None:
        publish_policy(ctx, conn)


def suspend_pool(conn: psycopg.Connection, merchant_id: bytes) -> None:
    conn.execute("UPDATE merchants SET pool_eligible = FALSE WHERE merchant_id = %s", (merchant_id,))


# R1–R3 -----------------------------------------------------------------------------


def open_equivocation_case(ctx, conn: psycopg.Connection, x: Tag, y: Tag, *, offline: bool) -> dict | None:
    """Open a case for a pair breaking R1–R3 (once per pair) and freeze the cert."""
    proof = rules.make_proof(x, y)
    if proof is None:
        return None
    a, b = proof.a, proof.b
    existing = one(
        conn,
        "SELECT * FROM cases WHERE rule = ANY(%s) AND tag_a = %s AND tag_b = %s",
        (list(EQUIVOCATION_RULES), a.tag_hash, b.tag_hash),
    )
    if existing:
        return None
    row = _insert_case(
        ctx, conn, proof.rule, cert_id=a.cert_id, tag_a=a.tag_hash, tag_b=b.tag_hash,
        detected_where="offline" if offline else "server", exposure_cents=b.amount_cents,
        evidence={"tags": [a.tag_hash.hex(), b.tag_hash.hex()], "proof_item_id": proof_id(proof).hex(),
                  "rules_fired": rules.rules_fired(a, b)},
    )
    freeze_cert(ctx, conn, a.cert_id)
    # A conflicting tag can arrive after a payment it implicates: re-run R5.
    recheck_cert_payments(ctx, conn, a.cert_id)
    return row


def check_new_tag(ctx, conn: psycopg.Connection, tag: Tag) -> None:
    """After a new tag is stored: the first stored tag it equivocates with opens a case."""
    for other in sorted(cert_tags(conn, tag.cert_id), key=lambda t: (t.counter, t.tag_hash)):
        if other.tag_hash != tag.tag_hash and rules.equivocation(other, tag):
            open_equivocation_case(ctx, conn, other, tag, offline=False)
            return


# R4 --------------------------------------------------------------------------------


def check_over_cap(ctx, conn: psycopg.Connection, cert_id: bytes) -> None:
    settled = [
        _tag_from_row(r)
        for r in all_rows(
            conn,
            """SELECT t.* FROM tags t JOIN payments p ON p.tag_hash = t.tag_hash
               WHERE p.cert_id = %s AND p.status = 'settled'""",
            (cert_id,),
        )
    ]
    caps = [c.cap_cents for c in registry.cert_versions(conn, cert_id)]
    if not settled or not rules.over_cap(settled, caps):
        return
    if scalar(conn, "SELECT 1 FROM cases WHERE rule = 'OVER_CAP' AND cert_id = %s", (cert_id,)):
        return
    top = max(settled, key=lambda t: t.cum_cents)
    _insert_case(
        ctx, conn, "OVER_CAP", cert_id=cert_id, tag_a=top.tag_hash, exposure_cents=top.cum_cents - max(caps),
        evidence={"tag": top.tag_hash.hex(), "cum_cents": top.cum_cents, "caps": caps},
    )
    freeze_cert(ctx, conn, cert_id)


# R5 --------------------------------------------------------------------------------


def merchant_logs(conn: psycopg.Connection, merchant_pub: bytes) -> list[Dlog]:
    """M's ACCEPT and CONTACT entries plus every peer CONTACT entry naming M."""
    rows = all_rows(
        conn,
        """SELECT body FROM device_log WHERE device_pub = %s AND kind IN ('ACCEPT', 'CONTACT')
           UNION ALL
           SELECT body FROM device_log WHERE kind = 'CONTACT' AND device_pub <> %s AND body->>'pp' = %s""",
        (merchant_pub, merchant_pub, b64u_encode(merchant_pub)),
    )
    return [Dlog.from_json(r["body"]) for r in rows]


def accept_time(conn: psycopg.Connection, merchant_pub: bytes, z: Tag, fallback: int) -> int:
    """t_accept: M's ACCEPT entry for z, else the payer's DET ts."""
    ts = scalar(
        conn,
        """SELECT MIN(ts) AS ts FROM device_log WHERE device_pub = %s AND kind = 'ACCEPT'
           AND body->>'th' = %s""",
        (merchant_pub, b64u_encode(z.tag_hash)),
    )
    return fallback if ts is None else ts


def check_merchant_knew(ctx, conn: psycopg.Connection, z: Tag, merchant: dict, det_ts: int) -> dict | None:
    """R5 for payment z at merchant M. Opens the case (once) and suspends M's
    pool eligibility. Returns the case evidence when R5 holds."""
    merchant_pub = bytes(merchant["merchant_pub"])
    t_accept = accept_time(conn, merchant_pub, z, det_ts)
    hit = rules.merchant_knew(
        z, merchant_pub=merchant_pub, t_accept=t_accept, cert_tags=cert_tags(conn, z.cert_id),
        logs=merchant_logs(conn, merchant_pub),
    )
    if hit is None:
        return None
    evidence = {
        "clause": hit.clause, "conflict": hit.conflict.hex(), "payment": z.tag_hash.hex(), "t_accept": t_accept,
        "contact_id": None if hit.contact_id is None else hit.contact_id.hex(),
    }
    merchant_id = bytes(merchant["merchant_id"])
    if not scalar(
        conn, "SELECT 1 FROM cases WHERE rule = 'MERCHANT_KNEW' AND merchant_id = %s AND tag_b = %s",
        (merchant_id, z.tag_hash),
    ):
        _insert_case(
            ctx, conn, "MERCHANT_KNEW", cert_id=z.cert_id, merchant_id=merchant_id, device_pub=merchant_pub,
            tag_a=hit.conflict, tag_b=z.tag_hash, exposure_cents=z.amount_cents, evidence=evidence,
        )
    suspend_pool(conn, merchant_id)
    return evidence


def _recheck(ctx, conn: psycopg.Connection, where: str, params: tuple) -> None:
    rows = all_rows(
        conn,
        f"""SELECT p.device_ts, t.*, m.merchant_id AS m_id, m.merchant_pub AS m_pub
            FROM payments p JOIN tags t ON t.tag_hash = p.tag_hash JOIN merchants m ON m.merchant_id = p.merchant_id
            WHERE p.status IN ('settled', 'held') AND {where}""",
        params,
    )
    for row in rows:
        merchant = {"merchant_id": row["m_id"], "merchant_pub": row["m_pub"]}
        if check_merchant_knew(ctx, conn, _tag_from_row(row), merchant, row["device_ts"]):
            conn.execute("UPDATE payments SET status = 'denied_knowing' WHERE tag_hash = %s", (row["tag_hash"],))


def recheck_merchant_payments(ctx, conn: psycopg.Connection, device_pub: bytes) -> None:
    """§11.2 step 5: after a device's log arrives, re-run R5 for its accepted
    payments whose certs have cases. Already-paid money stays paid; the case
    records it."""
    _recheck(
        ctx, conn, "m.merchant_pub = %s AND EXISTS (SELECT 1 FROM cases c WHERE c.cert_id = p.cert_id)",
        (device_pub,),
    )


def recheck_cert_payments(ctx, conn: psycopg.Connection, cert_id: bytes) -> None:
    _recheck(ctx, conn, "p.cert_id = %s", (cert_id,))


# R6 and contact pairing --------------------------------------------------------------------


def pair_contact(conn: psycopg.Connection, entry: Dlog) -> None:
    """Mark both rows paired when both sides logged this contact naming each other."""
    conn.execute(
        """UPDATE contacts SET paired = TRUE
           WHERE contact_id = %s AND (device_pub, peer_pub) IN ((%s, %s), (%s, %s))
           AND (SELECT count(*) FROM contacts WHERE contact_id = %s
                AND (device_pub, peer_pub) IN ((%s, %s), (%s, %s))) = 2""",
        (entry.contact_id, entry.device_pub, entry.peer_pub, entry.peer_pub, entry.device_pub,
         entry.contact_id, entry.device_pub, entry.peer_pub, entry.peer_pub, entry.device_pub),
    )


def check_log(ctx, conn: psycopg.Connection, device_pub: bytes) -> None:
    """R6 on a device's stored chain; a merchant loses pool eligibility."""
    entries = [Dlog.from_json(r["body"]) for r in
               all_rows(conn, "SELECT body FROM device_log WHERE device_pub = %s", (device_pub,))]
    finding = rules.log_tamper(entries)
    if finding is None:
        return
    if scalar(
        conn, "SELECT 1 FROM cases WHERE rule = 'LOG_TAMPER' AND device_pub = %s AND (evidence->>'seq')::int = %s",
        (device_pub, finding.seq),
    ):
        return
    at_seq = sorted(e.entry_hash.hex() for e in entries if e.seq == finding.seq)
    merchant = one(conn, "SELECT merchant_id FROM merchants WHERE merchant_pub = %s", (device_pub,))
    _insert_case(
        ctx, conn, "LOG_TAMPER", device_pub=device_pub,
        merchant_id=None if merchant is None else merchant["merchant_id"],
        evidence={"kind": finding.kind, "seq": finding.seq, "entries": at_seq},
    )
    if merchant is not None:
        suspend_pool(conn, bytes(merchant["merchant_id"]))
