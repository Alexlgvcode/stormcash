"""Settlement: ingest uploaded items (spec §11.2).

`ingest_items` is the one entry point, used by POST /v1/sync, the simulator and
tests. It is idempotent: re-ingesting the same items changes nothing (apart
from the `uploads` log row). Each upload is stored in one DB transaction, one
upload at a time. Every item is checked before anything of it is written and
runs under its own savepoint, so an invalid item is dropped, counted and leaves
no trace. Nessie moves and SSE events run after the transaction commits.

Round trips: on the hosted database each one costs ~35 ms and seed-town makes
~300 uploads, so the transaction runs in pipeline mode (db.pipelined) and only
waits where the code needs an answer. DLOG entries are stored as one batch, and
what the PAY and TAG checks read is fetched once per upload (`_Lookups`) and
kept current as items are stored. The rare paths that open cases (R1–R5) use
the plain queries in cases.py, and the lookups are refetched after them.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from . import cases, detectors, ledger, registry
from .db import all_rows, one, pipelined, scalar
from .deps import Deps
from .nessie import MoneyMover, is_whole_dollars
from .protocol import rules
from .protocol.encoding import EncodingError
from .protocol.objects import Cert, Dlog, Item, Pay, Policy, Proof, Rcpt, Renew, Tag, b64u_encode

log = logging.getLogger(__name__)

# Priority order (§10.2); within priority 3, DLOG before PAY so a merchant's
# REFUSE entry is known before its PAY, then RENEW.
KIND_ORDER = {"PROOF": 0, "POLICY": 1, "RCPT": 1, "CERT": 1, "DLOG": 2, "PAY": 3, "RENEW": 4, "TAG": 5}
INGEST_LOCK = 0x5C_1A6E57  # pg_advisory_xact_lock key: one upload at a time


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
    recheck: set[bytes] = field(default_factory=set)  # devices whose payments need R5 again


@dataclass
class _Row:
    """An event payload whose RETURNING row is read once the pipeline has synced."""

    cur: psycopg.Cursor
    extra: dict

    def resolve(self) -> dict:
        return {**self.cur.fetchone(), **self.extra}


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
    return _policy_from_row(row)


def _policy_from_row(row: dict) -> Policy:
    return Policy(
        row["policy_ver"], row["issued_at"], tuple(bytes(c) for c in row["frozen_certs"]),
        tuple(row["merchant_limits"]), bytes(row["server_sig"]),
    )


@dataclass
class _Snapshot:
    statuses: set[bytes]  # PAY certs with a cert_status row
    merchants: dict[bytes, dict]  # merchant_pub -> row
    holders: dict[bytes, bytes]  # cert_id -> holder_pub
    caps: dict[bytes, list[int]]  # cert_id -> cap of every version
    tags: dict[bytes, dict[bytes, Tag]]  # cert_id -> tag_hash -> stored tag
    payments: dict[bytes, str]  # tag_hash -> status, every payment of these certs
    refused: set[tuple[bytes, str]]  # (merchant_pub, b64u tag_hash) of REFUSE entries
    escrow: dict[bytes, int]  # cert_id -> escrow ledger balance
    residents: dict[bytes, dict]  # cert_id -> resident row


class _Lookups:
    """What the PAY and TAG checks of one upload read, fetched for all its items
    in one round trip and kept current as they store tags, payments and payouts.
    Code that opens a case can change rows behind it (cert status, pool
    eligibility, payment statuses), so after it callers say `stale()` and the
    next read refetches. Queries are sent on creation and read on first use."""

    def __init__(self, conn: psycopg.Connection, items: list[Item]) -> None:
        pays = [it.body for it in items if it.kind == "PAY"]
        self._conn = conn
        self._pay_certs = sorted({p.cert.cert_id for p in pays})
        self._certs = sorted({*self._pay_certs, *(it.body.cert_id for it in items if it.kind == "TAG")})
        self._merchants = sorted({p.det.merchant_pub for p in pays})
        self._ths = sorted({b64u_encode(p.tag.tag_hash) for p in pays})
        self._snap: _Snapshot | None = None
        self._cursors = self._send()

    def _send(self) -> dict[str, psycopg.Cursor]:
        conn, certs, pay_certs = self._conn, self._certs, self._pay_certs
        return {
            # Locks the PAY certs' status rows (as handle_pay did one by one), in cert_id order.
            "statuses": conn.execute(
                "SELECT cert_id FROM cert_status WHERE cert_id = ANY(%s) ORDER BY cert_id FOR UPDATE", (pay_certs,)
            ),
            "merchants": conn.execute("SELECT * FROM merchants WHERE merchant_pub = ANY(%s)", (self._merchants,)),
            "versions": conn.execute(
                "SELECT cert_id, holder_pub, cap_cents FROM certificates WHERE cert_id = ANY(%s) ORDER BY cert_id, cert_ver",
                (certs,),
            ),
            "tags": conn.execute("SELECT * FROM tags WHERE cert_id = ANY(%s)", (certs,)),
            "payments": conn.execute("SELECT tag_hash, status FROM payments WHERE cert_id = ANY(%s)", (certs,)),
            "refused": conn.execute(
                """SELECT device_pub, body->>'th' AS th FROM device_log
                   WHERE kind = 'REFUSE' AND device_pub = ANY(%s) AND body->>'th' = ANY(%s)""",
                (self._merchants, self._ths),
            ),
            "escrow": conn.execute(
                """SELECT account, COALESCE(SUM(debit_cents - credit_cents), 0) AS b FROM ledger_entries
                   WHERE account = ANY(%s) GROUP BY account""",
                ([ledger.escrow(c) for c in pay_certs],),
            ),
            "residents": conn.execute(
                """SELECT DISTINCT ON (c.cert_id) c.cert_id AS for_cert, r.* FROM residents r
                   JOIN certificates c ON c.resident_id = r.resident_id
                   WHERE c.cert_id = ANY(%s) ORDER BY c.cert_id""",
                (pay_certs,),
            ),
        }

    def current(self) -> _Snapshot:
        if self._snap is None:
            cur = self._cursors or self._send()
            self._cursors = None
            snap = _Snapshot(
                statuses={bytes(r["cert_id"]) for r in cur["statuses"].fetchall()},
                merchants={bytes(r["merchant_pub"]): r for r in cur["merchants"].fetchall()},
                holders={}, caps={}, tags={}, payments={}, refused=set(), escrow={}, residents={},
            )
            for r in cur["versions"].fetchall():
                snap.holders.setdefault(bytes(r["cert_id"]), bytes(r["holder_pub"]))
                snap.caps.setdefault(bytes(r["cert_id"]), []).append(r["cap_cents"])
            for r in cur["tags"].fetchall():
                snap.tags.setdefault(bytes(r["cert_id"]), {})[bytes(r["tag_hash"])] = tag_from_row(r)
            snap.payments = {bytes(r["tag_hash"]): r["status"] for r in cur["payments"].fetchall()}
            snap.refused = {(bytes(r["device_pub"]), r["th"]) for r in cur["refused"].fetchall()}
            balances = {r["account"]: r["b"] for r in cur["escrow"].fetchall()}
            snap.escrow = {c: balances.get(ledger.escrow(c), 0) for c in self._pay_certs}
            snap.residents = {bytes(r.pop("for_cert")): r for r in cur["residents"].fetchall()}
            self._snap = snap
        return self._snap

    def stale(self) -> None:
        self._snap = None

    # What this upload writes (a stale snapshot is refetched with it instead).

    def stored(self, tag: Tag) -> None:
        if self._snap is not None:
            self._snap.tags.setdefault(tag.cert_id, {})[tag.tag_hash] = tag

    def payment(self, tag_hash: bytes, status: str) -> None:
        if self._snap is not None:
            self._snap.payments[tag_hash] = status

    def paid_from_escrow(self, cert_id: bytes, cents: int) -> None:
        if self._snap is not None:
            self._snap.escrow[cert_id] -= cents


def _store_tag(conn: psycopg.Connection, tag: Tag, lookups: _Lookups) -> bool:
    """store_tag, answered from the lookups: True if the tag is new."""
    if tag.tag_hash in lookups.current().tags.get(tag.cert_id, {}):
        return False
    conn.execute(
        """INSERT INTO tags (tag_hash, cert_id, counter, prev_hash, amount_cents, cum_cents, details_hash, sig)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tag_hash) DO NOTHING""",
        (tag.tag_hash, tag.cert_id, tag.counter, tag.prev_hash, tag.amount_cents, tag.cum_cents,
         tag.details_hash, tag.sig),
    )
    lookups.stored(tag)
    return True


def _conflicts(tag: Tag, lookups: _Lookups) -> bool:
    """Does a stored tag of the cert equivocate with this one (R1–R3)?"""
    h = tag.tag_hash
    return any(xh != h and rules.equivocation(x, tag) for xh, x in lookups.current().tags.get(tag.cert_id, {}).items())


def _check_new_tag(ctx: _Ctx, conn: psycopg.Connection, tag: Tag, lookups: _Lookups) -> None:
    if _conflicts(tag, lookups):
        cases.check_new_tag(ctx, conn, tag)  # opens the case from what the database holds
        lookups.stale()


# Handlers ----------------------------------------------------------------------------------


def _server_signed(ctx: _Ctx, conn, obj) -> None:
    if not obj.verify(ctx.deps.settings.server_pub):
        raise InvalidItem(f"{obj.TYPE} not signed by this server")


def handle_tag(ctx: _Ctx, conn: psycopg.Connection, item: Item, lookups: _Lookups) -> None:
    tag: Tag = item.body
    pub = lookups.current().holders.get(tag.cert_id)
    if pub is None or not tag.verify(pub):
        raise InvalidItem("tag not signed by a known certificate holder")
    if _store_tag(conn, tag, lookups):
        _check_new_tag(ctx, conn, tag, lookups)


def handle_proof(ctx: _Ctx, conn: psycopg.Connection, item: Item, lookups: None) -> None:
    proof: Proof = item.body
    pub = holder_pub(conn, proof.a.cert_id)
    if pub is None or not rules.verify_proof(proof, pub):
        raise InvalidItem("invalid PROOF")
    # A phone found it first: the case is `offline` unless the server already had it.
    cases.open_equivocation_case(ctx, conn, proof.a, proof.b, offline=True)
    for tag in (proof.a, proof.b):
        if store_tag(conn, tag):
            cases.check_new_tag(ctx, conn, tag)


def handle_renew(ctx: _Ctx, conn: psycopg.Connection, item: Item, lookups: _Lookups | None) -> None:
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


def handle_pay(ctx: _Ctx, conn: psycopg.Connection, item: Item, lookups: _Lookups) -> None:
    pay: Pay = item.body
    cert, tag, det = pay.cert, pay.tag, pay.det
    _server_signed(ctx, conn, cert)
    if tag.cert_id != cert.cert_id or not tag.verify(cert.holder_pub):
        raise InvalidItem("tag not signed by the certificate holder")
    if tag.details_hash != det.digest():
        raise InvalidItem("details_hash does not match DET")
    merchant = lookups.current().merchants.get(det.merchant_pub)
    if merchant is None:
        raise InvalidItem("PAY names an unknown merchant")
    if cert.cert_id not in lookups.current().statuses:  # checked before anything is stored
        raise InvalidItem("PAY for a certificate this server never issued")
    if _store_tag(conn, tag, lookups):
        _check_new_tag(ctx, conn, tag, lookups)

    if tag.tag_hash in lookups.current().payments:
        return  # already ingested
    hops = max(0, len(item.path) - 1)
    conn.execute(
        """INSERT INTO payments (tag_hash, cert_id, merchant_id, nonce, device_ts, relay_device, hops, path, status,
                                 received_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', to_timestamp(%s))
           ON CONFLICT (tag_hash) DO NOTHING""",
        (tag.tag_hash, cert.cert_id, merchant["merchant_id"], det.nonce, det.ts, ctx.device_pub, hops,
         Jsonb([list(p) for p in item.path]), ctx.now),
    )
    lookups.payment(tag.tag_hash, "pending")

    status = decide_payment(ctx, conn, pay, merchant, lookups)
    funded_escrow = funded_pool = 0
    if status == "settled":
        funded_escrow, funded_pool, held = fund_payment(
            ctx, conn, pay, merchant, lookups, allow_pool=merchant["pool_eligible"]
        )
        status = "held" if held else status
    elif status == "denied_knowing" and _first_on_honest_chain(conn, tag):
        funded_escrow, _, _ = fund_payment(ctx, conn, pay, merchant, lookups, allow_pool=False)
    row = conn.execute(
        """UPDATE payments SET status = %s, funded_escrow_cents = %s, funded_pool_cents = %s
           WHERE tag_hash = %s RETURNING *""",
        (status, funded_escrow, funded_pool, tag.tag_hash),
    )
    lookups.payment(tag.tag_hash, status)
    if status in ("settled", "held"):
        check_over_cap(ctx, conn, cert.cert_id, lookups)  # R4, after payment (§11.2 step 3)
    ctx.events.append(
        ("payment", _Row(row, {"merchant_name": merchant["display_name"], "amount_cents": tag.amount_cents,
                               "cum_cents": tag.cum_cents}))
    )


def decide_payment(ctx: _Ctx, conn: psycopg.Connection, pay: Pay, merchant: dict, lookups: _Lookups) -> str:
    """Status for a newly ingested, verified PAY (§11.2 step 3)."""
    tag = pay.tag
    if not rules.tag_valid(tag):
        return "invalid"  # fails single-tag validity: a merchant skipped C5/C6
    if (bytes(merchant["merchant_pub"]), b64u_encode(tag.tag_hash)) in lookups.current().refused:
        return "refused_evidence"  # the merchant refused it offline and kept it as evidence
    # R5 needs a stored tag that conflicts with this one; only then are the logs read.
    if _conflicts(tag, lookups) and cases.check_merchant_knew(ctx, conn, tag, merchant, pay.det.ts):
        lookups.stale()
        return "denied_knowing"
    return "settled"


def _first_on_honest_chain(conn: psycopg.Connection, z: Tag) -> bool:
    """z comes before every tag it conflicts with, so escrow still pays it (§9.4)."""
    conflicts = [x for x in cases.cert_tags(conn, z.cert_id) if x.tag_hash != z.tag_hash and rules.equivocation(x, z)]
    return all(z.counter < x.counter for x in conflicts)


def fund_payment(
    ctx: _Ctx, conn: psycopg.Connection, pay: Pay, merchant: dict, lookups: _Lookups, *, allow_pool: bool = True
) -> tuple[int, int, bool]:
    """Pay from escrow first, the rest from the guarantee pool (§11.2, §11.3).
    Returns (from_escrow, from_pool, held): held when a pool share was owed but
    the merchant has lost pool eligibility (R5, R6).

    escrow_avail is the escrow's ledger balance, which equals max_cap − already
    paid from escrow until a refund on close lowers it.
    """
    cert_id, amount = pay.cert.cert_id, pay.tag.amount_cents
    merchant_id = bytes(merchant["merchant_id"])
    escrow_avail = max(0, lookups.current().escrow[cert_id])
    from_escrow = min(amount, escrow_avail)
    from_pool = amount - from_escrow
    held = from_pool > 0 and not allow_pool
    if held:
        from_pool = 0
    resident = lookups.current().residents.get(cert_id)
    settings = ctx.deps.settings
    merchant_real = ctx.deps.nessie is not None and not merchant["simulated"] and merchant["nessie_account_id"]
    resident_real = ctx.deps.nessie is not None and resident and not resident["simulated"]
    name = merchant["display_name"]

    for source, cents in (("escrow", from_escrow), ("pool", from_pool)):
        if cents == 0:
            continue
        credit = ledger.escrow(cert_id) if source == "escrow" else ledger.POOL
        txn_id = ledger.post(conn, ledger.merchant(merchant_id), credit, cents, f"settle from {source}")
        if source == "escrow":
            lookups.paid_from_escrow(cert_id, cents)
        else:
            ledger.post(conn, ledger.fraud_receivable(cert_id), ledger.POOL_RECOVERIES, cents, "pool receivable")
        nessie_from = (
            resident["escrow_account_id"] if source == "escrow" and resident_real
            else settings.nessie_pool_account_id if source == "pool" else None
        )
        # Simulated money never touches Nessie (§11.4), even when paid to a real shop.
        use_nessie = bool(merchant_real and resident_real and nessie_from and is_whole_dollars(cents))
        payout = conn.execute(
            """INSERT INTO payouts (tag_hash, merchant_id, amount_cents, source, status)
               VALUES (%s, %s, %s, %s, %s) RETURNING payout_id""",
            (pay.tag.tag_hash, merchant_id, cents, source, "queued" if use_nessie else "ledger_only"),
        )
        if use_nessie:
            label = "Escrow" if source == "escrow" else "Guarantee pool"
            MoneyMover.queue(
                conn, txn_id, nessie_from, merchant["nessie_account_id"], cents, f"{label} → {name}",
                payout_id=payout.fetchone()["payout_id"],
            )
            ctx.moves.append(txn_id)
    return from_escrow, from_pool, held


def check_over_cap(ctx: _Ctx, conn: psycopg.Connection, cert_id: bytes, lookups: _Lookups) -> None:
    """R4 from the lookups; the case itself is opened from what the database holds."""
    snap = lookups.current()
    settled = [t for h, t in snap.tags.get(cert_id, {}).items() if snap.payments.get(h) == "settled"]
    if settled and rules.over_cap(settled, snap.caps.get(cert_id, [])):
        cases.check_over_cap(ctx, conn, cert_id)
        lookups.stale()


def handle_server_object(ctx: _Ctx, conn: psycopg.Connection, item: Item, lookups: _Lookups | None) -> None:
    """POLICY, RCPT and CERT items travel down; uploading them back is a no-op."""
    _server_signed(ctx, conn, item.body)


HANDLERS = {
    "TAG": handle_tag,
    "PROOF": handle_proof,
    "PAY": handle_pay,
    "RENEW": handle_renew,
    "POLICY": handle_server_object,
    "RCPT": handle_server_object,
    "CERT": handle_server_object,
}


# DLOG entries, as one batch ------------------------------------------------------------------


@dataclass
class _Dlogs:
    entries: list[tuple[Item, Dlog]]  # verified, in upload order
    dropped: int
    window: psycopg.Cursor | None = None  # stored entries at seq − 1 … seq + 1, before this batch
    inserted: psycopg.Cursor | None = None  # keys of the entries that were new


def _send_dlogs(conn: psycopg.Connection, items: list[Item]) -> _Dlogs:
    """Verify the entries and send their inserts (§11.2 step 5) without waiting."""
    batch = _Dlogs([], 0)
    rows = []
    for item in items:
        entry: Dlog = item.body
        try:
            if not entry.verify_self():
                raise InvalidItem("DLOG entry not signed by its device")
            rows.append((entry.device_pub, entry.seq, entry.entry_hash, entry.prev_hash, entry.ts, entry.kind,
                         Jsonb(entry.to_json()), entry.sig))
        except (InvalidItem, EncodingError):
            batch.dropped += 1
            continue
        batch.entries.append((item, entry))
    if not rows:
        return batch
    keys = sorted({(e.device_pub, s) for _, e in batch.entries for s in (e.seq - 1, e.seq, e.seq + 1)})
    batch.window = conn.execute(
        """SELECT body FROM device_log WHERE (device_pub, seq) IN
           (SELECT * FROM unnest(%s::bytea[], %s::int[]))""",
        ([k[0] for k in keys], [k[1] for k in keys]),
    )
    # One statement for the batch; within it, a repeated entry conflicts with its first copy.
    batch.inserted = conn.execute(
        """INSERT INTO device_log (device_pub, seq, entry_hash, prev_hash, ts, kind, body, sig)
           SELECT * FROM unnest(%s::bytea[], %s::int[], %s::bytea[], %s::bytea[], %s::bigint[], %s::text[],
                                %s::jsonb[], %s::bytea[])
           ON CONFLICT DO NOTHING RETURNING device_pub, seq, entry_hash""",
        [list(column) for column in zip(*rows)],
    )
    return batch


def _finish_dlogs(ctx: _Ctx, conn: psycopg.Connection, batch: _Dlogs, lookups: _Lookups | None) -> list[bytes]:
    """Contacts and R6 for the new entries, in upload order; returns the accepted ids.

    R6 looks at seq − 1 … seq + 1 of each new entry as stored at that point:
    what was there before this batch plus the batch's earlier new entries."""
    if not batch.entries:
        return []
    stored: dict[tuple[bytes, int], dict[bytes, Dlog]] = {}
    for r in batch.window.fetchall():
        e = Dlog.from_json(r["body"])
        stored.setdefault((e.device_pub, e.seq), {})[e.entry_hash] = e
    inserted = {(bytes(r["device_pub"]), r["seq"], bytes(r["entry_hash"])) for r in batch.inserted.fetchall()}
    contacts = []
    for _, entry in batch.entries:
        key = (entry.device_pub, entry.seq, entry.entry_hash)
        if key not in inserted:
            continue
        inserted.discard(key)  # a second copy in the same upload isn't new
        stored.setdefault((entry.device_pub, entry.seq), {})[entry.entry_hash] = entry
        if entry.kind == "CONTACT":
            contacts.append(entry)
        window = [e for s in (entry.seq - 1, entry.seq, entry.seq + 1)
                  for e in stored.get((entry.device_pub, s), {}).values()]
        if cases.check_log(ctx, conn, entry, window) and lookups is not None:
            lookups.stale()
        # New log evidence may show a merchant knew (§11.2 step 5): the device itself,
        # or the merchant a peer's CONTACT entry names. Re-checked once per upload.
        ctx.recheck.add(entry.device_pub)
        if entry.kind == "CONTACT":
            ctx.recheck.add(entry.peer_pub)
    if contacts:
        # Pairing only ever sets `paired`, and nothing above reads it, so pairing
        # after the batch ends where pairing after each entry would.
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO contacts (contact_id, device_pub, peer_pub, ts, sent_ids, recv_ids)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                [(e.contact_id, e.device_pub, e.peer_pub, e.ts, list(e.sent_ids), list(e.recv_ids)) for e in contacts],
            )
        cases.pair_contacts(conn, contacts)
    return [item.id for item, _ in batch.entries]


