"""WS7 #31/#37: Photon notices, the inbound webhook and the appeal reply (spec §17)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest
from psycopg.types.json import Jsonb

from stormcash.db import all_rows, one, scalar
from stormcash.photon import notices, routes
from stormcash.photon.appeal import FALLBACK_REPLY, pick_reply
from stormcash.photon.config import PhotonSettings
from stormcash.protocol.objects import b64u_encode

from .world import CORNER, World, pub

SECRET = "whsec-test"
HANDLE = "777000111"
OPERATOR = {"X-SC-Operator": "test"}


class Bridge:
    """Stands in for photon/bridge: records every /send."""

    def __init__(self, status: int = 200) -> None:
        self.sent: list[dict] = []
        self.status = status

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/send"
        assert request.headers["authorization"] == "Bearer bridge-token"
        self.sent.append(json.loads(request.content))
        return httpx.Response(self.status, json={"ok": self.status == 200})


@pytest.fixture
def bridge() -> Bridge:
    return Bridge()


@pytest.fixture
def photon(app_client, bridge) -> PhotonSettings:
    cfg = PhotonSettings(bridge_token="bridge-token", webhook_secret=SECRET, transport=httpx.MockTransport(bridge.handle))
    app_client.app.include_router(routes.router)
    app_client.app.state.photon = cfg
    return cfg


@pytest.fixture
def corner(app_client, photon) -> bytes:
    """Corner Store, registered with its owner's Telegram handle."""
    world = World(app_client)
    out = world.post("/v1/merchants/register",
                     {"display_name": "Corner Store", "merchant_pub": b64u_encode(pub(CORNER)),
                      "region_id": "asheville-downtown", "contact": {"channel": "telegram", "handle": HANDLE}},
                     CORNER)
    with app_client.app.state.deps.pool.connection() as conn:
        return bytes(scalar(conn, "SELECT merchant_id FROM merchants WHERE display_name = 'Corner Store'"))


WINDOW_START = 1792346400  # 2026-10-18 14:00 EDT
WINDOW_END = WINDOW_START + 6 * 3600  # 20:00 EDT


_flags = iter(range(1000))


def make_flag(deps, merchant_id: bytes, notice: str | None, action: str = "hold_pool_payout",
              exposure: int = 14000, params: dict | None = None) -> int:
    day = next(_flags) * 86400  # candidates are unique per (kind, subject, window_start)
    features = {"contacts_per_hour": 0.0, "neighbor_median_contacts_per_hour": 6.8, "pool_funded_cents": 14000,
                "pool_funded_count": 3, "neighbor_contacts": 41, "neighbors": 2}
    with deps.pool.connection() as conn:
        cand = scalar(conn, """INSERT INTO candidates (kind, subject_id, window_start, window_end, features)
                               VALUES ('merchant_silence', %s, %s, %s, %s) RETURNING candidate_id""",
                      (merchant_id.hex(), WINDOW_START + day, WINDOW_END + day, Jsonb(features)))
        return scalar(conn, """INSERT INTO flags (candidate_id, kind, severity, subject_id, evidence_ids, exposure_cents,
                                   summary, proposed_action, citations_valid, agent_transcript, status)
                               VALUES (%s, 'merchant_silence', 'review', %s, '{}', %s, 's', %s, true, %s, 'approved')
                               RETURNING flag_id""",
                      (cand, merchant_id.hex(), exposure, action,
                       Jsonb({"merchant_notice": notice, "action_params": params or {}})))


def signed(body: dict, secret: str = SECRET, ts: int | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    ts = str(int(time.time()) if ts is None else ts)
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + raw, hashlib.sha256).hexdigest()
    return raw, {"content-type": "application/json", "x-spectrum-timestamp": ts, "x-spectrum-signature": sig,
                 "x-spectrum-event": "messages"}


def telegram_text(text: str, sender: str = HANDLE, msg_id: str = "m-1") -> dict:
    space = {"id": sender, "platform": "Telegram"}
    return {"event": "messages", "space": space, "message": {
        "id": msg_id, "platform": "Telegram", "direction": "inbound", "timestamp": "2026-10-18T22:00:00Z",
        "sender": {"id": sender, "platform": "Telegram"}, "space": space, "content": {"type": "text", "text": text}}}


