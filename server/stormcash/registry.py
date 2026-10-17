"""Residents, merchants, certificates and Storm Mode (spec §7.4, §11.3, §11.4, §12.1).

Service functions shared by the API routes, the simulator and tests. Money
always moves in the ledger; for real demo entities it is also queued as a
Nessie withdrawal + deposit pair and executed after the DB transaction commits.
"""

from __future__ import annotations

import time
import uuid

import psycopg

from . import ledger
from .db import all_rows, one, pipelined, scalar
from .deps import Deps
from .nessie import MoneyMover, NessieError, is_whole_dollars
from .protocol import crypto, encoding
from .protocol.encoding import EncodingError
from .protocol.objects import Cert, Mcert

HOUR = 3600
DAY = 24 * HOUR
BASE_CAP_CENTS = 2000  # always-on cap
MAX_CAP_CENTS = 5000  # Storm Mode cap
CERT_TTL_S = 72 * HOUR
MCERT_TTL_S = 30 * DAY
ESCROW_GRACE_S = 24 * HOUR
CHECKING_OPENING_DOLLARS = 500
CONTACT_CHANNELS = ("telegram", "imessage", "sms")


class RegistryError(Exception):
    status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Invalid(RegistryError):
    status = 400


class Forbidden(RegistryError):
    status = 403


class NotFound(RegistryError):
    status = 404


class Conflict(RegistryError):
    status = 409


class Unavailable(RegistryError):
    status = 503


def _now(now: int | None) -> int:
    return int(time.time()) if now is None else now


def _string(value: str | None, name: str) -> str:
    try:
        return encoding.normalize_string(value or "")
    except EncodingError as exc:
        raise Invalid(f"{name}: {exc}") from exc


def _pub(value: bytes, name: str) -> bytes:
    try:
        crypto.load_public_key(value)
    except crypto.CryptoError as exc:
        raise Invalid(f"{name}: {exc}") from exc
    return value


def _check_region(conn: psycopg.Connection, region_id: str | None) -> None:
    if region_id and scalar(conn, "SELECT 1 FROM regions WHERE region_id = %s", (region_id,)) is None:
        raise Invalid(f"unknown region_id {region_id!r}")


# Certificates ------------------------------------------------------------------


def cert_from_row(row: dict) -> Cert:
    return Cert(
        bytes(row["cert_id"]), row["cert_ver"], bytes(row["holder_pub"]), row["cap_cents"],
        row["issued_at"], row["expires_at"], row["escrow_ref"], bytes(row["server_sig"]),
    )


def latest_cert(conn: psycopg.Connection, cert_id: bytes) -> Cert | None:
    row = one(conn, "SELECT * FROM certificates WHERE cert_id = %s ORDER BY cert_ver DESC LIMIT 1", (cert_id,))
    return None if row is None else cert_from_row(row)


def cert_versions(conn: psycopg.Connection, cert_id: bytes) -> list[Cert]:
    rows = all_rows(conn, "SELECT * FROM certificates WHERE cert_id = %s ORDER BY cert_ver", (cert_id,))
    return [cert_from_row(r) for r in rows]


