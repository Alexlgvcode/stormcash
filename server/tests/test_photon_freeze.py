"""WS7: a resident texts FREEZE through Photon (spec §17.2). Deterministic, no agent."""

from __future__ import annotations

import httpx
import pytest

from stormcash.db import all_rows, one, scalar
from stormcash.demo import reset_demo
from stormcash.photon import freeze
from stormcash.photon.config import PhotonSettings
from stormcash.protocol.objects import Policy, b64u_encode

from .test_photon import OPERATOR, SECRET, Bridge, signed, telegram_text
from .world import CORNER, MAYA, World, pub, signed_post

MAYA_HANDLE = "555000222"


@pytest.fixture
def bridge() -> Bridge:
    return Bridge()


@pytest.fixture
def photon(app_client, bridge) -> PhotonSettings:
    cfg = PhotonSettings(bridge_token="bridge-token", webhook_secret=SECRET, transport=httpx.MockTransport(bridge.handle))
    app_client.app.state.photon = cfg
    return cfg


@pytest.fixture
def world(app_client, photon) -> World:
    """Maya, registered again from her phone with her Telegram handle (an existing resident keeps her cert)."""
    w = World(app_client)
    out = signed_post(app_client, "/v1/residents/register",
                      {"display_name": "Maya", "holder_pub": b64u_encode(pub(MAYA)), "region_id": "asheville-downtown",
                       "contact": {"channel": "telegram", "handle": MAYA_HANDLE}}, MAYA)
    assert out.status_code == 200, out.text
    assert out.json()["resident_id"] == w.resident_id
    return w


@pytest.fixture
def events(deps, monkeypatch) -> list[tuple[str, dict]]:
    published: list[tuple[str, dict]] = []
    real = deps.events.publish
    monkeypatch.setattr(deps.events, "publish", lambda e, d: (published.append((e, d)), real(e, d)))
    return published


