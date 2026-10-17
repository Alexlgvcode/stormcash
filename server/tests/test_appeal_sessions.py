"""WS7/WS5: a shop's appeal is one conversation, one Droid session resumed for every text (spec §17.2).

Droid itself is replaced by FakeDroid, which keeps sessions after they close (like ~/.factory/sessions),
reopens them with Session.resume, and answers each turn with the next scripted AppealReply.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from stormcash.app import create_app
from stormcash.db import all_rows, scalar
from stormcash.photon import notices
from stormcash.photon.appeal import FALLBACK_REPLY
from stormcash.photon.config import PhotonSettings
from stormcash.protocol.objects import b64u_encode
from stormcash.stormdesk import runner

from .conftest import make_settings
from .test_photon import SECRET, Bridge, make_flag, signed, telegram_text, wait_for
from .test_photon_freeze import MAYA_HANDLE, world  # noqa: F401 (Maya, registered with her Telegram handle)
from .world import CORNER, pub, signed_post

HANDLE = MAYA_HANDLE  # one Telegram account at the table is both Maya and the Corner Store


class FakeDroid:
    """Stands in for droid_sdk.Session."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)  # AppealReply dicts, or RunFailure results
        self.prompts: dict[str, list[str]] = {}  # session id -> the prompts it was sent, in order
        self.log: list[tuple[str, str]] = []  # ("start" | "resume" | "resume_failed", session id)
        self.lost: set[str] = set()  # saved sessions that are gone (expired, another machine)
        self.resumed_with: list[dict] = []

    def install(self, monkeypatch) -> None:
        import droid_sdk
        from droid_sdk import RunSuccess, SessionNotFoundError, ToolCall, ToolResult, Usage

        fake = self

        class Stream:
            def __init__(self, result, events) -> None:
                self.result, self.events = result, events

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.events:
                    raise StopAsyncIteration
                return self.events.pop(0)

        class Session:
            def __init__(self, *, model=None, config=None, interactions=None, api_key=None, **kw) -> None:
                self.config, self.interactions, self.resume_id, self.sid = config, interactions, None, None

            @classmethod
            def resume(cls, session_id, *, interactions=None, mcp_servers=(), api_key=None, disabled_tools=None,
                       disable_builtin_skills=None, **kw):
                s = cls(interactions=interactions)
                s.resume_id = session_id
                fake.resumed_with.append({"mcp_servers": list(mcp_servers), "disabled_tools": disabled_tools,
                                          "disable_builtin_skills": disable_builtin_skills,
                                          "interactions": interactions})
                return s

            async def open(self) -> None:
                if self.sid:
                    return
                if self.resume_id:
                    if self.resume_id not in fake.prompts or self.resume_id in fake.lost:
                        fake.log.append(("resume_failed", self.resume_id))
                        raise SessionNotFoundError(self.resume_id)
                    self.sid = self.resume_id
                    fake.log.append(("resume", self.sid))
                else:
                    self.sid = f"droid-s{len(fake.prompts) + 1}"
                    fake.prompts[self.sid] = []
                    fake.log.append(("start", self.sid))

            async def close(self) -> None:
                pass

            async def __aenter__(self):
                await self.open()
                return self

            async def __aexit__(self, *exc):
                return False

            @property
            def id(self) -> str:
                return self.sid

            @property
            def settings(self):
                return SimpleNamespace(model="claude-sonnet-5-5")

            def stream(self, prompt, output, timeout):
                fake.prompts[self.sid].append(prompt)
                result = fake.replies.pop(0)
                if isinstance(result, dict):
                    result = RunSuccess(text="", messages=(), duration=timedelta(seconds=4), turn_count=2,
                                        session_id=self.sid, structured_output=result,
                                        usage=Usage(input_tokens=900, output_tokens=120, cache_creation_tokens=0,
                                                    cache_read_tokens=0, thinking_tokens=0, factory_credits=5000.0))
                events = [ToolCall(name="mcp__stormdesk__get_device_log", tool_use_id="t1", input={"device_id": "x"}),
                          ToolResult(tool_use_id="t1", tool_name="mcp__stormdesk__get_device_log", content="{}",
                                     is_error=False)]
                return Stream(result, events)

        monkeypatch.setattr(droid_sdk, "Session", Session)


@pytest.fixture
def appeal_sessions() -> bool:
    return True


