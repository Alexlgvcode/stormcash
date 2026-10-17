"""Photon routes (spec §12.1, §17): inbound webhook (shop appeals, resident FREEZE), threads, a manual
notice trigger, and the operator's way to give a resident a Photon handle."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections import OrderedDict

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from .. import registry
from ..db import all_rows, one, scalar
from ..jsonutil import jsonable
from ..routes.demo import require_operator
from . import appeal, client, freeze, notices
from .config import PhotonSettings, load

log = logging.getLogger(__name__)
router = APIRouter()

SIGNATURE_TOLERANCE_S = 300  # Spectrum webhooks: reject timestamps more than 5 minutes off
SEEN_MAX = 2000  # deliveries are at-least-once; remember recent message ids


def settings(request: Request) -> PhotonSettings:
    if not hasattr(request.app.state, "photon"):
        request.app.state.photon = load()
    return request.app.state.photon


def verify_signature(secret: str, raw: bytes, timestamp: str | None, signature: str | None, now: int) -> bool:
    """Spectrum webhook signature: `v0=` + hex HMAC-SHA256 over `v0:{timestamp}:{raw body}`."""
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(now - ts) > SIGNATURE_TOLERANCE_S:
        return False
    expected = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _seen(request: Request, message_id: str) -> bool:
    seen: OrderedDict = getattr(request.app.state, "photon_seen", None) or OrderedDict()
    request.app.state.photon_seen = seen
    if message_id in seen:
        return True
    seen[message_id] = True
    while len(seen) > SEEN_MAX:
        seen.popitem(last=False)
    return False


def _open_flag(conn, merchant_id: bytes) -> int | None:
    """The merchant's most recent flag that could have produced a notice."""
    return scalar(
        conn,
        """SELECT flag_id FROM flags WHERE subject_id = %s AND proposed_action = ANY(%s)
           AND status IN ('open', 'approved') ORDER BY flag_id DESC LIMIT 1""",
        (merchant_id.hex(), list(notices.NOTICE_ACTIONS)),
    )


