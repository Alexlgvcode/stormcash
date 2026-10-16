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


@router.get("/v1/cases")
def list_cases(request: Request, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(conn, "SELECT * FROM cases ORDER BY case_id DESC LIMIT %s", (limit,))
    return [jsonable(case_summary(r)) for r in rows]


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