@pytest.fixture
def app_client(clean_db, fake_nessie, appeal_sessions):
    """The server with StormDesk on Droid (FakeDroid in the tests) and appeal sessions on unless a test says off."""
    settings = make_settings(clean_db, nessie_pool_account_id=fake_nessie.pool_id, stormdesk_runner="droid",
                             stormdesk_model="claude-sonnet-5-5", stormdesk_appeal_sessions=appeal_sessions)
    app = create_app(settings, nessie_transport=fake_nessie.transport(), photon=PhotonSettings(disabled=True))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def bridge() -> Bridge:
    return Bridge()


@pytest.fixture
def photon(app_client, bridge) -> PhotonSettings:
    cfg = PhotonSettings(bridge_token="bridge-token", webhook_secret=SECRET, transport=httpx.MockTransport(bridge.handle))
    app_client.app.state.photon = cfg
    return cfg


@pytest.fixture
def corner(app_client, photon) -> bytes:
    """Corner Store, on the same Telegram handle as Maya."""
    r = signed_post(app_client, "/v1/merchants/register",
                    {"display_name": "Corner Store", "merchant_pub": b64u_encode(pub(CORNER)),
                     "region_id": "asheville-downtown", "contact": {"channel": "telegram", "handle": HANDLE}}, CORNER)
    assert r.status_code == 200, r.text
    with app_client.app.state.deps.pool.connection() as conn:
        return bytes(scalar(conn, "SELECT merchant_id FROM merchants WHERE display_name = 'Corner Store'"))


@pytest.fixture
def notice(deps, corner, photon) -> int:
    """An approved hold on the Corner Store, and the hold notice that starts its thread."""
    flag_id = make_flag(deps, corner, None)
    notices.hold_notice(deps, photon, flag_id)
    return flag_id


def reply(text: str, cites: list[str], consistent: bool = False, escalate: bool = True) -> dict:
    return {"reply": text, "claim_consistent_with_logs": consistent, "evidence_ids": cites, "escalate": escalate}


def text(app_client, deps, body: str, n: int) -> None:
    """The shop texts `body` (its n-th text); returns once StormDesk's answer to it went out."""
    raw, headers = signed(telegram_text(body, sender=HANDLE, msg_id=f"shop-{n}"))
    r = app_client.post("/v1/photon/inbound", content=raw, headers=headers)
    assert r.status_code == 200 and "merchant_id" in r.json(), r.text
    wait_for(deps, """SELECT count(*) FROM stormdesk_runs WHERE job = 'respond'
                      AND transcript->'appeal' ? 'out_message_id' HAVING count(*) >= %s""", (n,))


def turns(deps) -> list[dict]:
    with deps.pool.connection() as conn:
        return all_rows(conn, """SELECT run_id, runner, status, session_id, transcript FROM stormdesk_runs
                                 WHERE job = 'respond' ORDER BY run_id""")


