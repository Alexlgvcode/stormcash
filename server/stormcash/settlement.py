"""Settlement: ingest uploaded items (spec §11.2).

`ingest_items` is the one entry point, used by POST /v1/sync, the simulator and
tests. It is idempotent: re-ingesting the same items changes nothing (apart
from the `uploads` log row). Each item is verified and stored in its own DB
transaction; invalid items are dropped and counted. Nessie moves and SSE
events run after the transactions commit.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from . import cases, ledger, registry
from .db import all_rows, one, scalar
from .deps import Deps
from .nessie import MoneyMover, is_whole_dollars
from .protocol import rules
from .protocol.encoding import EncodingError
from .protocol.objects import Cert, Dlog, Item, Pay, Policy, Proof, Rcpt, Renew, Tag, b64u_encode

# Priority order (§10.2); within priority 3, DLOG before PAY so a merchant's
# REFUSE entry is known before its PAY, then RENEW.
KIND_ORDER = {"PROOF": 0, "POLICY": 1, "RCPT": 1, "CERT": 1, "DLOG": 2, "PAY": 3, "RENEW": 4, "TAG": 5}


class InvalidItem(Exception):
    pass


@dataclass
class SyncResult:
    rcpt: Rcpt
    policy: Policy
    certs: list[Cert]
    accepted: list[bytes]  # ids in the RCPT
    dropped: int
    unreceipted: list[bytes] = field(default_factory=list)  # stored TAGs whose PAY the server lacks

    def to_json(self) -> dict:
        return {
            "rcpt": self.rcpt.to_json(),
            "policy": self.policy.to_json(),
            "certs": [c.to_json() for c in self.certs],
        }


@dataclass
class _Ctx:
    deps: Deps
    device_pub: bytes
    now: int
    simulated: bool
    certs: list[Cert] = field(default_factory=list)
    moves: list[uuid.UUID] = field(default_factory=list)
    events: list[tuple[str, dict]] = field(default_factory=list)


# Lookups ---------------------------------------------------------------------------


def holder_pub(conn: psycopg.Connection, cert_id: bytes) -> bytes | None:
    row = one(conn, "SELECT holder_pub FROM certificates WHERE cert_id = %s LIMIT 1", (cert_id,))
    return None if row is None else bytes(row["holder_pub"])


def resident_for_cert(conn: psycopg.Connection, cert_id: bytes) -> dict | None:
    return one(
        conn,
        """SELECT r.* FROM residents r JOIN certificates c ON c.resident_id = r.resident_id
           WHERE c.cert_id = %s LIMIT 1""",
        (cert_id,),
    )


def store_tag(conn: psycopg.Connection, tag: Tag) -> bool:
    """Insert a verified tag; True if it was new."""
    return (
        scalar(
            conn,
            """INSERT INTO tags (tag_hash, cert_id, counter, prev_hash, amount_cents, cum_cents, details_hash, sig)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tag_hash) DO NOTHING RETURNING tag_hash""",
            (tag.tag_hash, tag.cert_id, tag.counter, tag.prev_hash, tag.amount_cents, tag.cum_cents,
             tag.details_hash, tag.sig),
        )
        is not None
    )


def tag_from_row(row: dict) -> Tag:
    return Tag(
        bytes(row["cert_id"]), row["counter"], bytes(row["prev_hash"]), row["amount_cents"], row["cum_cents"],
        bytes(row["details_hash"]), bytes(row["sig"]),
    )


def current_policy(conn: psycopg.Connection, server_key, now: int) -> Policy:
    """The highest POLICY version; version 1 (empty) is issued on first use."""
    row = one(conn, "SELECT * FROM policy_versions ORDER BY policy_ver DESC LIMIT 1")
    if row is None:
        policy = Policy(1, now, (), ()).signed(server_key)
        conn.execute(
            """INSERT INTO policy_versions (policy_ver, issued_at, frozen_certs, merchant_limits, server_sig)
               VALUES (1, %s, %s, %s, %s) ON CONFLICT (policy_ver) DO NOTHING""",
            (now, [], [], policy.sig),
        )
        row = one(conn, "SELECT * FROM policy_versions ORDER BY policy_ver DESC LIMIT 1")
    return Policy(
        row["policy_ver"], row["issued_at"], tuple(bytes(c) for c in row["frozen_certs"]),
        tuple(row["merchant_limits"]), bytes(row["server_sig"]),
    )


# Handlers (each runs inside its own transaction) ------------------------------------------


def _verify_tag(conn: psycopg.Connection, tag: Tag) -> None:
    pub = holder_pub(conn, tag.cert_id)
    if pub is None or not tag.verify(pub):
        raise InvalidItem("tag not signed by a known certificate holder")


def _server_signed(ctx: _Ctx, conn, obj) -> None:
    if not obj.verify(ctx.deps.settings.server_pub):
        raise InvalidItem(f"{obj.TYPE} not signed by this server")


def handle_tag(ctx: _Ctx, conn: psycopg.Connection, item: Item) -> None:
    _verify_tag(conn, item.body)
    if store_tag(conn, item.body):
        cases.check_new_tag(ctx, conn, item.body)


def handle_proof(ctx: _Ctx, conn: psycopg.Connection, item: Item) -> None:
    proof: Proof = item.body
    pub = holder_pub(conn, proof.a.cert_id)
    if pub is None or not rules.verify_proof(proof, pub):
        raise InvalidItem("invalid PROOF")
    # A phone found it first: the case is `offline` unless the server already had it.
    cases.open_equivocation_case(ctx, conn, proof.a, proof.b, offline=True)
    for tag in (proof.a, proof.b):
        if store_tag(conn, tag):
            cases.check_new_tag(ctx, conn, tag)


def handle_dlog(ctx: _Ctx, conn: psycopg.Connection, item: Item) -> None:
    entry: Dlog = item.body
    if not entry.verify_self():
        raise InvalidItem("DLOG entry not signed by its device")
    new = scalar(
        conn,
        """INSERT INTO device_log (device_pub, seq, entry_hash, prev_hash, ts, kind, body, sig)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING seq""",
        (entry.device_pub, entry.seq, entry.entry_hash, entry.prev_hash, entry.ts, entry.kind,
         Jsonb(entry.to_json()), entry.sig),
    )
    if new is None:
        return
    if entry.kind == "CONTACT":
        conn.execute(
            """INSERT INTO contacts (contact_id, device_pub, peer_pub, ts, sent_ids, recv_ids)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (entry.contact_id, entry.device_pub, entry.peer_pub, entry.ts, list(entry.sent_ids), list(entry.recv_ids)),
        )
        cases.pair_contact(conn, entry)
    cases.check_log(ctx, conn, entry)
    # New log evidence may show a merchant knew (§11.2 step 5): the device itself,
    # or the merchant a peer's CONTACT entry names.
    cases.recheck_merchant_payments(ctx, conn, entry.device_pub)
    if entry.kind == "CONTACT":
        cases.recheck_merchant_payments(ctx, conn, entry.peer_pub)