# Entry point ---------------------------------------------------------------------------


def _ingest_one(ctx: _Ctx, conn: psycopg.Connection, item: Item, lookups: _Lookups | None) -> bool:
    """One item under its own savepoint; False if it was invalid and dropped."""
    conn.execute("SAVEPOINT item")
    try:
        HANDLERS[item.kind](ctx, conn, item, lookups)
    except (InvalidItem, EncodingError):
        conn.execute("ROLLBACK TO SAVEPOINT item")
        if lookups is not None:
            lookups.stale()
        return False
    conn.execute("RELEASE SAVEPOINT item")
    return True


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
    ordered = sorted(items, key=lambda it: KIND_ORDER[it.kind])
    first = [it for it in ordered if KIND_ORDER[it.kind] < KIND_ORDER["DLOG"]]
    dlogs = [it for it in ordered if it.kind == "DLOG"]
    rest = [it for it in ordered if KIND_ORDER[it.kind] > KIND_ORDER["DLOG"]]
    accepted: list[bytes] = []
    tag_ids: list[bytes] = []
    with pipelined(deps.pool) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (INGEST_LOCK,))
        for item in first:
            if _ingest_one(ctx, conn, item, None):
                accepted.append(item.id)
            else:
                dropped += 1
        batch = _send_dlogs(conn, dlogs)
        # Sent now, so they share the DLOG batch's round trip (and see its REFUSE entries).
        lookups = _Lookups(conn, rest) if any(it.kind in ("PAY", "TAG") for it in rest) else None
        # §11.2 step 5 re-runs R5 for the payments of devices whose logs grew;
        # its reads go now too, for every device the batch could add (see below).
        logged = sorted({e.device_pub for _, e in batch.entries}
                        | {e.peer_pub for _, e in batch.entries if e.kind == "CONTACT"})
        recheck = cases.send_recheck_merchants(conn, logged) if logged else None
        policy_row = conn.execute("SELECT * FROM policy_versions ORDER BY policy_ver DESC LIMIT 1")
        mark = len(ctx.events)
        dropped += batch.dropped
        accepted += _finish_dlogs(ctx, conn, batch, lookups)
        for item in rest:
            if not _ingest_one(ctx, conn, item, lookups):
                dropped += 1
                continue
            (tag_ids if item.kind == "TAG" else accepted).append(item.id)
            if item.kind == "RENEW" and lookups is not None:
                lookups.stale()  # plain queries wrote around the lookups

        # A TAG shares its id with its PAY (§10.2). Receipting the id before the
        # PAY arrives would make phones delete the PAY, so a TAG is receipted
        # only once the server holds the payment.
        paid = conn.execute("SELECT tag_hash FROM payments WHERE tag_hash = ANY(%s)", (tag_ids,)) if tag_ids else None
        upload = conn.execute(
            """INSERT INTO uploads (device_pub, region_id, item_count, simulated, received_at)
               VALUES (%s, (SELECT region_id FROM residents WHERE holder_pub = %s
                            UNION ALL SELECT region_id FROM merchants WHERE merchant_pub = %s LIMIT 1), %s, %s,
                       to_timestamp(%s))
               RETURNING *""",
            (device_pub, device_pub, device_pub, len(items), simulated, now),
        )
        # The re-check (§11.2 step 5) read its payments before the items were
        # stored. Unless an item opened a case or published a POLICY since, the
        # only payments that changed are the ones this upload added, and
        # decide_payment already ran R5 on those with the same logs and tags. So
        # the early read gives the same answer; otherwise read again.
        rare = any(event != "payment" for event, _ in ctx.events[mark:])
        if ctx.recheck:
            if rare:
                recheck = cases.send_recheck_merchants(conn, sorted(ctx.recheck))
            cases.finish_recheck(ctx, conn, recheck, only=ctx.recheck)  # rechecks change none of the reads here
        row = None if any(event == "policy" for event, _ in ctx.events) else policy_row.fetchone()
        policy = _policy_from_row(row) if row is not None else current_policy(conn, deps.server_key, now)
        try:
            # Sent with the COMMIT; evaluated after it, where a failure can't fail the sync.
            detector_reads = detectors.send_incremental(deps, conn, now)
        except Exception:
            log.exception("detectors failed before ingest committed")
            detector_reads = None
    paid_ids = {bytes(r["tag_hash"]) for r in paid.fetchall()} if paid is not None else set()
    unreceipted = [t for t in tag_ids if t not in paid_ids]
    accepted += [t for t in tag_ids if t in paid_ids]
    upload = upload.fetchone()
    # Receipt ids are unique and sorted by the canonical encoding anyway.
    rcpt = Rcpt(now, tuple(dict.fromkeys(accepted))).signed(deps.server_key)

    for txn_id in ctx.moves:
        deps.mover.execute(txn_id)
    for event, data in ctx.events:
        deps.events.publish(event, data.resolve() if isinstance(data, _Row) else data)
    hops = max((len(it.path) - 1 for it in items if it.kind == "PAY"), default=0)
    deps.events.publish("upload", {**upload, "accepted": len(accepted), "dropped": dropped, "hops": max(0, hops)})
    try:  # §11.2: may create candidates for StormDesk
        if detector_reads is None:
            detectors.run_incremental(deps, now)
        else:
            detectors.finish_incremental(deps, now, detector_reads)
    except Exception:  # a detector bug must never fail a phone's sync
        log.exception("detectors failed after ingest")
    return SyncResult(rcpt, policy, ctx.certs, accepted, dropped, unreceipted)
