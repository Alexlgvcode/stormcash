"""Appeals (spec §17.2, #37): a merchant's reply runs the StormDesk `respond` job.

The agent's reply is sent only if it cites at least one id and every cited id exists (§14.7);
otherwise the merchant gets a neutral acknowledgement and a person reviews the thread. An
`escalate` answer leaves the flag open with the appeal attached (the messages carry flag_id).
"""

from __future__ import annotations

import asyncio
import logging

from ..stormdesk.runner import Job
from .client import send_to_merchant
from .config import PhotonSettings

log = logging.getLogger(__name__)

FALLBACK_REPLY = "Thanks. Your reply is attached to the review, and a person will look at it."


def pick_reply(result: dict) -> tuple[str, bool]:
    """(text to send, whether it is the agent's own reply)."""
    out = result.get("output") or {}
    if result.get("status") == "succeeded" and result.get("citations_valid") and out.get("evidence_ids") \
            and (out.get("reply") or "").strip():
        return out["reply"].strip(), True
    return FALLBACK_REPLY, False


async def respond(app, settings: PhotonSettings, merchant_id: bytes, text: str, flag_id: int | None,
                  transport=None) -> dict:
    deps = app.state.deps
    try:
        result = await app.state.stormdesk.run(Job("respond", merchant_id=merchant_id.hex(), message=text))
    except Exception as exc:  # StormDesk down: still acknowledge, a person reviews
        log.exception("respond job failed")
        result = {"status": "failed", "error": str(exc)}
    reply, from_agent = pick_reply(result)
    message = await asyncio.to_thread(send_to_merchant, deps, settings, merchant_id, reply, flag_id, transport)
    out = result.get("output") or {}
    deps.events.publish("appeal", {
        "merchant_id": merchant_id.hex(), "flag_id": flag_id, "run_id": result.get("run_id"),
        "from_agent": from_agent, "escalate": bool(out.get("escalate", True)),
        "claim_consistent_with_logs": out.get("claim_consistent_with_logs"),
        "evidence_ids": out.get("evidence_ids", []),
    })
    return {"reply": message, "from_agent": from_agent, "run": result}