def wait_for(deps, sql: str, params, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with deps.pool.connection() as conn:
            row = one(conn, sql, params)
        if row:
            return row
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for: {sql}")


# Signatures -------------------------------------------------------------------------------


def test_signature_check():
    raw = b'{"event":"messages"}'
    now = 1_800_000_000
    good = "v0=" + hmac.new(b"k", b"v0:%d:" % now + raw, hashlib.sha256).hexdigest()
    assert routes.verify_signature("k", raw, str(now), good, now)
    assert not routes.verify_signature("k", raw + b" ", str(now), good, now)  # body changed
    assert not routes.verify_signature("other", raw, str(now), good, now)
    assert not routes.verify_signature("k", raw, str(now), good, now + 301)  # stale
    assert not routes.verify_signature("", raw, str(now), good, now)


# Hold notice --------------------------------------------------------------------------------


def test_hold_notice_uses_a_grounded_agent_draft(deps, corner, photon, bridge):
    draft = ("Corner Store, your $140 guarantee-pool payout is on hold. Your phone logged no contact with other "
             "phones from 2–8 PM while 2 nearby shops logged 41. Reply to explain.")
    flag_id = make_flag(deps, corner, draft)
    msg = notices.hold_notice(deps, photon, flag_id)
    assert msg["delivered"] is True and msg["body"] == draft and msg["flag_id"] == flag_id
    assert bridge.sent == [{"channel": "telegram", "handle": HANDLE, "text": draft}]


def test_hold_notice_drops_a_draft_with_an_invented_number(deps, corner, photon, bridge):
    flag_id = make_flag(deps, corner, "Corner Store, your $990 payout is on hold. Reply to explain.")
    msg = notices.hold_notice(deps, photon, flag_id)
    assert "990" not in msg["body"]
    assert msg["body"] == notices.template_notice("Corner Store", {"proposed_action": "hold_pool_payout"})


def test_limit_notice_template(deps, corner, photon, bridge):
    flag_id = make_flag(deps, corner, None, action="lower_merchant_limit", params={"limit_cents": 1000})
    assert "$10.00" in notices.hold_notice(deps, photon, flag_id)["body"]


def test_no_notice_for_other_actions(deps, corner, photon, bridge):
    assert notices.hold_notice(deps, photon, make_flag(deps, corner, "x", action="freeze_cert")) is None
    assert bridge.sent == []


def test_failed_send_is_recorded_honestly(deps, corner, bridge):
    bridge.status = 502
    cfg = PhotonSettings(bridge_token="bridge-token", transport=httpx.MockTransport(bridge.handle))
    msg = notices.hold_notice(deps, cfg, make_flag(deps, corner, None))
    assert msg["delivered"] is False and "502" in msg["error"]
    off = PhotonSettings(disabled=True)
    assert notices.hold_notice(deps, off, make_flag(deps, corner, None))["delivered"] is False
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM messages WHERE direction = 'out'") == 2


def test_notify_route_needs_operator(app_client, deps, corner, photon, bridge):
    flag_id = make_flag(deps, corner, None)
    assert app_client.post(f"/v1/photon/notify/{flag_id}").status_code == 401
    r = app_client.post(f"/v1/photon/notify/{flag_id}", headers=OPERATOR)
    assert r.status_code == 200 and len(bridge.sent) == 1


def test_settled_text():
    assert notices.settled_text(1200, 1792354320) == "Paid: $12.00 from StormCash for payment at 4:12 PM."


# Inbound + appeal ----------------------------------------------------------------------------


def test_inbound_reply_gets_an_answer(app_client, deps, corner, photon, bridge):
    flag_id = make_flag(deps, corner, None)
    raw, headers = signed(telegram_text("we were closed, generator died"))
    r = app_client.post("/v1/photon/inbound", content=raw, headers=headers)
    assert r.status_code == 200 and r.json()["flag_id"] == flag_id
    out = wait_for(deps, "SELECT * FROM messages WHERE direction = 'out'", ())
    # The fake runner cites nothing, so the merchant gets the neutral acknowledgement.
    assert out["body"] == FALLBACK_REPLY and out["flag_id"] == flag_id
    with deps.pool.connection() as conn:
        inbound = one(conn, "SELECT * FROM messages WHERE direction = 'in'")
        runs = all_rows(conn, "SELECT job, merchant_id FROM stormdesk_runs")
    assert inbound["body"] == "we were closed, generator died" and inbound["channel"] == "telegram"
    assert runs == [{"job": "respond", "merchant_id": corner}]
    assert bridge.sent[-1]["text"] == FALLBACK_REPLY

    thread = app_client.get("/v1/photon/messages", params={"merchant_id": corner.hex()}).json()["messages"]
    assert [m["direction"] for m in thread] == ["in", "out"]


def test_inbound_rejects_bad_signature_and_ignores_noise(app_client, deps, corner, photon, bridge):
    raw, headers = signed(telegram_text("hi"), secret="wrong")
    assert app_client.post("/v1/photon/inbound", content=raw, headers=headers).status_code == 401
    raw, headers = signed(telegram_text("hi", sender="999"))
    assert app_client.post("/v1/photon/inbound", content=raw, headers=headers).json()["ignored"] == "unknown sender"
    raw, headers = signed({"event": "messages", "message": {"direction": "inbound", "content": {"type": "reaction"}}})
    assert "ignored" in app_client.post("/v1/photon/inbound", content=raw, headers=headers).json()


def test_duplicate_delivery_is_ignored(app_client, deps, corner, photon, bridge):
    raw, headers = signed(telegram_text("hello", msg_id="dup"))
    assert app_client.post("/v1/photon/inbound", content=raw, headers=headers).json()["ok"]
    assert app_client.post("/v1/photon/inbound", content=raw, headers=headers).json()["ignored"] == "duplicate delivery"
    wait_for(deps, "SELECT 1 FROM messages WHERE direction = 'out'", ())
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM messages WHERE direction = 'in'") == 1


def test_pick_reply_requires_citations():
    agent = {"status": "succeeded", "citations_valid": True,
             "output": {"reply": "Your log shows 3 payments.", "evidence_ids": ["ab" * 32]}}
    assert pick_reply(agent) == ("Your log shows 3 payments.", True)
    assert pick_reply({**agent, "output": {**agent["output"], "evidence_ids": []}}) == (FALLBACK_REPLY, False)
    assert pick_reply({**agent, "citations_valid": False}) == (FALLBACK_REPLY, False)
    assert pick_reply({"status": "failed"}) == (FALLBACK_REPLY, False)
