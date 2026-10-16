"""Signed API writes (spec §12).

A resident or merchant write carries:
    X-SC-Pub  base64url SEC1 compressed key (33 bytes)
    X-SC-Ts   Unix seconds, within ±600 s of the server clock
    X-SC-Sig  base64url raw r||s over SHA-256(canonical(API, path, body_sha256, ts))
where path is the URL path (string), body_sha256 the SHA-256 of the raw body
bytes (bytes32, lowercase hex in the canonical string) and ts an integer.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Request

from .protocol import crypto, encoding
from .protocol.encoding import EncodingError
from .protocol.objects import b64u_decode, b64u_encode

TOLERANCE_S = 600


def api_canonical(path: str, body: bytes, ts: int) -> str:
    return encoding.canonical(
        "API",
        [
            encoding.render_string(path),
            encoding.render_bytes(encoding.sha256(body), 32),
            encoding.render_int(ts),
        ],
    )


def sign_request(key, path: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    """Headers for a signed request (used by tests, the simulator and tools)."""
    ts = int(time.time()) if ts is None else ts
    sig = crypto.sign_digest(key, encoding.digest(api_canonical(path, body, ts)))
    return {
        "X-SC-Pub": b64u_encode(crypto.public_key_bytes(key)),
        "X-SC-Ts": str(ts),
        "X-SC-Sig": b64u_encode(sig),
    }


async def signer_pub(request: Request) -> bytes | None:
    """FastAPI dependency: the verified X-SC-Pub, or None when signatures are
    switched off (API_SIG_REQUIRED=0) and the request carries no key."""
    required = request.app.state.deps.settings.api_sig_required
    headers = request.headers
    pub_h, ts_h, sig_h = headers.get("x-sc-pub"), headers.get("x-sc-ts"), headers.get("x-sc-sig")
    if not required and pub_h is None:
        return None
    if not (pub_h and ts_h and sig_h):
        raise HTTPException(401, "missing X-SC-Pub / X-SC-Ts / X-SC-Sig")
    try:
        pub = b64u_decode(pub_h)
        sig = b64u_decode(sig_h)
        ts = int(ts_h)
        message = api_canonical(request.url.path, await request.body(), ts)
    except (EncodingError, ValueError) as exc:
        raise HTTPException(401, "malformed signature headers") from exc
    if not required:
        return pub
    if abs(time.time() - ts) > TOLERANCE_S:
        raise HTTPException(401, "X-SC-Ts outside the 10-minute window")
    if not crypto.verify_digest(pub, encoding.digest(message), sig):
        raise HTTPException(401, "bad request signature")
    return pub
