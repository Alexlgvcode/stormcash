"""Send a message to a merchant and record it (spec §17).

`send(channel, handle, text)` talks to the Node bridge (photon/bridge), which owns the Spectrum
SDK. `send_to_merchant` adds the bookkeeping: the merchant's handle from `merchant_contacts`,
a `messages` row and a `message` SSE event. A send that fails (or Photon switched off) is still
recorded, so the dashboard thread stays honest about what was and wasn't delivered.
"""

from __future__ import annotations

import logging

import httpx

from ..db import one
from .config import PhotonSettings

log = logging.getLogger(__name__)

TIMEOUT_S = 10.0


class SendError(RuntimeError):
    pass


def send(settings: PhotonSettings, channel: str, handle: str, text: str,
         transport: httpx.BaseTransport | None = None) -> None:
    """Deliver one text through Photon. Raises SendError when it can't."""
    if not settings.can_send:
        raise SendError("Photon sending is switched off (PHOTON_DISABLED or no PHOTON_BRIDGE_TOKEN)")
    try:
        with httpx.Client(timeout=TIMEOUT_S, transport=transport or settings.transport) as http:
            res = http.post(f"{settings.bridge_url}/send",
                            headers={"Authorization": f"Bearer {settings.bridge_token}"},
                            json={"channel": channel, "handle": handle, "text": text})
    except httpx.HTTPError as exc:
        raise SendError(f"bridge unreachable: {exc}") from exc
    if res.status_code != 200:
        raise SendError(f"bridge answered {res.status_code}: {res.text[:200]}")


def merchant_contact(conn, merchant_id: bytes) -> dict | None:
    return one(conn, "SELECT channel, handle FROM merchant_contacts WHERE merchant_id = %s ORDER BY channel LIMIT 1",
               (merchant_id,))


def record(deps, merchant_id: bytes, direction: str, channel: str, body: str, flag_id: int | None,
           delivered: bool | None = None, error: str | None = None) -> dict:
    with deps.pool.connection() as conn:
        row = one(
            conn,
            """INSERT INTO messages (merchant_id, flag_id, direction, channel, body)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (merchant_id, flag_id, direction, channel, body),
        )
    event = {**row, "merchant_id": merchant_id.hex()}
    if direction == "out":
        event.update(delivered=delivered, error=error)
    deps.events.publish("message", event)
    return event


def send_to_merchant(deps, settings: PhotonSettings, merchant_id: bytes, text: str, flag_id: int | None = None,
                     transport: httpx.BaseTransport | None = None) -> dict:
    """Send `text` to the merchant's registered handle; returns the recorded message."""
    with deps.pool.connection() as conn:
        contact = merchant_contact(conn, merchant_id)
    if contact is None:
        return record(deps, merchant_id, "out", "none", text, flag_id, False, "merchant has no contact handle")
    try:
        send(settings, contact["channel"], contact["handle"], text, transport)
        return record(deps, merchant_id, "out", contact["channel"], text, flag_id, True)
    except SendError as exc:
        log.warning("Photon send to %s failed: %s", merchant_id.hex(), exc)
        return record(deps, merchant_id, "out", contact["channel"], text, flag_id, False, str(exc))