def text_in(app_client, text: str, sender: str = MAYA_HANDLE, msg_id: str = "m-1") -> dict:
    raw, headers = signed(telegram_text(text, sender=sender, msg_id=msg_id))
    r = app_client.post("/v1/photon/inbound", content=raw, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def cert_status(deps, cert_id: bytes) -> dict:
    with deps.pool.connection() as conn:
        return one(conn, "SELECT * FROM cert_status WHERE cert_id = %s", (cert_id,))


def policy_ver(deps) -> int:
    with deps.pool.connection() as conn:
        return scalar(conn, "SELECT COALESCE(max(policy_ver), 0) FROM policy_versions")


def test_freeze_by_text_freezes_the_cert_publishes_policy_and_confirms(app_client, deps, world, bridge, events):
    cert_id = world.cert.cert_id
    before = policy_ver(deps)
    out = text_in(app_client, "FREEZE")
    assert out["freeze"] == "frozen" and out["newly_frozen"] is True
    assert out["cert_ids"] == [cert_id.hex()] and out["policy_ver"] == before + 1

    status = cert_status(deps, cert_id)
    assert status["status"] == "frozen" and status["frozen_at"] is not None
    assert status["owner_freeze_at"] == out["owner_freeze_at"]
    # The new signed POLICY lists the cert, and phones get it from GET /v1/policy.
    policy = Policy.from_json(app_client.get("/v1/policy").json()["policy"])
    assert policy.policy_ver == before + 1 and cert_id in policy.frozen_certs
    assert policy.verify(deps.settings.server_pub)

    assert bridge.sent == [{"channel": "telegram", "handle": MAYA_HANDLE, "text": freeze.CONFIRM}]
    thread = app_client.get("/v1/photon/messages", params={"resident_id": world.resident_id}).json()["messages"]
    assert [(m["direction"], m["body"]) for m in thread] == [("in", "FREEZE"), ("out", freeze.CONFIRM)]
    assert all(m["merchant_id"] is None for m in thread)

    names = [e for e, _ in events]
    assert names == ["message", "policy", "owner_freeze", "message"]
    assert dict(events)["owner_freeze"]["cert_ids"] == [cert_id.hex()]

    [row] = app_client.get("/v1/photon/freezes").json()
    assert (row["cert_id"], row["display_name"], row["status"], row["policy_ver"]) == \
        (cert_id.hex(), "Maya", "frozen", before + 1)
    with deps.pool.connection() as conn:  # never through the agent
        assert scalar(conn, "SELECT count(*) FROM stormdesk_runs") == 0


def test_second_freeze_changes_nothing(app_client, deps, world, bridge):
    first = text_in(app_client, "FREEZE", msg_id="a")
    ver = policy_ver(deps)
    second = text_in(app_client, "freeze", msg_id="b")
    assert second["freeze"] == "frozen" and second["newly_frozen"] is False
    assert policy_ver(deps) == ver and second["policy_ver"] == ver
    assert second["owner_freeze_at"] == first["owner_freeze_at"]
    assert cert_status(deps, world.cert.cert_id)["owner_freeze_at"] == first["owner_freeze_at"]
    assert [s["text"] for s in bridge.sent] == [freeze.CONFIRM, freeze.CONFIRM]
    # The same delivery twice (at-least-once webhooks) is dropped before anything runs.
    assert text_in(app_client, "FREEZE", msg_id="b")["ignored"] == "duplicate delivery"
    assert len(bridge.sent) == 2


@pytest.mark.parametrize("text", ["freeze", "Freeze", "  FREEZE\n", "fReEzE"])
def test_freeze_is_case_insensitive_and_trimmed(app_client, deps, world, text):
    assert text_in(app_client, text)["freeze"] == "frozen"
    assert cert_status(deps, world.cert.cert_id)["status"] == "frozen"


def test_other_texts_never_freeze_or_unfreeze(app_client, deps, world, bridge):
    ver = policy_ver(deps)
    for i, text in enumerate(["FREEZE!", "please freeze", "UNFREEZE", "hello"]):
        out = text_in(app_client, text, msg_id=f"x{i}")
        assert "freeze" not in out and out["reply"]["body"] == freeze.HELP
    assert cert_status(deps, world.cert.cert_id)["status"] == "active" and policy_ver(deps) == ver

    text_in(app_client, "FREEZE", msg_id="f")
    out = text_in(app_client, "UNFREEZE", msg_id="u")
    assert out["reply"]["body"] == freeze.HELP
    assert cert_status(deps, world.cert.cert_id)["status"] == "frozen"


def test_unknown_handle_gets_a_neutral_reply_and_changes_nothing(app_client, deps, world, bridge, events):
    ver = policy_ver(deps)
    out = text_in(app_client, "FREEZE", sender="999")
    assert out["freeze"] == "unknown sender" and out["reply"]["body"] == freeze.UNKNOWN
    assert bridge.sent == [{"channel": "telegram", "handle": "999", "text": freeze.UNKNOWN}]
    assert cert_status(deps, world.cert.cert_id)["status"] == "active"
    assert cert_status(deps, world.cert.cert_id)["owner_freeze_at"] is None
    assert policy_ver(deps) == ver and events == []
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM messages") == 0
    # Anything else from an unknown handle is ignored, as before.
    assert text_in(app_client, "hi", sender="999", msg_id="m-2")["ignored"] == "unknown sender"


def test_photon_disabled_still_freezes_and_records_the_reply(app_client, deps, world, bridge, events):
    app_client.app.state.photon = PhotonSettings(disabled=True, bridge_token="bridge-token", webhook_secret=SECRET,
                                                 transport=httpx.MockTransport(bridge.handle))
    out = text_in(app_client, "FREEZE")
    assert out["freeze"] == "frozen" and cert_status(deps, world.cert.cert_id)["status"] == "frozen"
    assert bridge.sent == []
    assert out["reply"]["delivered"] is False and "switched off" in out["reply"]["error"]
    with deps.pool.connection() as conn:
        replies = all_rows(conn, "SELECT body, resident_id FROM messages WHERE direction = 'out'")
    assert [r["body"] for r in replies] == [freeze.CONFIRM] and str(replies[0]["resident_id"]) == world.resident_id
    assert [d["delivered"] for e, d in events if e == "message" and d["direction"] == "out"] == [False]


def test_same_handle_for_a_shop_and_a_resident(app_client, deps, world, bridge):
    """At the table one Telegram account can be both Maya and the Corner Store: FREEZE is Maya's,
    anything else is the shop's appeal."""
    signed_post(app_client, "/v1/merchants/register",
                {"display_name": "Corner Store", "merchant_pub": b64u_encode(pub(CORNER)),
                 "region_id": "asheville-downtown", "contact": {"channel": "telegram", "handle": MAYA_HANDLE}}, CORNER)
    assert text_in(app_client, "FREEZE", msg_id="a")["freeze"] == "frozen"
    out = text_in(app_client, "we were closed, generator died", msg_id="b")
    assert "merchant_id" in out and "freeze" not in out


def test_resident_with_nothing_to_freeze(app_client, deps, world, bridge):
    with deps.pool.connection() as conn:
        conn.execute("UPDATE cert_status SET status = 'closed' WHERE cert_id = %s", (world.cert.cert_id,))
    out = text_in(app_client, "FREEZE")
    assert out["freeze"] == "no wallet" and out["cert_ids"] == [] and out["reply"]["body"] == freeze.NO_WALLET


def test_register_contact_validation(app_client, photon):
    bad = signed_post(app_client, "/v1/residents/register",
                      {"display_name": "Maya", "holder_pub": b64u_encode(pub(MAYA)),
                       "contact": {"channel": "carrier-pigeon", "handle": "1"}}, MAYA)
    assert bad.status_code == 400 and "contact.channel" in bad.text


def test_operator_attaches_a_handle_to_maya(app_client, deps, photon, bridge):
    w = World(app_client)  # Maya registered from her phone without a handle
    body = {"display_name": "Maya", "channel": "telegram", "handle": " 42 "}
    assert app_client.post("/v1/photon/resident-contact", json=body).status_code == 401
    r = app_client.post("/v1/photon/resident-contact", json=body, headers=OPERATOR)
    assert r.status_code == 200 and r.json() == {"resident_id": w.resident_id, "display_name": "Maya",
                                                 "channel": "telegram", "handle": "42"}
    missing = app_client.post("/v1/photon/resident-contact", json={**body, "display_name": "Nobody"}, headers=OPERATOR)
    assert missing.status_code == 404
    assert text_in(app_client, "FREEZE", sender="42")["freeze"] == "frozen"


def test_demo_reset_keeps_the_handle_and_issues_an_unfrozen_cert(app_client, deps, world, bridge):
    text_in(app_client, "FREEZE", msg_id="a")
    reset_demo(deps)
    assert app_client.get("/v1/photon/freezes").json() == []  # the old cert is gone with its request
    out = text_in(app_client, "FREEZE", msg_id="b")  # the handle still points at Maya
    assert out["freeze"] == "frozen" and out["cert_ids"] != [world.cert.cert_id.hex()]