def handle_renew(ctx: _Ctx, conn: psycopg.Connection, item: Item) -> None:
    """Answer with a new version (expiry now + 72 h, same cap) unless frozen.
    A renewal the latest version already postdates gets that version back."""
    renew: Renew = item.body
    pub = holder_pub(conn, renew.cert_id)
    if pub is None or not renew.verify(pub):
        raise InvalidItem("RENEW not signed by the certificate holder")
    status = one(conn, "SELECT * FROM cert_status WHERE cert_id = %s FOR UPDATE", (renew.cert_id,))
    if status is None or status["status"] == "frozen":
        return
    latest = registry.latest_cert(conn, renew.cert_id)
    if latest.issued_at >= renew.ts - rules.CLOCK_TOLERANCE_S:
        ctx.certs.append(latest)
        return
    resident = resident_for_cert(conn, renew.cert_id)
    ctx.certs.append(
        registry.issue_cert(
            conn, ctx.deps.server_key, cert_id=renew.cert_id, cert_ver=latest.cert_ver + 1,
            holder_pub=latest.holder_pub, cap_cents=latest.cap_cents, now=ctx.now, escrow_ref=latest.escrow_ref,
            resident_id=resident["resident_id"],
        )
    )


def handle_pay(ctx: _Ctx, conn: psycopg.Connection, item: Item) -> None:
    pay: Pay = item.body
    cert, tag, det = pay.cert, pay.tag, pay.det
    _server_signed(ctx, conn, cert)
    if tag.cert_id != cert.cert_id or not tag.verify(cert.holder_pub):
        raise InvalidItem("tag not signed by the certificate holder")
    if tag.details_hash != det.digest():
        raise InvalidItem("details_hash does not match DET")
    merchant = one(conn, "SELECT * FROM merchants WHERE merchant_pub = %s", (det.merchant_pub,))
    if merchant is None:
        raise InvalidItem("PAY names an unknown merchant")
    if store_tag(conn, tag):
        cases.check_new_tag(ctx, conn, tag)

    status_row = one(conn, "SELECT * FROM cert_status WHERE cert_id = %s FOR UPDATE", (cert.cert_id,))
    if status_row is None:
        raise InvalidItem("PAY for a certificate this server never issued")
    hops = max(0, len(item.path) - 1)
    inserted = scalar(
        conn,
        """INSERT INTO payments (tag_hash, cert_id, merchant_id, nonce, device_ts, relay_device, hops, path, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending') ON CONFLICT (tag_hash) DO NOTHING RETURNING tag_hash""",
        (tag.tag_hash, cert.cert_id, merchant["merchant_id"], det.nonce, det.ts, ctx.device_pub, hops,
         Jsonb([list(p) for p in item.path])),
    )
    if inserted is None:
        return  # already ingested

    status = decide_payment(ctx, conn, pay, merchant)
    funded_escrow = funded_pool = 0
    if status == "settled":
        funded_escrow, funded_pool, held = fund_payment(ctx, conn, pay, merchant, allow_pool=merchant["pool_eligible"])
        status = "held" if held else status
    elif status == "denied_knowing" and _first_on_honest_chain(conn, tag):
        funded_escrow, _, _ = fund_payment(ctx, conn, pay, merchant, allow_pool=False)
    row = one(
        conn,
        """UPDATE payments SET status = %s, funded_escrow_cents = %s, funded_pool_cents = %s
           WHERE tag_hash = %s RETURNING *""",
        (status, funded_escrow, funded_pool, tag.tag_hash),
    )
    if status in ("settled", "held"):
        cases.check_over_cap(ctx, conn, cert.cert_id)  # R4, after payment (§11.2 step 3)
    ctx.events.append(
        ("payment", {**row, "merchant_name": merchant["display_name"], "amount_cents": tag.amount_cents,
                     "cum_cents": tag.cum_cents})
    )


