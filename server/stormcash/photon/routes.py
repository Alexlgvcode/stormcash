"""Photon routes (spec §12.1, §17): inbound webhook, a shop's thread, and a manual notice trigger."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict

from fastapi import APIRouter, Header, HTTPException, Query, Request

from ..db import all_rows, one, scalar
from ..jsonutil import jsonable
from ..routes.demo import require_operator
from . import appeal, client, notices
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
    """Photon (Spectrum) webhook. Verifies the signature, records the merchant's message and
    starts the StormDesk respond job; the reply goes out when it finishes."""
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
def thread(request: Request, merchant_id: str, limit: int = Query(100, ge=1, le=500)) -> dict:
    """A shop's Photon conversation, oldest first (dashboard thread)."""
    try:
        mid = bytes.fromhex(merchant_id)
    except ValueError:
        raise HTTPException(400, "merchant_id must be hex")
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(
            conn,
            """SELECT * FROM (SELECT * FROM messages WHERE merchant_id = %s ORDER BY message_id DESC LIMIT %s) m
               ORDER BY message_id""",
            (mid, limit),
        )
    return jsonable({"merchant_id": merchant_id, "messages": [{**r, "merchant_id": merchant_id} for r in rows]})


@router.post("/v1/photon/notify/{flag_id}")
async def notify(flag_id: int, request: Request, x_sc_operator: str | None = Header(None)) -> dict:
    """Send the hold notice for a flag now (operator). The approval route calls notices.hold_notice too."""
    require_operator(x_sc_operator)
    message = await asyncio.to_thread(notices.hold_notice, request.app.state.deps, settings(request), flag_id)
    if message is None:
        raise HTTPException(409, "this flag has no merchant notice (wrong action or unknown merchant)")
    return jsonable(message)
