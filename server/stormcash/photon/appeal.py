"""Appeals (spec §17.2, #37): a merchant's reply runs the StormDesk `respond` job.

The agent's reply is sent only if it cites at least one id and every cited id exists (§14.7);
otherwise the merchant gets a neutral acknowledgement and a person reviews the thread. An
`escalate` answer leaves the flag open with the appeal attached (the messages carry flag_id).

With STORMDESK_APPEAL_SESSIONS on (the default), an appeal thread (merchant + flag) is one
conversation: one Droid session, resumed for each new text (stormdesk/service.py). A thread's
turns run one at a time, so each turn knows what the shop was actually sent before it. Off: one
fresh run per message, as before.
"""

from __future__ import annotations

import asyncio
import logging

from ..stormdesk.runner import Job
from ..stormdesk.service import appeal_reply_sent
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


def _thread_lock(app, merchant_id: bytes, flag_id: int | None) -> asyncio.Lock:
    locks = getattr(app.state, "appeal_locks", None)
    if locks is None:
        locks = app.state.appeal_locks = {}
    return locks.setdefault((merchant_id, flag_id), asyncio.Lock())


async def respond(app, settings: PhotonSettings, merchant_id: bytes, text: str, flag_id: int | None,
                  transport=None, in_message_id: int | None = None) -> dict:
    deps = app.state.deps
    if deps.settings.stormdesk_appeal_sessions:
        async with _thread_lock(app, merchant_id, flag_id):  # one turn at a time in the thread's session
            return await _respond(app, settings, merchant_id, text, flag_id, transport, in_message_id, "session")
    return await _respond(app, settings, merchant_id, text, flag_id, transport, in_message_id, "per_message")


async def _respond(app, settings: PhotonSettings, merchant_id: bytes, text: str, flag_id: int | None, transport,
                   in_message_id: int | None, mode: str) -> dict:
    deps = app.state.deps
    job = Job("respond", merchant_id=merchant_id.hex(), message=text,
              appeal={"mode": mode, "flag_id": flag_id, "in_message_id": in_message_id})
    try:
        result = await app.state.stormdesk.run(job)
    except Exception as exc:  # StormDesk down: still acknowledge, a person reviews
        log.exception("respond job failed")
        result = {"status": "failed", "error": str(exc)}
    reply, from_agent = pick_reply(result)
    message = await asyncio.to_thread(send_to_merchant, deps, settings, merchant_id, reply, flag_id, transport)
    if result.get("run_id") is not None:
        await asyncio.to_thread(appeal_reply_sent, deps, result["run_id"], message.get("message_id"), from_agent)
    out = result.get("output") or {}
    turn = result.get("appeal") or {}
    deps.events.publish("appeal", {
        "merchant_id": merchant_id.hex(), "flag_id": flag_id, "run_id": result.get("run_id"),
        "from_agent": from_agent, "escalate": bool(out.get("escalate", True)),
        "claim_consistent_with_logs": out.get("claim_consistent_with_logs"),
        "evidence_ids": out.get("evidence_ids", []),
        "session_id": result.get("session_id"), "session": turn.get("session"), "turn": turn.get("turn"),
    })
    return {"reply": message, "from_agent": from_agent, "run": result}