def test_an_appeal_is_one_droid_session_resumed_for_every_text(app_client, deps, corner, notice, bridge,
                                                               monkeypatch):
    shop = corner.hex()
    answers = ["Your log shows 3 payments accepted at 4:12, 4:30 and 5:05 PM.",
               "You said you were closed, but those payments were accepted while you say the generator was down.",
               "Thanks. A person will compare the receipts with your log."]
    droid = FakeDroid([reply(a, [shop]) for a in answers])
    droid.install(monkeypatch)
    text(app_client, deps, "we were closed, generator died", 1)
    text(app_client, deps, "we only took cash after 4", 2)
    text(app_client, deps, "ok I have receipts", 3)

    # One Droid session for the whole thread: started once, then resumed for each new text.
    assert droid.log == [("start", "droid-s1"), ("resume", "droid-s1"), ("resume", "droid-s1")]
    first, second, third = droid.prompts["droid-s1"]
    hold = bridge.sent[0]["text"]
    assert hold in first and "The shop's new message: 'we were closed, generator died'" in first
    assert "merchant_silence, proposed action hold_pool_payout" in first and f"#{notice}" not in first
    # Later turns bring only the new text: the session already has the notice and its earlier replies.
    assert second.startswith("The shop wrote again: 'we only took cash after 4'") and hold not in second
    assert third.startswith("The shop wrote again: 'ok I have receipts'") and "not sent" not in third

    runs = turns(deps)
    assert [r["session_id"] for r in runs] == ["droid-s1"] * 3
    assert [(r["transcript"]["appeal"]["session"], r["transcript"]["appeal"]["turn"]) for r in runs] == [
        ("started", 1), ("resumed", 2), ("resumed", 3)]
    for r in runs:  # recorded like every other run
        t = r["transcript"]
        assert (r["runner"], r["status"]) == ("droid", "succeeded")
        assert t["model"] == "claude-sonnet-5-5" and t["usage"]["factory_credits"] == 5000.0
        assert t["attempts"] == [{"attempt": 1, "ok": True, "error": None}] and t["permission_denials"] == []
        assert t["duration_s"] is not None and t["steps"][0]["tool"] == "get_device_log"
        assert t["appeal"]["mode"] == "session" and t["appeal"]["flag_id"] == notice
        assert t["appeal"]["reply_sent"] is True
    # Each reply went to the shop, in order.
    assert [m["text"] for m in bridge.sent[1:]] == answers

    # Every turn resumed with the same read-only tools, built-ins off and the permission handler.
    for kw in droid.resumed_with:
        assert len(kw["mcp_servers"]) == 1 and kw["disabled_tools"] == runner.BUILTIN_TOOLS
        assert kw["disable_builtin_skills"] is True and kw["interactions"].on_permission is not None

    # The dashboard thread: messages and the turns that answered them, one Droid session.
    thread = app_client.get("/v1/photon/messages", params={"merchant_id": shop}).json()
    outs = [m["message_id"] for m in thread["messages"] if m["direction"] == "out"]
    assert [t["out_message_id"] for t in thread["turns"]] == outs[1:]  # the first is the hold notice
    assert {t["session_id"] for t in thread["turns"]} == {"droid-s1"}
    assert [t["turn"] for t in thread["turns"]] == [1, 2, 3]

    # The Droid tab counts them as one conversation.
    console = app_client.get("/v1/droid/console").json()
    assert console["appeal_sessions"] == {"sessions": 1, "turns": 3, "resumed": 2, "restarted": 0, "longest": 3}
    assert [r["subject"] for r in console["runs"]] == [f"Corner Store · appeal turn {n}" for n in (3, 2, 1)]
    assert console["runs"][0]["appeal"] == {"session": "resumed", "turn": 3, "session_id": "droid-s1",
                                            "resume_error": None}


def test_a_session_that_cant_be_resumed_starts_over_from_the_stored_thread(app_client, deps, corner, notice,
                                                                         bridge, monkeypatch):
    shop = corner.hex()
    droid = FakeDroid([reply("Your log shows 3 payments during that window.", [shop]),
                       reply("Earlier you said the generator died; your log has payments then.", [shop]),
                       reply("Noted.", [shop])])
    droid.install(monkeypatch)
    text(app_client, deps, "we were closed, generator died", 1)
    droid.lost.add("droid-s1")  # e.g. the server moved to another machine
    text(app_client, deps, "we only took cash", 2)
    text(app_client, deps, "ok", 3)

    assert droid.log == [("start", "droid-s1"), ("resume_failed", "droid-s1"), ("start", "droid-s2"),
                         ("resume", "droid-s2")]
    seeded = droid.prompts["droid-s2"][0]
    assert "couldn't be reopened" in seeded
    for earlier in (bridge.sent[0]["text"], "we were closed, generator died", "Your log shows 3 payments during"):
        assert earlier in seeded  # the whole thread from `messages`
    assert "The shop's new message: 'we only took cash'" in seeded

    second = turns(deps)[1]["transcript"]["appeal"]
    assert second["session"] == "restarted" and second["turn"] == 1 and second["resumed_from"] == "droid-s1"
    assert second["resume_error"] == "SessionNotFoundError: Session not found: droid-s1"
    assert second["seeded_messages"] == 3  # the notice, the first text and its reply
    assert [r["session_id"] for r in turns(deps)] == ["droid-s1", "droid-s2", "droid-s2"]
    assert turns(deps)[2]["transcript"]["appeal"]["turn"] == 2
    assert app_client.get("/v1/droid/console").json()["appeal_sessions"] == {
        "sessions": 2, "turns": 3, "resumed": 1, "restarted": 1, "longest": 2}


