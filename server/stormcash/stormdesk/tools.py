"""StormDesk's tools (spec §14.3): read-only, in-process.

Plain functions over the database; runner.py exposes them to Droid as MCP
tools, and the fake runner calls them directly. Ids come back as lowercase
hex so the agent can cite exactly what it retrieved (§14.7). There is no
write tool: the agent's only output is its structured result.
"""

from __future__ import annotations

import datetime as dt
import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .. import ledger, registry
from ..db import all_rows, one, scalar
from ..protocol import rules
from ..protocol.objects import Dlog, Tag

LIMIT = 200


def hexify(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {k: hexify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [hexify(v) for v in value]
    if isinstance(value, dt.datetime):
        return int(value.timestamp())
    if isinstance(value, Decimal):
        return int(value)
    return value


def _hex(value: str, name: str) -> bytes:
    try:
        return bytes.fromhex(value.removeprefix("0x").strip())
    except (ValueError, AttributeError) as exc:
        raise ToolError(f"{name} must be hex") from exc


class ToolError(ValueError):
    """A bad argument; reported back to the agent as a tool error."""


def _window(since: int | None, until: int | None) -> tuple[int, int]:
    return since or 0, until or int(time.time()) + 365 * 86400


def _tag(row: dict) -> Tag:
    return Tag(bytes(row["cert_id"]), row["counter"], bytes(row["prev_hash"]), row["amount_cents"], row["cum_cents"],
               bytes(row["details_hash"]), bytes(row["sig"]))


def _device_pub(conn, device_id: str) -> bytes:
    """A device by its pub (33 bytes) or, for a shop, its merchant_id (16 bytes)."""
    raw = _hex(device_id, "device_id")
    if len(raw) == 33:
        return raw
    if len(raw) == 16:
        pub = scalar(conn, "SELECT merchant_pub FROM merchants WHERE merchant_id = %s", (raw,))
        if pub is not None:
            return bytes(pub)
    raise ToolError("device_id must be a device pub (66 hex) or a merchant_id (32 hex)")


# The tools -------------------------------------------------------------------------------


def get_case(conn, case_id: int) -> dict:
    """The hard case: rule, both tags, the cert, evidence ids and exposure."""
    row = one(conn, "SELECT * FROM cases WHERE case_id = %s", (case_id,))
    if row is None:
        raise ToolError(f"no case {case_id}")
    tags = [hexify({**r, "tag_hash": r["tag_hash"]}) for r in all_rows(
        conn, "SELECT * FROM tags WHERE tag_hash = ANY(%s)", ([h for h in (row["tag_a"], row["tag_b"]) if h],))]
    cert = registry.latest_cert(conn, bytes(row["cert_id"])) if row["cert_id"] else None
    return hexify({
        "case_id": row["case_id"], "rule": row["rule"], "detected_where": row["detected_where"],
        "exposure_cents": row["exposure_cents"], "cert_id": row["cert_id"], "merchant_id": row["merchant_id"],
        "device_pub": row["device_pub"], "tag_a": row["tag_a"], "tag_b": row["tag_b"], "evidence": row["evidence"],
        "tags": [{k: t[k] for k in ("tag_hash", "counter", "amount_cents", "cum_cents", "prev_hash", "details_hash")}
                 for t in tags],
        "cert": None if cert is None else {"cert_id": cert.cert_id, "cert_ver": cert.cert_ver,
                                           "cap_cents": cert.cap_cents, "holder_pub": cert.holder_pub},
    })


def get_candidate(conn, candidate_id: int) -> dict:
    """A soft candidate: kind, subject, window and the frozen features."""
    row = one(conn, "SELECT * FROM candidates WHERE candidate_id = %s", (candidate_id,))
    if row is None:
        raise ToolError(f"no candidate {candidate_id}")
    name = None
    if row["kind"] == "merchant_silence":
        name = scalar(conn, "SELECT display_name FROM merchants WHERE merchant_id = %s",
                      (bytes.fromhex(row["subject_id"]),))
    return hexify({k: row[k] for k in ("candidate_id", "kind", "subject_id", "window_start", "window_end", "features")}
                  | {"subject_name": name})


def get_cert_chain(conn, cert_id: str) -> dict:
    """All tags of a cert in counter order, its versions, status and settled total."""
    cid = _hex(cert_id, "cert_id")
    status = one(conn, "SELECT * FROM cert_status WHERE cert_id = %s", (cid,))
    if status is None:
        raise ToolError("unknown cert_id")
    tags = all_rows(
        conn,
        """SELECT t.tag_hash, t.counter, t.prev_hash, t.amount_cents, t.cum_cents, p.status AS payment_status,
                  p.device_ts, p.funded_escrow_cents, p.funded_pool_cents, m.merchant_id, m.display_name AS merchant
           FROM tags t LEFT JOIN payments p USING (tag_hash) LEFT JOIN merchants m ON m.merchant_id = p.merchant_id
           WHERE t.cert_id = %s ORDER BY t.counter, t.tag_hash LIMIT %s""",
        (cid, LIMIT),
    )
    versions = [{"cert_ver": c.cert_ver, "cap_cents": c.cap_cents, "issued_at": c.issued_at,
                 "expires_at": c.expires_at} for c in registry.cert_versions(conn, cid)]
    settled = sum(t["amount_cents"] for t in tags if t["payment_status"] == "settled")
    return hexify({"cert_id": cid, "status": status["status"], "max_cap_cents": status["max_cap_cents"],
                   "storm_mode": status["storm_mode"], "versions": versions, "tags": tags,
                   "settled_total_cents": settled})


def verify_tags(conn, tag_hashes: list[str]) -> dict:
    """Deterministic re-check: is each signature valid, and which rule (if any)
    does each pair break? Uses the same protocol code as the phones."""
    hashes = [_hex(h, "tag_hashes") for h in tag_hashes[:20]]
    rows = {bytes(r["tag_hash"]): r for r in all_rows(conn, "SELECT * FROM tags WHERE tag_hash = ANY(%s)", (hashes,))}
    out_tags, objs = [], {}
    for h in hashes:
        row = rows.get(h)
        if row is None:
            out_tags.append({"tag_hash": h.hex(), "found": False})
            continue
        tag = _tag(row)
        holder = scalar(conn, "SELECT holder_pub FROM certificates WHERE cert_id = %s LIMIT 1", (tag.cert_id,))
        objs[h] = tag
        out_tags.append({"tag_hash": h.hex(), "found": True, "recomputed_hash_matches": tag.tag_hash == h,
                         "signature_valid": holder is not None and tag.verify(bytes(holder))})
    pairs = [
        {"a": a.hex(), "b": b.hex(), "rules_broken": rules.rules_fired(objs[a], objs[b])}
        for a, b in itertools.combinations(objs, 2)
    ]
    return {"tags": out_tags, "pairs": pairs}


def get_device_log(conn, device_id: str, since: int | None = None, until: int | None = None) -> dict:
    """A device's signed log entries in a window, and whether that stretch of chain is intact."""
    pub = _device_pub(conn, device_id)
    lo, hi = _window(since, until)
    rows = all_rows(
        conn,
        """SELECT entry_hash, seq, ts, kind, body FROM device_log WHERE device_pub = %s AND ts BETWEEN %s AND %s
           ORDER BY seq LIMIT %s""",
        (pub, lo, hi, LIMIT),
    )
    entries = [Dlog.from_json(r["body"]) for r in rows]
    tamper = rules.log_tamper(entries) if entries else None
    summarized = []
    for e in entries:
        item = {"entry_hash": e.entry_hash, "seq": e.seq, "ts": e.ts, "kind": e.kind}
        if e.kind in ("ACCEPT", "REFUSE"):
            item |= {"tag_hash": e.tag_hash, "cert_id": e.cert_id}
            item |= {"held_ids": list(e.held_ids)} if e.kind == "ACCEPT" else {"check": e.check}
        else:
            item |= {"contact_id": e.contact_id, "peer_pub": e.peer_pub, "sent": len(e.sent_ids) + e.sent_overflow,
                     "received": len(e.recv_ids) + e.recv_overflow}
        summarized.append(item)
    return hexify({"device_pub": pub, "entries": summarized,
                   "chain": "intact" if tamper is None else {"problem": tamper.kind, "seq": tamper.seq}})


def get_contacts(conn, device_id: str, since: int | None = None, until: int | None = None) -> dict:
    """Contacts this device was in (either side's log), with paired flags and peers."""
    pub = _device_pub(conn, device_id)
    lo, hi = _window(since, until)
    rows = all_rows(
        conn,
        """SELECT contact_id, device_pub, peer_pub, ts, paired, cardinality(sent_ids) AS sent, cardinality(recv_ids) AS recv
           FROM contacts WHERE (device_pub = %s OR peer_pub = %s) AND ts BETWEEN %s AND %s ORDER BY ts LIMIT %s""",
        (pub, pub, lo, hi, LIMIT),
    )
    return hexify({"device_pub": pub, "contacts": [dict(r, logged_by="self" if bytes(r["device_pub"]) == pub
                                                         else "peer") for r in rows]})


def get_merchant_payments(conn, merchant_id: str, since: int | None = None, until: int | None = None) -> dict:
    """A shop's payments in a window with the escrow/pool split and the cert's status."""
    mid = _hex(merchant_id, "merchant_id")
    lo, hi = _window(since, until)
    rows = all_rows(
        conn,
        """SELECT p.tag_hash, p.cert_id, p.device_ts, p.status, p.funded_escrow_cents, p.funded_pool_cents, p.hops,
                  t.amount_cents, t.cum_cents, s.status AS cert_status
           FROM payments p JOIN tags t USING (tag_hash) JOIN cert_status s ON s.cert_id = p.cert_id
           WHERE p.merchant_id = %s AND p.device_ts BETWEEN %s AND %s ORDER BY p.device_ts LIMIT %s""",
        (mid, lo, hi, LIMIT),
    )
    shop = one(conn, "SELECT display_name, simulated, pool_eligible, region_id FROM merchants WHERE merchant_id = %s",
               (mid,))
    if shop is None:
        raise ToolError("unknown merchant_id")
    return hexify({"merchant_id": mid, **shop, "payments": rows})


def query_features(conn, entity: str, id: str, features: list[str] | None = None) -> dict:
    """Feature lookup (§15.2). Until the Chalk client is wired (WS6), this is the
    Postgres fallback (§22.4): the detectors' frozen features for this entity."""
    if entity not in ("merchant", "cert", "region"):
        raise ToolError("entity must be merchant, cert or region")
    row = one(
        conn,
        "SELECT kind, features, window_start, window_end FROM candidates WHERE subject_id = %s "
        "ORDER BY window_end DESC LIMIT 1",
        (id,),
    )
    values = dict(row["features"]) if row else {}
    if features:
        values = {k: values.get(k) for k in features}
    return {"source": "postgres_fallback", "entity": entity, "id": id, "features": values,
            "window": None if row is None else [row["window_start"], row["window_end"]]}


def get_region_status(conn, region_id: str) -> dict:
    """Active certs, expiries, last upload and alerts (live and replayed, labeled)."""
    if scalar(conn, "SELECT 1 FROM regions WHERE region_id = %s", (region_id,)) is None:
        raise ToolError("unknown region_id")
    now = scalar(conn, "SELECT max(device_ts) FROM payments") or int(time.time())
    certs = all_rows(
        conn,
        """SELECT DISTINCT ON (c.cert_id) c.cert_id, c.expires_at FROM certificates c
           JOIN residents r ON r.resident_id = c.resident_id WHERE r.region_id = %s ORDER BY c.cert_id, c.cert_ver DESC""",
        (region_id,),
    )
    active = [c for c in certs if c["expires_at"] > now]
    alerts = all_rows(conn, "SELECT alert_id, event, severity, onset, expires, source FROM weather_alerts "
                            "WHERE region_id = %s ORDER BY onset", (region_id,))
    last_upload = scalar(conn, "SELECT extract(epoch FROM max(received_at))::bigint FROM uploads WHERE region_id = %s",
                         (region_id,))
    return hexify({
        "region_id": region_id, "as_of": now, "active_certs": len(active),
        "expiring_12h": sum(1 for c in active if c["expires_at"] < now + 12 * 3600),
        "sample_cert_ids": [c["cert_id"] for c in active[:5]],
        "last_upload_at": last_upload, "alerts": alerts,
    })


def get_nessie_balances(conn, entity_id: str, deps=None) -> dict:
    """Balances for a demo entity: live Nessie for real ones, ledger for simulated ones."""
    raw = _hex(entity_id, "entity_id")
    shop = one(conn, "SELECT * FROM merchants WHERE merchant_id = %s", (raw,))
    if shop is not None:
        account, simulated = shop["nessie_account_id"], shop["simulated"]
        ledger_cents = ledger.balance(conn, ledger.merchant(raw))
    else:
        cert = scalar(conn, "SELECT resident_id FROM certificates WHERE cert_id = %s LIMIT 1", (raw,))
        if cert is None:
            raise ToolError("entity_id must be a merchant_id or cert_id")
        res = one(conn, "SELECT * FROM residents WHERE resident_id = %s", (cert,))
        account, simulated = res["escrow_account_id"], res["simulated"]
        ledger_cents = ledger.balance(conn, ledger.escrow(raw))
    nessie_cents = None
    if not simulated and account and deps is not None and deps.nessie is not None:
        nessie_cents = deps.nessie.balance_cents(account)
    return {"entity_id": entity_id, "simulated": simulated, "ledger_cents": ledger_cents,
            "nessie_cents": nessie_cents, "note": "simulated: ledger only" if simulated else "from Nessie transactions"}


def get_messages(conn, merchant_id: str) -> dict:
    """The Photon conversation with this shop so far."""
    rows = all_rows(conn, "SELECT message_id, direction, channel, body, created_at FROM messages "
                          "WHERE merchant_id = %s ORDER BY created_at LIMIT %s", (_hex(merchant_id, "merchant_id"), LIMIT))
    return hexify({"merchant_id": merchant_id, "messages": rows})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    function: Callable[..., dict]


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("get_case", "A hard case: rule, both tags, the cert, evidence ids, exposure.", get_case),
    ToolSpec("get_candidate", "A soft candidate: kind, subject, window and the frozen detector features.", get_candidate),
    ToolSpec("get_cert_chain", "All tags of a cert in counter order, versions, status and settled total.", get_cert_chain),
    ToolSpec("verify_tags", "Re-check tag signatures and which rule any pair breaks (deterministic).", verify_tags),
    ToolSpec("get_device_log", "A device's signed log entries in a time window and whether the chain is intact.",
             get_device_log),
    ToolSpec("get_contacts", "Contacts a device was in, with paired flags and peers.", get_contacts),
    ToolSpec("get_merchant_payments", "A shop's payments with the escrow/pool split and cert status.",
             get_merchant_payments),
    ToolSpec("query_features", "Features for a merchant, cert or region (Chalk; Postgres fallback).", query_features),
    ToolSpec("get_region_status", "A region's active certs, expiries, last upload and alerts (live/replayed).",
             get_region_status),
    ToolSpec("get_nessie_balances", "Balances for a demo entity (Nessie for real ones, ledger for simulated).",
             get_nessie_balances),
    ToolSpec("get_messages", "The Photon conversation with a shop so far.", get_messages),
)
TOOL_NAMES = tuple(t.name for t in TOOLS)


def call(deps, name: str, args: dict) -> dict:
    """Run one tool in its own read-only transaction."""
    spec = next((t for t in TOOLS if t.name == name), None)
    if spec is None:
        raise ToolError(f"unknown tool {name}")
    with deps.pool.connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")  # the database itself refuses any write
        if name == "get_nessie_balances":
            return spec.function(conn, deps=deps, **args)
        return spec.function(conn, **args)