@router.post("/v1/photon/inbound")
async def inbound(request: Request) -> dict:
    """Photon (Spectrum) webhook. Verifies the signature. A resident's FREEZE freezes their wallet
    deterministically and is confirmed by text (photon/freeze.py, no agent). A shop's message is
    recorded and starts the StormDesk respond job; the reply goes out when it finishes."""
    cfg = settings(request)
    raw = await request.body()
    if not cfg.allow_unsigned:
        if not cfg.webhook_secret:
            raise HTTPException(500, "SPECTRUM_WEBHOOK_SECRET is not set")
        if not verify_signature(cfg.webhook_secret, raw, request.headers.get("x-spectrum-timestamp"),
                                request.headers.get("x-spectrum-signature"), int(time.time())):
            raise HTTPException(401, "bad webhook signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "body is not JSON")
    message = payload.get("message") or {}
    content = message.get("content") or {}
    if payload.get("event") != "messages" or content.get("type") != "text" or message.get("direction") != "inbound":
        return {"ok": True, "ignored": "not an inbound text message"}
    if _seen(request, str(message.get("id"))):
        return {"ok": True, "ignored": "duplicate delivery"}

    channel = str(message.get("platform") or (payload.get("space") or {}).get("platform") or "").lower()
    handle = str((message.get("sender") or {}).get("id") or "")
    text = str(content.get("text") or "").strip()
    deps = request.app.state.deps
    if text:
        answer = await asyncio.to_thread(freeze.handle_inbound, deps, cfg, channel, handle, text)
        if answer is not None:
            return jsonable(answer)
    with deps.pool.connection() as conn:
        row = one(conn, "SELECT merchant_id FROM merchant_contacts WHERE channel = %s AND handle = %s",
                  (channel, handle))
        if row is None or not text:
            return {"ok": True, "ignored": "unknown sender"}
        merchant_id = bytes(row["merchant_id"])
        flag_id = _open_flag(conn, merchant_id)
    await asyncio.to_thread(client.record, deps, merchant_id, "in", channel, text, flag_id)
    task = asyncio.create_task(appeal.respond(request.app, cfg, merchant_id, text, flag_id))
    request.app.state.photon_tasks = {t for t in getattr(request.app.state, "photon_tasks", set()) if not t.done()}
    request.app.state.photon_tasks.add(task)
    return {"ok": True, "merchant_id": merchant_id.hex(), "flag_id": flag_id}


@router.get("/v1/photon/messages")
def thread(request: Request, merchant_id: str | None = None, resident_id: str | None = None,
           limit: int = Query(100, ge=1, le=500)) -> dict:
    """A shop's or a resident's Photon conversation, oldest first (dashboard thread)."""
    if (merchant_id is None) == (resident_id is None):
        raise HTTPException(400, "give exactly one of merchant_id or resident_id")
    try:
        column, key = ("merchant_id", bytes.fromhex(merchant_id)) if merchant_id is not None \
            else ("resident_id", uuid.UUID(resident_id))
    except ValueError:
        raise HTTPException(400, "merchant_id must be hex, resident_id a UUID")
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(
            conn,
            f"""SELECT * FROM (SELECT * FROM messages WHERE {column} = %s ORDER BY message_id DESC LIMIT %s) m
               ORDER BY message_id""",
            (key, limit),
        )
    if merchant_id is not None:
        return jsonable({"merchant_id": merchant_id, "messages": [{**r, "merchant_id": merchant_id} for r in rows]})
    return jsonable({"resident_id": resident_id, "messages": rows})


class ResidentContactIn(BaseModel):
    resident_id: str | None = None
    display_name: str | None = None  # a real (not simulated) resident's exact name, e.g. "Maya"
    channel: str
    handle: str


@router.post("/v1/photon/resident-contact")
def resident_contact(body: ResidentContactIn, request: Request, x_sc_operator: str | None = Header(None)) -> dict:
    """Operator (demo): give a resident the Photon handle that may text FREEZE (§17.2)."""
    require_operator(x_sc_operator)
    if (body.resident_id is None) == (body.display_name is None):
        raise HTTPException(400, "give exactly one of resident_id or display_name")
    with request.app.state.deps.pool.connection() as conn:
        if body.resident_id is not None:
            try:
                rows = all_rows(conn, "SELECT resident_id, display_name FROM residents WHERE resident_id = %s",
                                (uuid.UUID(body.resident_id),))
            except ValueError:
                raise HTTPException(400, "resident_id must be a UUID")
        else:
            rows = all_rows(conn, """SELECT resident_id, display_name FROM residents
                                     WHERE NOT simulated AND display_name = %s""", (body.display_name,))
        if len(rows) != 1:
            raise HTTPException(404 if not rows else 409,
                                f"{len(rows)} residents match; give resident_id" if rows else "no such resident")
        contact = registry.set_resident_contact(conn, rows[0]["resident_id"],
                                                {"channel": body.channel, "handle": body.handle})
    return jsonable({**rows[0], **contact})


@router.get("/v1/photon/freezes")
def owner_freezes(request: Request, cert_id: str | None = None, limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    """Certificates whose owner texted FREEZE, newest first, with the first POLICY that listed each."""
    try:
        cid = None if cert_id is None else bytes.fromhex(cert_id)
    except ValueError:
        raise HTTPException(400, "cert_id must be hex")
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(
            conn,
            """SELECT s.cert_id, s.status, s.frozen_at, s.owner_freeze_at, r.resident_id, r.display_name,
                      (SELECT min(policy_ver) FROM policy_versions p WHERE s.cert_id = ANY(p.frozen_certs)) AS policy_ver
               FROM cert_status s
               JOIN residents r ON r.resident_id = (SELECT resident_id FROM certificates c
                                                    WHERE c.cert_id = s.cert_id LIMIT 1)
               WHERE s.owner_freeze_at IS NOT NULL AND (%s::bytea IS NULL OR s.cert_id = %s)
               ORDER BY s.owner_freeze_at DESC LIMIT %s""",
            (cid, cid, limit),
        )
    return jsonable([{**r, "cert_id": bytes(r["cert_id"]).hex()} for r in rows])


@router.post("/v1/photon/notify/{flag_id}")
async def notify(flag_id: int, request: Request, x_sc_operator: str | None = Header(None)) -> dict:
    """Send the hold notice for a flag now (operator). The approval route calls notices.hold_notice too."""
    require_operator(x_sc_operator)
    message = await asyncio.to_thread(notices.hold_notice, request.app.state.deps, settings(request), flag_id)
    if message is None:
        raise HTTPException(409, "this flag has no merchant notice (wrong action or unknown merchant)")
    return jsonable(message)