def test_a_reply_citing_a_missing_record_is_held_back_mid_conversation(app_client, deps, corner, notice, bridge,
                                                                       monkeypatch):
    shop = corner.hex()
    invented = "cd" * 32
    droid = FakeDroid([reply("Your log shows payments at 4:12 PM.", [shop]),
                       reply("Contact record shows you were open.", [invented]),
                       reply("Your log shows the 4:12 PM payment, so you were open then.", [shop])])
    droid.install(monkeypatch)
    text(app_client, deps, "we were closed", 1)
    text(app_client, deps, "no we were closed all day", 2)
    text(app_client, deps, "why?", 3)

    runs = turns(deps)
    assert [r["status"] for r in runs] == ["succeeded", "invalid", "succeeded"]
    assert runs[1]["transcript"]["missing_citations"] == [invented]
    assert [r["transcript"]["appeal"]["reply_sent"] for r in runs] == [True, False, True]
    # The invented citation never reached the shop: it got the neutral acknowledgement instead.
    assert [m["text"] for m in bridge.sent[1:]] == [
        "Your log shows payments at 4:12 PM.", FALLBACK_REPLY,
        "Your log shows the 4:12 PM payment, so you were open then."]
    # Same session next turn, and it is told what the shop actually received.
    assert droid.log == [("start", "droid-s1"), ("resume", "droid-s1"), ("resume", "droid-s1")]
    third = droid.prompts["droid-s1"][2]
    assert f"Your previous reply was not sent: it cited records that aren't in the database ({invented})." in third
    assert f"- StormCash: {FALLBACK_REPLY!r}" in third


def test_a_failed_structured_output_is_asked_again_in_the_same_session(app_client, deps, corner, notice,
                                                                        monkeypatch):
    from droid_sdk import RunFailure

    shop = corner.hex()
    bad = RunFailure(subtype="error_structured_output", text="", messages=(), usage=None, duration=timedelta(0),
                     turn_count=1, session_id="droid-s1")
    droid = FakeDroid([bad, reply("Your log shows 3 payments.", [shop])])
    droid.install(monkeypatch)
    text(app_client, deps, "we were closed", 1)
    assert droid.log == [("start", "droid-s1")]
    assert len(droid.prompts["droid-s1"]) == 2 and "wasn't a valid AppealReply" in droid.prompts["droid-s1"][1]
    run = turns(deps)[0]
    assert run["status"] == "succeeded" and [a["ok"] for a in run["transcript"]["attempts"]] == [False, True]


@pytest.mark.parametrize("appeal_sessions", [False])
def test_switch_off_is_one_fresh_run_per_message(app_client, deps, corner, notice, bridge, monkeypatch):
    shop = corner.hex()
    droid = FakeDroid([reply("Your log shows 3 payments.", [shop]), reply("Noted.", [shop])])
    droid.install(monkeypatch)
    text(app_client, deps, "we were closed", 1)
    text(app_client, deps, "really", 2)
    assert droid.log == [("start", "droid-s1"), ("start", "droid-s2")]  # never resumed
    assert all(p[0].startswith(f"Merchant {shop} replied to a hold notice") for p in droid.prompts.values())
    runs = turns(deps)
    assert [r["transcript"]["appeal"]["mode"] for r in runs] == ["per_message"] * 2
    assert all("session" not in r["transcript"]["appeal"] for r in runs)
    assert [m["text"] for m in bridge.sent[1:]] == ["Your log shows 3 payments.", "Noted."]
    assert app_client.get("/v1/droid/console").json()["appeal_sessions"]["turns"] == 0


def test_the_fake_runner_keeps_its_labelled_reply(app_client, deps, corner, notice, bridge, monkeypatch):
    from stormcash.stormdesk import service

    monkeypatch.setattr(service, "make_runner", lambda deps: runner.FakeRunner(deps))
    text(app_client, deps, "we were closed", 1)
    run = turns(deps)[0]
    assert run["runner"] == "fake" and run["session_id"].startswith("fake-")
    assert run["transcript"]["appeal"]["session"] is None  # no Droid session
    assert bridge.sent[-1]["text"] == FALLBACK_REPLY  # it cites nothing, so the neutral acknowledgement goes out


def test_freeze_is_untouched_by_appeal_sessions(app_client, deps, world, corner, notice, bridge,  # noqa: F811
                                                monkeypatch):
    droid = FakeDroid([reply("Your log shows 3 payments.", [corner.hex()])])
    droid.install(monkeypatch)
    raw, headers = signed(telegram_text("FREEZE", sender=HANDLE, msg_id="freeze-1"))
    out = app_client.post("/v1/photon/inbound", content=raw, headers=headers).json()
    assert out["freeze"] == "frozen" and droid.log == []  # deterministic: no agent, no session
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM cert_status WHERE cert_id = %s", (world.cert.cert_id,)) == "frozen"
        assert scalar(conn, "SELECT count(*) FROM stormdesk_runs") == 0
    text(app_client, deps, "we were closed", 1)  # the same handle's other texts are still the shop's appeal
    assert droid.log == [("start", "droid-s1")]