def decide_payment(ctx: _Ctx, conn: psycopg.Connection, pay: Pay, merchant: dict) -> str:
    """Status for a newly ingested, verified PAY (§11.2 step 3)."""
    tag = pay.tag
    if not rules.tag_valid(tag):
        return "invalid"  # fails single-tag validity: a merchant skipped C5/C6
    refused = scalar(
        conn,
        """SELECT 1 FROM device_log WHERE device_pub = %s AND kind = 'REFUSE'
           AND body->>'th' = %s LIMIT 1""",
        (merchant["merchant_pub"], b64u_encode(tag.tag_hash)),
    )
    if refused:
        return "refused_evidence"  # the merchant refused it offline and kept it as evidence
    if cases.check_merchant_knew(ctx, conn, tag, merchant, pay.det.ts):
        return "denied_knowing"
    return "settled"


def _first_on_honest_chain(conn: psycopg.Connection, z: Tag) -> bool:
    """z comes before every tag it conflicts with, so escrow still pays it (§9.4)."""
    conflicts = [x for x in cases.cert_tags(conn, z.cert_id) if x.tag_hash != z.tag_hash and rules.equivocation(x, z)]
    return all(z.counter < x.counter for x in conflicts)


def fund_payment(
    ctx: _Ctx, conn: psycopg.Connection, pay: Pay, merchant: dict, *, allow_pool: bool = True
) -> tuple[int, int, bool]:
    """Pay from escrow first, the rest from the guarantee pool (§11.2, §11.3).
    Returns (from_escrow, from_pool, held): held when a pool share was owed but
    the merchant has lost pool eligibility (R5, R6).

    escrow_avail is the escrow's ledger balance, which equals max_cap − already
    paid from escrow until a refund on close lowers it.
    """
    cert_id, amount = pay.cert.cert_id, pay.tag.amount_cents
    merchant_id = bytes(merchant["merchant_id"])
    escrow_avail = max(0, ledger.balance(conn, ledger.escrow(cert_id)))
    from_escrow = min(amount, escrow_avail)
    from_pool = amount - from_escrow
    held = from_pool > 0 and not allow_pool
    if held:
        from_pool = 0
    resident = resident_for_cert(conn, cert_id)
    settings = ctx.deps.settings
    merchant_real = ctx.deps.nessie is not None and not merchant["simulated"] and merchant["nessie_account_id"]
    resident_real = ctx.deps.nessie is not None and resident and not resident["simulated"]
    name = merchant["display_name"]

    for source, cents in (("escrow", from_escrow), ("pool", from_pool)):
        if cents == 0:
            continue
        credit = ledger.escrow(cert_id) if source == "escrow" else ledger.POOL
        txn_id = ledger.post(conn, ledger.merchant(merchant_id), credit, cents, f"settle from {source}")
        if source == "pool":
            ledger.post(conn, ledger.fraud_receivable(cert_id), ledger.POOL_RECOVERIES, cents, "pool receivable")
        nessie_from = (
            resident["escrow_account_id"] if source == "escrow" and resident_real
            else settings.nessie_pool_account_id if source == "pool" else None
        )
        # Simulated money never touches Nessie (§11.4), even when paid to a real shop.
        use_nessie = bool(merchant_real and resident_real and nessie_from and is_whole_dollars(cents))
        payout_id = scalar(
            conn,
            """INSERT INTO payouts (tag_hash, merchant_id, amount_cents, source, status)
               VALUES (%s, %s, %s, %s, %s) RETURNING payout_id""",
            (pay.tag.tag_hash, merchant_id, cents, source, "queued" if use_nessie else "ledger_only"),
        )
        if use_nessie:
            label = "Escrow" if source == "escrow" else "Guarantee pool"
            MoneyMover.queue(
                conn, txn_id, nessie_from, merchant["nessie_account_id"], cents, f"{label} → {name}",
                payout_id=payout_id,
            )
            ctx.moves.append(txn_id)
    return from_escrow, from_pool, held


