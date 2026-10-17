"""GET /v1/cases, /v1/cases/{id}, /v1/proof/{case_id}, /v1/policy (spec §12.1, §18.3, §18.6)."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request

from .. import registry
from ..cases import case_summary
from ..db import all_rows, one
from ..jsonutil import jsonable
from ..protocol.objects import Dlog, Tag, b64u_encode
from ..settlement import current_policy, tag_from_row

router = APIRouter()


def _signed(obj) -> dict:
    """An object with what a browser needs to verify it: transport JSON plus the
    canonical string (WebCrypto ECDSA-SHA256 over its UTF-8 bytes)."""
    return {"type": obj.TYPE, "json": obj.to_json(), "fields": obj.to_fields(), "canonical": obj.canonical(),
            "digest": obj.digest().hex()}


def _case(conn, case_id: int) -> dict:
    row = one(conn, "SELECT * FROM cases WHERE case_id = %s", (case_id,))
    if row is None:
        raise HTTPException(404, "no such case")
    return row


def _tag(conn, tag_hash) -> Tag | None:
    if tag_hash is None:
        return None
    row = one(conn, "SELECT * FROM tags WHERE tag_hash = %s", (tag_hash,))
    return None if row is None else tag_from_row(row)


def _detail(conn, row: dict) -> dict:
    tags = {k: _tag(conn, row[k]) for k in ("tag_a", "tag_b")}
    cert = registry.latest_cert(conn, bytes(row["cert_id"])) if row["cert_id"] else None
    entries: list[Dlog] = []
    if row["rule"] == "MERCHANT_KNEW" and row["device_pub"] is not None:
        entries = [Dlog.from_json(r["body"]) for r in all_rows(
            conn,
            """SELECT body FROM device_log WHERE device_pub = %s AND kind = 'ACCEPT' AND body->>'th' = %s
               ORDER BY seq""",
            (row["device_pub"], b64u_encode(bytes(row["tag_b"]))),
        )]
    elif row["rule"] == "LOG_TAMPER":
        hashes = [bytes.fromhex(h) for h in row["evidence"].get("entries", [])]
        entries = [Dlog.from_json(r["body"]) for r in all_rows(
            conn, "SELECT body FROM device_log WHERE entry_hash = ANY(%s) ORDER BY seq", (hashes,)
        )]
    return {
        "case": jsonable({**case_summary(row), "evidence": row["evidence"], "case_file_md": row["case_file_md"]}),
        "cert": None if cert is None else _signed(cert),
        "tag_a": None if tags["tag_a"] is None else _signed(tags["tag_a"]),
        "tag_b": None if tags["tag_b"] is None else _signed(tags["tag_b"]),
        "holder_pub": None if cert is None else b64u_encode(cert.holder_pub),
        "log_entries": [_signed(e) for e in entries],
    }


# What the dashboard says about each case in plain words (§18.3 [v4.23]): which shop took
# each payment, its amount and number, and whether the case is the simulated town's.
LIST_SQL = """
SELECT c.*,
  (SELECT r.simulated FROM certificates ce JOIN residents r ON r.resident_id = ce.resident_id
    WHERE ce.cert_id = c.cert_id LIMIT 1) AS resident_simulated,
  m.display_name AS case_merchant, m.simulated AS case_merchant_simulated,
  ta.counter AS a_counter, ta.amount_cents AS a_amount, pa.status AS a_status,
  ma.display_name AS a_merchant, ma.simulated AS a_simulated,
  tb.counter AS b_counter, tb.amount_cents AS b_amount, pb.status AS b_status,
  mb.display_name AS b_merchant, mb.simulated AS b_simulated
FROM cases c
LEFT JOIN merchants m ON m.merchant_id = c.merchant_id
LEFT JOIN tags ta ON ta.tag_hash = c.tag_a
LEFT JOIN payments pa ON pa.tag_hash = c.tag_a
LEFT JOIN merchants ma ON ma.merchant_id = pa.merchant_id
LEFT JOIN tags tb ON tb.tag_hash = c.tag_b
LEFT JOIN payments pb ON pb.tag_hash = c.tag_b
LEFT JOIN merchants mb ON mb.merchant_id = pb.merchant_id
ORDER BY c.case_id DESC LIMIT %s"""


def _payment(row: dict, side: str) -> dict | None:
    if row[f"{side}_counter"] is None:
        return None
    return {"counter": row[f"{side}_counter"], "amount_cents": row[f"{side}_amount"], "status": row[f"{side}_status"],
            "merchant": row[f"{side}_merchant"], "simulated": row[f"{side}_simulated"]}


@router.get("/v1/cases")
def list_cases(request: Request, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(conn, LIST_SQL, (limit,))
    return [jsonable({
        **case_summary(r),
        "simulated": bool(r["resident_simulated"] or r["case_merchant_simulated"] or r["a_simulated"]
                          or r["b_simulated"]),
        "merchant": r["case_merchant"],
        "payment_a": _payment(r, "a"),
        "payment_b": _payment(r, "b"),
    }) for r in rows]


@router.get("/v1/cases/{case_id}")
def get_case(case_id: int, request: Request) -> dict:
    with request.app.state.deps.pool.connection() as conn:
        return _detail(conn, _case(conn, case_id))


@router.get("/v1/proof/{case_id}")
def get_proof(case_id: int, request: Request) -> dict:
    """Everything the public verify page needs: the server-signed cert, both
    tags, holder_pub and the rule. The page should check the cert against the
    server key it already knows, not the one echoed here."""
    deps = request.app.state.deps
    with deps.pool.connection() as conn:
        row = _case(conn, case_id)
        detail = _detail(conn, row)
    if detail["tag_a"] is None or detail["tag_b"] is None:
        raise HTTPException(404, "this case has no tag pair to verify")
    return {
        "case_id": case_id,
        "rule": row["rule"],
        "server_pub": b64u_encode(deps.settings.server_pub),
        **{k: detail[k] for k in ("cert", "tag_a", "tag_b", "holder_pub", "log_entries")},
    }


@router.get("/v1/policy")
def get_policy(request: Request, since: int = Query(0, ge=0)) -> dict:
    """The latest signed POLICY, or null when the caller already has it."""
    deps = request.app.state.deps
    with deps.pool.connection() as conn:
        policy = current_policy(conn, deps.server_key, int(time.time()))
    return {"policy": policy.to_json() if policy.policy_ver > since else None}
