"""Resident FREEZE by text (spec §17.2): a stolen phone's owner texts FREEZE from their registered handle.

Deterministic, never through StormDesk: the resident's certificate is frozen with the same code the
hard rules use (`cases.freeze_cert`: cert_status = frozen, a new signed POLICY, SSE `policy`), and
`cert_status.owner_freeze_at` records the request, which cap_drain reads as `owner_freeze_request`
(§13.2). Idempotent: a second FREEZE changes nothing and gets the same confirmation. Texting can't
unfreeze. An unknown handle gets a neutral reply and changes nothing.
"""

from __future__ import annotations

import logging
import time

from .. import cases
from ..db import all_rows, one, scalar
from ..settlement import _Ctx
from .client import record, reply
from .config import PhotonSettings

log = logging.getLogger(__name__)

CONFIRM = "Your StormCash wallet is frozen. Shops will refuse it as the freeze list spreads."
NO_WALLET = "There's no StormCash wallet on this account to freeze. Nothing was changed."
UNKNOWN = "This account isn't linked to a StormCash wallet, so nothing was changed."
HELP = "Text FREEZE to freeze your StormCash wallet. Texting can't unfreeze it."


def is_freeze(text: str) -> bool:
    return text.strip().casefold() == "freeze"


def resident_for_handle(conn, channel: str, handle: str) -> dict | None:
    return one(
        conn,
        """SELECT r.resident_id, r.display_name FROM resident_contacts c JOIN residents r USING (resident_id)
           WHERE c.channel = %s AND c.handle = %s""",
        (channel, handle),
    )


def freeze_resident(deps, resident_id, now: int | None = None) -> dict:
    """Freeze every certificate of the resident that isn't frozen yet and record the owner's request.
    Returns {cert_ids, newly_frozen, policy_ver}; cert_ids is empty when the resident has none."""
    now = int(time.time()) if now is None else now
    ctx = _Ctx(deps, b"", now, False)
    with deps.pool.connection() as conn:
        certs = [bytes(r["cert_id"]) for r in all_rows(
            conn,
            """SELECT s.cert_id FROM cert_status s
               WHERE s.status <> 'closed'
                 AND s.cert_id IN (SELECT cert_id FROM certificates WHERE resident_id = %s)
               ORDER BY s.cert_id FOR UPDATE""",
            (resident_id,),
        )]
        for cert_id in certs:
            cases.freeze_cert(ctx, conn, cert_id)  # no-op (and no new POLICY) if already frozen
        asked = [r["owner_freeze_at"] for r in all_rows(
            conn, """UPDATE cert_status SET owner_freeze_at = COALESCE(owner_freeze_at, %s) WHERE cert_id = ANY(%s)
                     RETURNING owner_freeze_at""", (now, certs))]
        policy_ver = scalar(conn, "SELECT max(policy_ver) FROM policy_versions")  # lists every frozen cert
    for event, data in ctx.events:
        deps.events.publish(event, data)
    result = {"resident_id": str(resident_id), "cert_ids": [c.hex() for c in certs],
              "newly_frozen": any(event == "policy" for event, _ in ctx.events), "policy_ver": policy_ver,
              "owner_freeze_at": min(asked, default=None)}
    if certs:
        deps.events.publish("owner_freeze", result)
    return result


def handle_inbound(deps, settings: PhotonSettings, channel: str, handle: str, text: str,
                   transport=None) -> dict | None:
    """A resident's text. Returns the webhook answer, or None when the sender isn't a resident and the
    text isn't FREEZE (the caller then tries the merchant flow)."""
    freeze = is_freeze(text)
    with deps.pool.connection() as conn:
        resident = resident_for_handle(conn, channel, handle)
        shop = scalar(conn, "SELECT 1 FROM merchant_contacts WHERE channel = %s AND handle = %s", (channel, handle))
    if not freeze and shop:  # one account can be a shop and a resident: only FREEZE is the resident's
        return None
    if resident is None:
        if not freeze:
            return None
        log.info("FREEZE from unknown %s handle %s", channel, handle)
        sent = reply(deps, settings, channel, handle, UNKNOWN, transport=transport)
        return {"ok": True, "freeze": "unknown sender", "reply": sent}

    resident_id = resident["resident_id"]
    record(deps, None, "in", channel, text, None, resident_id=resident_id)
    if not freeze:
        sent = reply(deps, settings, channel, handle, HELP, resident_id=resident_id, transport=transport)
        return {"ok": True, "resident_id": str(resident_id), "reply": sent}
    result = freeze_resident(deps, resident_id)
    sent = reply(deps, settings, channel, handle, CONFIRM if result["cert_ids"] else NO_WALLET,
                 resident_id=resident_id, transport=transport)
    return {"ok": True, "freeze": "frozen" if result["cert_ids"] else "no wallet", **result, "reply": sent}