def handle_server_object(ctx: _Ctx, conn: psycopg.Connection, item: Item) -> None:
    """POLICY, RCPT and CERT items travel down; uploading them back is a no-op."""
    _server_signed(ctx, conn, item.body)


HANDLERS = {
    "TAG": handle_tag,
    "PROOF": handle_proof,
    "DLOG": handle_dlog,
    "PAY": handle_pay,
    "RENEW": handle_renew,
    "POLICY": handle_server_object,
    "RCPT": handle_server_object,
    "CERT": handle_server_object,
}


# Entry point ---------------------------------------------------------------------------


def ingest_items(
    deps: Deps,
    device_pub: bytes,
    items: list[Item],
    *,
    dropped: int = 0,
    simulated: bool = False,
    now: int | None = None,
) -> SyncResult:
    """Verify and store every item, settle payments, and build the response.

    `dropped` counts items the caller already failed to decode."""
    now = int(time.time()) if now is None else now
    ctx = _Ctx(deps, device_pub, now, simulated)
    accepted: list[bytes] = []
    tag_ids: list[bytes] = []
    for item in sorted(items, key=lambda it: KIND_ORDER[it.kind]):
        try:
            with deps.pool.connection() as conn:
                HANDLERS[item.kind](ctx, conn, item)
        except (InvalidItem, EncodingError):
            dropped += 1
            continue
        (tag_ids if item.kind == "TAG" else accepted).append(item.id)

    with deps.pool.connection() as conn:
        # A TAG shares its id with its PAY (§10.2). Receipting the id before the
        # PAY arrives would make phones delete the PAY, so a TAG is receipted
        # only once the server holds the payment.
        paid = {bytes(r["tag_hash"]) for r in all_rows(
            conn, "SELECT tag_hash FROM payments WHERE tag_hash = ANY(%s)", (tag_ids,))} if tag_ids else set()
        unreceipted = [t for t in tag_ids if t not in paid]
        accepted += [t for t in tag_ids if t in paid]
        policy = current_policy(conn, deps.server_key, now)
        upload = one(
            conn,
            """INSERT INTO uploads (device_pub, region_id, item_count, simulated)
               VALUES (%s, (SELECT region_id FROM residents WHERE holder_pub = %s
                            UNION ALL SELECT region_id FROM merchants WHERE merchant_pub = %s LIMIT 1), %s, %s)
               RETURNING *""",
            (device_pub, device_pub, device_pub, len(items), simulated),
        )
    # Receipt ids are unique and sorted by the canonical encoding anyway.
    rcpt = Rcpt(now, tuple(dict.fromkeys(accepted))).signed(deps.server_key)

    for txn_id in ctx.moves:
        deps.mover.execute(txn_id)
    for event, data in ctx.events:
        deps.events.publish(event, data)
    hops = max((len(it.path) - 1 for it in items if it.kind == "PAY"), default=0)
    deps.events.publish("upload", {**upload, "accepted": len(accepted), "dropped": dropped, "hops": max(0, hops)})
    return SyncResult(rcpt, policy, ctx.certs, accepted, dropped, unreceipted)
