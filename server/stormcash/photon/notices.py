"""Outbound notices (spec §17.2): hold notice on approval, settled notice on payout.

The hold notice uses StormDesk's `merchant_notice` draft only if every number in it can be found
in the flag's evidence (exposure, the candidate's frozen features, the action's parameters, the
window's hours). Otherwise it falls back to a template built from the flag alone, so a merchant
is never sent an invented number.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import one
from .client import send_to_merchant
from .config import PhotonSettings

DISPLAY_TZ = ZoneInfo("America/New_York")  # the demo table is in Boston; UIs show local time (§0 rule 8)
NOTICE_ACTIONS = ("hold_pool_payout", "lower_merchant_limit")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    return {_canon(m.group()) for m in _NUMBER.finditer(text)}


def _canon(token: str) -> str:
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def _add_number(out: set[str], value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    for form in (str(value), f"{value:.2f}", f"{value:.1f}", str(round(value)), str(int(value))):
        out.add(_canon(form))


def _clock_numbers(out: set[str], ts: int) -> None:
    t = datetime.fromtimestamp(ts, DISPLAY_TZ)
    hour12 = t.hour % 12 or 12
    for v in (t.hour, hour12, t.minute, t.strftime("%M")):
        out.add(_canon(str(v)))
    out.add(_canon(f"{hour12}:{t.strftime('%M')}"))
    out.add(_canon(f"{t.hour}:{t.strftime('%M')}"))


def allowed_numbers(flag: dict, candidate: dict | None) -> set[str]:
    out: set[str] = set()
    cents = [flag.get("exposure_cents") or 0]
    params = (flag.get("agent_transcript") or {}).get("action_params") or {}
    for k, v in params.items():
        if k.endswith("_cents") and isinstance(v, (int, float)):
            cents.append(v)
        _add_number(out, v)
    features = (candidate or {}).get("features") or {}
    for k, v in features.items():
        if k.endswith("_cents") and isinstance(v, (int, float)):
            cents.append(v)
        _add_number(out, v)
    for c in cents:
        if isinstance(c, (int, float)):
            _add_number(out, c / 100)
    if candidate:
        for ts in (candidate.get("window_start"), candidate.get("window_end")):
            if ts:
                _clock_numbers(out, int(ts))
        if candidate.get("window_start") and candidate.get("window_end"):
            _add_number(out, round((candidate["window_end"] - candidate["window_start"]) / 3600))
    return out


def draft_is_grounded(draft: str, flag: dict, candidate: dict | None) -> bool:
    return numbers_in(draft) <= allowed_numbers(flag, candidate)


def template_notice(name: str, flag: dict) -> str:
    params = (flag.get("agent_transcript") or {}).get("action_params") or {}
    if flag["proposed_action"] == "lower_merchant_limit" and isinstance(params.get("limit_cents"), int):
        return (f"{name}: your per-payment limit with StormCash is now ${params['limit_cents'] / 100:.2f} "
                "while a reviewer checks your shop's records. Reply here to explain.")
    return (f"{name}: your guarantee-pool payouts are on hold while a reviewer checks your shop's records. "
            "Reply here to explain.")


def compose_hold_notice(name: str, flag: dict, candidate: dict | None) -> tuple[str, bool]:
    """Returns (text, used_agent_draft)."""
    draft = (flag.get("agent_transcript") or {}).get("merchant_notice")
    if draft and draft.strip() and draft_is_grounded(draft, flag, candidate):
        return draft.strip(), True
    return template_notice(name, flag), False


def hold_notice(deps, settings: PhotonSettings, flag_id: int, transport=None) -> dict | None:
    """Send the notice for an approved hold / limit flag. Returns the message, or None if not applicable."""
    with deps.pool.connection() as conn:
        flag = one(conn, "SELECT * FROM flags WHERE flag_id = %s", (flag_id,))
        if flag is None or flag["proposed_action"] not in NOTICE_ACTIONS:
            return None
        candidate = one(conn, "SELECT * FROM candidates WHERE candidate_id = %s", (flag["candidate_id"],))
        try:
            merchant_id = bytes.fromhex(flag["subject_id"])
        except ValueError:
            return None
        merchant = one(conn, "SELECT display_name FROM merchants WHERE merchant_id = %s", (merchant_id,))
    if merchant is None:
        return None
    text, _ = compose_hold_notice(merchant["display_name"], flag, candidate)
    return send_to_merchant(deps, settings, merchant_id, text, flag_id, transport)


def settled_text(amount_cents: int, device_ts: int) -> str:
    t = datetime.fromtimestamp(device_ts, DISPLAY_TZ)
    return f"Paid: ${amount_cents / 100:.2f} from StormCash for payment at {t.strftime('%-I:%M %p')}."


def settled_notice(deps, settings: PhotonSettings, payout_id: int, transport=None) -> dict | None:
    """Template notice when a payout to a real merchant is executed (no agent involved)."""
    with deps.pool.connection() as conn:
        row = one(
            conn,
            """SELECT o.merchant_id, o.amount_cents, o.status, p.device_ts, m.simulated
               FROM payouts o JOIN payments p USING (tag_hash) JOIN merchants m ON m.merchant_id = o.merchant_id
               WHERE o.payout_id = %s""",
            (payout_id,),
        )
    if row is None or row["status"] != "executed" or row["simulated"]:
        return None
    return send_to_merchant(deps, settings, bytes(row["merchant_id"]),
                            settled_text(row["amount_cents"], row["device_ts"]), None, transport)