def issue_cert(
    conn: psycopg.Connection,
    server_key,
    *,
    cert_id: bytes,
    cert_ver: int,
    holder_pub: bytes,
    cap_cents: int,
    now: int,
    escrow_ref: str,
    resident_id: uuid.UUID,
) -> Cert:
    cert = Cert(cert_id, cert_ver, holder_pub, cap_cents, now, now + CERT_TTL_S, escrow_ref).signed(server_key)
    conn.execute(
        """INSERT INTO certificates (cert_id, cert_ver, resident_id, holder_pub, cap_cents, issued_at,
                                     expires_at, escrow_ref, server_sig)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (cert_id, cert_ver, resident_id, holder_pub, cap_cents, cert.issued_at, cert.expires_at, escrow_ref, cert.sig),
    )
    return cert


def issue_mcert(server_key, merchant: dict, now: int) -> Mcert:
    """MCERTs are not stored: re-issuing gives the merchant a fresh expiry."""
    return Mcert(
        bytes(merchant["merchant_id"]), 1, bytes(merchant["merchant_pub"]), merchant["display_name"],
        merchant["region_id"] or "", now + MCERT_TTL_S,
    ).signed(server_key)


def paid_from_escrow(conn: psycopg.Connection, cert_id: bytes) -> int:
    return scalar(
        conn,
        """SELECT COALESCE(SUM(po.amount_cents), 0) AS paid FROM payouts po
           JOIN payments p ON p.tag_hash = po.tag_hash
           WHERE p.cert_id = %s AND po.source = 'escrow'""",
        (cert_id,),
    )


def _move(
    conn: psycopg.Connection,
    *,
    debit: str,
    credit: str,
    cents: int,
    ref: str,
    nessie_from: str | None,
    nessie_to: str | None,
    summary: str,
) -> uuid.UUID | None:
    """Post to the ledger; queue the Nessie pair when both accounts are real.
    Returns the txn_id to execute after commit, or None if ledger-only."""
    txn_id = ledger.post(conn, debit, credit, cents, ref)
    if nessie_from and nessie_to and is_whole_dollars(cents):
        MoneyMover.queue(conn, txn_id, nessie_from, nessie_to, cents, summary)
        return txn_id
    return None


# Residents -----------------------------------------------------------------------


def register_resident(
    deps: Deps,
    display_name: str,
    holder_pub: bytes,
    region_id: str | None,
    *,
    simulated: bool = False,
    now: int | None = None,
    cert_id: bytes | None = None,
    contact: dict | None = None,
) -> tuple[uuid.UUID, Cert, bool]:
    """Create a resident, Nessie checking ($500) + escrow ($0), lock $20 and
    issue cert v1 (cap $20). Returns (resident_id, cert, created); registering
    the same holder_pub again returns the existing resident and latest cert.
    `contact` ({channel, handle}) is the Photon handle that may text FREEZE (§17.2);
    it is saved for an existing resident too.
    `cert_id` is only for the seeded simulator; phones always get a random one."""
    now = _now(now)
    display_name = _string(display_name, "display_name")
    region_id = _string(region_id, "region_id") or None
    _pub(holder_pub, "holder_pub")
    contact = _contact(contact)

    with deps.pool.connection() as conn:
        existing = _existing_resident(conn, holder_pub)
        if existing:
            if contact:
                set_resident_contact(conn, existing[0], contact)
            return existing
        _check_region(conn, region_id)

    resident_id = uuid.uuid4()
    cert_id = cert_id or crypto.random_id()
    real = not simulated and deps.nessie is not None
    customer_id = checking_id = escrow_id = None
    if real:
        try:
            customer_id = deps.nessie.create_customer(display_name, "StormCash")
            checking_id = deps.nessie.create_account(customer_id, f"{display_name} Checking", CHECKING_OPENING_DOLLARS)
            escrow_id = deps.nessie.create_account(customer_id, f"{display_name} StormCash Escrow", 0)
        except NessieError as exc:
            raise Unavailable(f"Nessie unavailable ({exc}); retry, or set NESSIE_DISABLED=1") from exc
    escrow_ref = escrow_id or (f"sim-{resident_id}" if simulated else "ledger-only")

    with deps.pool.connection() as conn:
        inserted = scalar(
            conn,
            """INSERT INTO residents (resident_id, display_name, holder_pub, region_id, nessie_customer_id,
                                      checking_account_id, escrow_account_id, simulated)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (holder_pub) DO NOTHING RETURNING resident_id""",
            (resident_id, display_name, holder_pub, region_id, customer_id, checking_id, escrow_id, simulated),
        )
        if inserted is None:  # lost a race with a concurrent registration
            return _existing_resident(conn, holder_pub)
        if contact:
            set_resident_contact(conn, resident_id, contact)
        cert = issue_cert(
            conn, deps.server_key, cert_id=cert_id, cert_ver=1, holder_pub=holder_pub,
            cap_cents=BASE_CAP_CENTS, now=now, escrow_ref=escrow_ref, resident_id=resident_id,
        )
        conn.execute(
            "INSERT INTO cert_status (cert_id, status, max_cap_cents) VALUES (%s, 'active', %s)",
            (cert_id, BASE_CAP_CENTS),
        )
        txn_id = _move(
            conn, debit=ledger.escrow(cert_id), credit=ledger.checking(resident_id), cents=BASE_CAP_CENTS,
            ref="lock escrow", nessie_from=checking_id, nessie_to=escrow_id,
            summary=f"Lock escrow, {display_name} checking → escrow",
        )
    if txn_id:
        deps.mover.execute(txn_id)
    return resident_id, cert, True


def _contact(contact: dict | None) -> dict | None:
    if contact is None:
        return None
    if contact.get("channel") not in CONTACT_CHANNELS:
        raise Invalid(f"contact.channel must be one of {', '.join(CONTACT_CHANNELS)}")
    handle = _string(contact.get("handle"), "contact.handle").strip()
    if not handle:
        raise Invalid("contact.handle is empty")
    return {"channel": contact["channel"], "handle": handle}


def set_resident_contact(conn: psycopg.Connection, resident_id: uuid.UUID, contact: dict) -> dict:
    """Point a Photon handle at a resident (one resident per handle, like merchant_contacts).
    The handle isn't verified: demo only; a real deployment would confirm it with a code."""
    contact = _contact(contact)
    conn.execute(
        """INSERT INTO resident_contacts (resident_id, channel, handle) VALUES (%s, %s, %s)
           ON CONFLICT (channel, handle) DO UPDATE SET resident_id = EXCLUDED.resident_id""",
        (resident_id, contact["channel"], contact["handle"]),
    )
    return contact


def _existing_resident(conn: psycopg.Connection, holder_pub: bytes) -> tuple[uuid.UUID, Cert, bool] | None:
    row = one(
        conn,
        """SELECT r.resident_id, c.cert_id FROM residents r
           JOIN certificates c ON c.resident_id = r.resident_id
           WHERE r.holder_pub = %s ORDER BY c.cert_ver DESC LIMIT 1""",
        (holder_pub,),
    )
    if row is None:
        return None
    return row["resident_id"], latest_cert(conn, bytes(row["cert_id"])), False


# Merchants -----------------------------------------------------------------------


def register_merchant(
    deps: Deps,
    display_name: str,
    merchant_pub: bytes,
    region_id: str | None,
    x: int | None = None,
    y: int | None = None,
    contact: dict | None = None,
    *,
    simulated: bool = False,
    now: int | None = None,
    merchant_id: bytes | None = None,
) -> tuple[bytes, Mcert, bool]:
    """Create a merchant (+ a $0 Nessie account for real ones) and issue an MCERT.
    `merchant_id` is only for the seeded simulator."""
    now = _now(now)
    display_name = _string(display_name, "display_name")
    region_id = _string(region_id, "region_id") or None
    _pub(merchant_pub, "merchant_pub")
    if contact is not None and contact.get("channel") not in CONTACT_CHANNELS:
        raise Invalid(f"contact.channel must be one of {', '.join(CONTACT_CHANNELS)}")

    with deps.pool.connection() as conn:
        row = one(conn, "SELECT * FROM merchants WHERE merchant_pub = %s", (merchant_pub,))
        if row:
            return bytes(row["merchant_id"]), issue_mcert(deps.server_key, row, now), False
        _check_region(conn, region_id)

    account_id = None
    if not simulated and deps.nessie is not None:
        try:
            customer_id = deps.nessie.create_customer(display_name, "StormCash merchant")
            account_id = deps.nessie.create_account(customer_id, display_name, 0)
        except NessieError as exc:
            raise Unavailable(f"Nessie unavailable ({exc}); retry, or set NESSIE_DISABLED=1") from exc

    merchant_id = merchant_id or crypto.random_id()
    with deps.pool.connection() as conn:
        row = one(
            conn,
            """INSERT INTO merchants (merchant_id, display_name, merchant_pub, region_id, x, y,
                                      nessie_account_id, simulated)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (merchant_pub) DO NOTHING RETURNING *""",
            (merchant_id, display_name, merchant_pub, region_id, x, y, account_id, simulated),
        )
        if row is None:
            row = one(conn, "SELECT * FROM merchants WHERE merchant_pub = %s", (merchant_pub,))
            return bytes(row["merchant_id"]), issue_mcert(deps.server_key, row, now), False
        if contact is not None:
            conn.execute(
                """INSERT INTO merchant_contacts (merchant_id, channel, handle) VALUES (%s, %s, %s)
                   ON CONFLICT (channel, handle) DO UPDATE SET merchant_id = EXCLUDED.merchant_id""",
                (merchant_id, contact["channel"], _string(contact.get("handle"), "contact.handle")),
            )
    return merchant_id, issue_mcert(deps.server_key, row, now), True


def register_simulated(
    deps: Deps, merchants: list[dict], residents: list[dict], *, now: int | None = None
) -> tuple[list[Mcert], list[Cert]]:
    """Register the seeded simulator's town in one transaction.

    Does what register_merchant and register_resident do for new simulated
    entities (no Nessie, ids from the seed), without a round trip per entity.
    `merchants` hold register_merchant's arguments (display_name, merchant_pub,
    region_id, x, y, merchant_id), `residents` register_resident's (display_name,
    holder_pub, region_id, cert_id). Keys already registered go through those
    functions, which return what exists."""
    now = _now(now)
    merchants = [{**m, "display_name": _string(m["display_name"], "display_name"),
                  "region_id": _string(m.get("region_id"), "region_id") or None} for m in merchants]
    residents = [{**r, "display_name": _string(r["display_name"], "display_name"),
                  "region_id": _string(r.get("region_id"), "region_id") or None} for r in residents]
    for m in merchants:
        _pub(m["merchant_pub"], "merchant_pub")
    for r in residents:
        _pub(r["holder_pub"], "holder_pub")
    mcerts: dict[int, Mcert] = {}
    certs: dict[int, Cert] = {}
    with pipelined(deps.pool) as conn:
        known_cur = conn.execute(
            "SELECT region_id FROM regions WHERE region_id = ANY(%s)",
            (sorted({e["region_id"] for e in merchants + residents if e["region_id"]}),),
        )
        taken_cur = conn.execute(
            """SELECT merchant_pub AS pub FROM merchants WHERE merchant_pub = ANY(%s)
               UNION ALL SELECT holder_pub FROM residents WHERE holder_pub = ANY(%s)""",
            ([m["merchant_pub"] for m in merchants], [r["holder_pub"] for r in residents]),
        )
        known = {r["region_id"] for r in known_cur.fetchall()}
        taken = {bytes(r["pub"]) for r in taken_cur.fetchall()}

        def check_region(region_id: str | None) -> None:
            if region_id and region_id not in known:
                raise Invalid(f"unknown region_id {region_id!r}")

        for i, m in enumerate(merchants):
            if m["merchant_pub"] in taken:
                continue
            check_region(m["region_id"])
            row = {**m, "merchant_id": m.get("merchant_id") or crypto.random_id()}
            conn.execute(
                """INSERT INTO merchants (merchant_id, display_name, merchant_pub, region_id, x, y, simulated)
                   VALUES (%s, %s, %s, %s, %s, %s, TRUE)""",
                (row["merchant_id"], row["display_name"], row["merchant_pub"], row["region_id"], row.get("x"),
                 row.get("y")),
            )
            mcerts[i] = issue_mcert(deps.server_key, row, now)
        for i, r in enumerate(residents):
            if r["holder_pub"] in taken:
                continue
            check_region(r["region_id"])
            resident_id = uuid.uuid4()
            cert_id = r.get("cert_id") or crypto.random_id()
            conn.execute(
                """INSERT INTO residents (resident_id, display_name, holder_pub, region_id, simulated)
                   VALUES (%s, %s, %s, %s, TRUE)""",
                (resident_id, r["display_name"], r["holder_pub"], r["region_id"]),
            )
            certs[i] = issue_cert(
                conn, deps.server_key, cert_id=cert_id, cert_ver=1, holder_pub=r["holder_pub"],
                cap_cents=BASE_CAP_CENTS, now=now, escrow_ref=f"sim-{resident_id}", resident_id=resident_id,
            )
            conn.execute(
                "INSERT INTO cert_status (cert_id, status, max_cap_cents) VALUES (%s, 'active', %s)",
                (cert_id, BASE_CAP_CENTS),
            )
            ledger.post(conn, ledger.escrow(cert_id), ledger.checking(resident_id), BASE_CAP_CENTS, "lock escrow")
    for i, m in enumerate(merchants):
        if i not in mcerts:
            mcerts[i] = register_merchant(deps, **m, simulated=True, now=now)[1]
    for i, r in enumerate(residents):
        if i not in certs:
            certs[i] = register_resident(deps, **r, simulated=True, now=now)[1]
    return [mcerts[i] for i in range(len(merchants))], [certs[i] for i in range(len(residents))]


# Storm Mode ----------------------------------------------------------------------


def _lock_cert(conn: psycopg.Connection, cert_id: bytes, caller_pub: bytes | None) -> tuple[dict, Cert, dict]:
    status = one(conn, "SELECT * FROM cert_status WHERE cert_id = %s FOR UPDATE", (cert_id,))
    latest = latest_cert(conn, cert_id) if status else None
    if latest is None:
        raise NotFound("unknown cert_id")
    if caller_pub is not None and caller_pub != latest.holder_pub:
        raise Forbidden("only the certificate holder can change Storm Mode")
    if status["status"] == "frozen":
        raise Conflict("certificate is frozen")
    resident = one(
        conn,
        """SELECT r.* FROM residents r JOIN certificates c ON c.resident_id = r.resident_id
           WHERE c.cert_id = %s LIMIT 1""",
        (cert_id,),
    )
    return status, latest, resident


def _nessie_accounts(deps: Deps, resident: dict) -> tuple[str | None, str | None]:
    if resident["simulated"] or deps.nessie is None:
        return None, None
    return resident["checking_account_id"], resident["escrow_account_id"]


def raise_storm_mode(
    deps: Deps, cert_id: bytes, cap_cents: int, *, caller_pub: bytes | None = None, now: int | None = None
) -> Cert:
    """Issue a new version at cap_cents and top escrow up so it covers the cap."""
    return raise_storm_mode_many(deps, [cert_id], cap_cents, caller_pub=caller_pub, now=now)[0]


def raise_storm_mode_many(
    deps: Deps, cert_ids: list[bytes], cap_cents: int, *, caller_pub: bytes | None = None, now: int | None = None
) -> list[Cert]:
    """raise_storm_mode for several certs in one transaction. Everything it reads
    is fetched in one round trip (the town simulator raises ~170 certs at once
    against a hosted database); certs are handled in order as if one by one."""
    now = _now(now)
    if not isinstance(cap_cents, int) or not BASE_CAP_CENTS < cap_cents <= MAX_CAP_CENTS:
        raise Invalid(f"cap_cents must be above {BASE_CAP_CENTS} and at most {MAX_CAP_CENTS}")
    certs, moves = [], []
    with pipelined(deps.pool) as conn:
        status_cur = conn.execute(
            "SELECT * FROM cert_status WHERE cert_id = ANY(%s) ORDER BY cert_id FOR UPDATE", (cert_ids,)
        )
        latest_cur = conn.execute(
            """SELECT DISTINCT ON (cert_id) * FROM certificates WHERE cert_id = ANY(%s)
               ORDER BY cert_id, cert_ver DESC""",
            (cert_ids,),
        )
        resident_cur = conn.execute(
            """SELECT DISTINCT ON (c.cert_id) c.cert_id AS for_cert, r.* FROM residents r
               JOIN certificates c ON c.resident_id = r.resident_id
               WHERE c.cert_id = ANY(%s) ORDER BY c.cert_id""",
            (cert_ids,),
        )
        paid_cur = conn.execute(
            """SELECT p.cert_id, COALESCE(SUM(po.amount_cents), 0) AS paid FROM payouts po
               JOIN payments p ON p.tag_hash = po.tag_hash
               WHERE p.cert_id = ANY(%s) AND po.source = 'escrow' GROUP BY p.cert_id""",
            (cert_ids,),
        )
        balances = ledger.balances(conn, [ledger.escrow(c) for c in cert_ids])
        statuses = {bytes(r["cert_id"]): r for r in status_cur.fetchall()}
        latest = {bytes(r["cert_id"]): cert_from_row(r) for r in latest_cur.fetchall()}
        residents = {bytes(r.pop("for_cert")): r for r in resident_cur.fetchall()}
        paid = {bytes(r["cert_id"]): r["paid"] for r in paid_cur.fetchall()}
        for cert_id in cert_ids:
            status, resident = _check_cert(statuses, latest, residents, cert_id, caller_pub)
            checking_id, escrow_id = _nessie_accounts(deps, resident)
            if escrow_id and not is_whole_dollars(cap_cents):
                raise Invalid("cap_cents must be whole dollars for a Nessie-backed resident")
            if status["storm_mode"] and latest[cert_id].cap_cents == cap_cents:
                certs.append(latest[cert_id])  # already there
                continue
            if cap_cents < latest[cert_id].cap_cents:
                raise Invalid("use /v1/storm-mode/close to lower the cap")
            # Escrow must cover what the new cap still allows: cap − already paid from escrow.
            top_up = cap_cents - paid.get(cert_id, 0) - balances[ledger.escrow(cert_id)]
            cert = issue_cert(
                conn, deps.server_key, cert_id=cert_id, cert_ver=latest[cert_id].cert_ver + 1,
                holder_pub=latest[cert_id].holder_pub, cap_cents=cap_cents, now=now,
                escrow_ref=latest[cert_id].escrow_ref, resident_id=resident["resident_id"],
            )
            conn.execute(
                """UPDATE cert_status SET status = 'active', storm_mode = TRUE, storm_mode_at = %s,
                          max_cap_cents = GREATEST(max_cap_cents, %s) WHERE cert_id = %s""",
                (now, cap_cents, cert_id),
            )
            # Keep what this loop read current, in case a cert is listed twice.
            statuses[cert_id] = {**status, "status": "active", "storm_mode": True}
            latest[cert_id] = cert
            if top_up > 0:
                balances[ledger.escrow(cert_id)] += top_up
                txn_id = _move(
                    conn, debit=ledger.escrow(cert_id), credit=ledger.checking(resident["resident_id"]),
                    cents=top_up, ref="storm mode top-up", nessie_from=checking_id, nessie_to=escrow_id,
                    summary=f"Storm Mode top-up, {resident['display_name']} checking → escrow",
                )
                if txn_id:
                    moves.append(txn_id)
            certs.append(cert)
    for txn_id in moves:
        deps.mover.execute(txn_id)
    return certs


def _check_cert(statuses: dict, latest: dict, residents: dict, cert_id: bytes,
                caller_pub: bytes | None) -> tuple[dict, dict]:
    status = statuses.get(cert_id)
    if status is None or cert_id not in latest:
        raise NotFound("unknown cert_id")
    if caller_pub is not None and caller_pub != latest[cert_id].holder_pub:
        raise Forbidden("only the certificate holder can change Storm Mode")
    if status["status"] == "frozen":
        raise Conflict("certificate is frozen")
    return status, residents.get(cert_id)


def close_storm_mode(deps: Deps, cert_id: bytes, *, caller_pub: bytes | None = None, now: int | None = None) -> Cert:
    """Issue a version back at the always-on cap. The escrow above it is refunded
    once every higher-cap version has expired plus a 24 h grace (§7.4)."""
    now = _now(now)
    with deps.pool.connection() as conn:
        status, latest, resident = _lock_cert(conn, cert_id, caller_pub)
        if not status["storm_mode"]:
            return latest
        cert = issue_cert(
            conn, deps.server_key, cert_id=cert_id, cert_ver=latest.cert_ver + 1, holder_pub=latest.holder_pub,
            cap_cents=BASE_CAP_CENTS, now=now, escrow_ref=latest.escrow_ref, resident_id=resident["resident_id"],
        )
        conn.execute(
            "UPDATE cert_status SET status = 'closing', storm_mode = FALSE WHERE cert_id = %s", (cert_id,)
        )
    return cert


def escrow_release_at(conn: psycopg.Connection, cert_id: bytes) -> int | None:
    """When the escrow above the current cap may be refunded, or None if nothing
    is above it."""
    versions = cert_versions(conn, cert_id)
    current = versions[-1].cap_cents
    higher = [v.expires_at for v in versions if v.cap_cents > current]
    return max(higher) + ESCROW_GRACE_S if higher else None


def release_due_escrows(deps: Deps, now: int | None = None) -> list[bytes]:
    """Refund escrow above what the current cap still needs, for every closing
    cert whose higher-cap versions have all expired plus the grace window."""
    now = _now(now)
    with deps.pool.connection() as conn:
        closing = [bytes(r["cert_id"]) for r in all_rows(conn, "SELECT cert_id FROM cert_status WHERE status = 'closing'")]
    released, moves = [], []
    for cert_id in closing:
        with deps.pool.connection() as conn:
            status = one(conn, "SELECT * FROM cert_status WHERE cert_id = %s FOR UPDATE", (cert_id,))
            if status is None or status["status"] != "closing":
                continue
            due = escrow_release_at(conn, cert_id)
            if due is not None and now < due:
                continue
            latest = latest_cert(conn, cert_id)
            resident = one(
                conn,
                "SELECT r.* FROM residents r JOIN certificates c ON c.resident_id = r.resident_id WHERE c.cert_id = %s LIMIT 1",
                (cert_id,),
            )
            keep = max(0, latest.cap_cents - paid_from_escrow(conn, cert_id))
            refund = ledger.balance(conn, ledger.escrow(cert_id)) - keep
            if refund > 0:
                checking_id, escrow_id = _nessie_accounts(deps, resident)
                txn_id = _move(
                    conn, debit=ledger.checking(resident["resident_id"]), credit=ledger.escrow(cert_id), cents=refund,
                    ref="refund on close", nessie_from=escrow_id, nessie_to=checking_id,
                    summary=f"Refund on close, {resident['display_name']} escrow → checking",
                )
                if txn_id:
                    moves.append(txn_id)
            conn.execute("UPDATE cert_status SET status = 'active' WHERE cert_id = %s", (cert_id,))
            released.append(cert_id)
    for txn_id in moves:
        deps.mover.execute(txn_id)
    return released

