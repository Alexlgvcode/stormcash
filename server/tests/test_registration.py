"""WS2 #13: register, Storm Mode on Nessie, ledger, call log, SSE (spec §11.3, §11.4, §12)."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from stormcash import ledger, registry
from stormcash.auth import sign_request
from stormcash.db import all_rows, one, scalar
from stormcash.nessie import cents_to_dollars
from stormcash.protocol import crypto
from stormcash.protocol.objects import Cert, Mcert, b64u_decode, b64u_encode
from stormcash.sse import Broker

from .conftest import SERVER_KEY

MAYA = crypto.private_key_from_scalar(0x111)
PHARMACY = crypto.private_key_from_scalar(0x222)
SERVER_PUB = crypto.public_key_bytes(SERVER_KEY)


def post(client, path: str, payload: dict, key=MAYA, ts: int | None = None, headers: dict | None = None):
    body = json.dumps(payload).encode()
    hdrs = {"content-type": "application/json"}
    hdrs.update(sign_request(key, path, body, ts) if key is not None else {})
    hdrs.update(headers or {})
    return client.post(path, content=body, headers=hdrs)


def register_maya(client, **extra):
    payload = {"display_name": "Maya", "holder_pub": b64u_encode(crypto.public_key_bytes(MAYA)),
               "region_id": "asheville-downtown", **extra}
    resp = post(client, "/v1/residents/register", payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_cents_to_dollars_refuses_fractions():
    assert cents_to_dollars(1200) == 12
    assert cents_to_dollars(0) == 0
    with pytest.raises(ValueError):
        cents_to_dollars(1234)
    with pytest.raises(TypeError):
        cents_to_dollars(12.0)


def test_register_resident_creates_nessie_accounts_cert_and_locks_escrow(app_client, deps, fake_nessie):
    out = register_maya(app_client)
    cert = Cert.from_json(out["cert"])
    assert cert.verify(SERVER_PUB)
    assert (cert.cert_ver, cert.cap_cents, cert.holder_pub) == (1, 2000, crypto.public_key_bytes(MAYA))
    assert cert.expires_at - cert.issued_at == 72 * 3600
    assert abs(cert.issued_at - time.time()) < 60

    with deps.pool.connection() as conn:
        res = one(conn, "SELECT * FROM residents WHERE resident_id = %s", (out["resident_id"],))
        status = one(conn, "SELECT * FROM cert_status WHERE cert_id = %s", (cert.cert_id,))
        assert ledger.balance(conn, ledger.escrow(cert.cert_id)) == 2000
        assert ledger.balance(conn, ledger.checking(out["resident_id"])) == -2000
        assert ledger.unbalanced_txns(conn) == []
        move = one(conn, "SELECT * FROM nessie_moves")
        calls = all_rows(conn, "SELECT method, path, summary, status FROM nessie_calls ORDER BY call_id")

    assert cert.escrow_ref == res["escrow_account_id"]
    assert (status["status"], status["max_cap_cents"], status["storm_mode"]) == ("active", 2000, False)
    # Checking opened at $500, escrow at $0; $20 moved as withdrawal + deposit.
    assert fake_nessie.accounts[res["checking_account_id"]]["balance"] == 500
    assert fake_nessie.accounts[res["escrow_account_id"]]["balance"] == 0
    assert fake_nessie.balance_dollars(res["checking_account_id"]) == 480
    assert fake_nessie.balance_dollars(res["escrow_account_id"]) == 20
    desc = f"SC {move['txn_id']} "
    assert all(r["description"].startswith(desc) for recs in fake_nessie.records.values() for r in recs)
    assert move["status"] == "executed" and move["withdrawal_id"] and move["deposit_id"]
    assert [c["method"] for c in calls] == ["POST"] * 5
    assert all(c["status"] == 201 and c["summary"] for c in calls)
    assert all("key" not in c["path"] for c in calls)


def test_register_is_idempotent_per_key(app_client, fake_nessie):
    first = register_maya(app_client)
    n_calls = len(fake_nessie.calls)
    again = register_maya(app_client)
    assert again["resident_id"] == first["resident_id"]
    assert again["cert"] == first["cert"]
    assert len(fake_nessie.calls) == n_calls


@pytest.mark.parametrize(
    "case",
    ["unsigned", "other_key", "stale_ts", "tampered_body"],
)
def test_register_requires_holder_signature(app_client, case):
    payload = {"display_name": "Maya", "holder_pub": b64u_encode(crypto.public_key_bytes(MAYA))}
    path = "/v1/residents/register"
    if case == "unsigned":
        resp = post(app_client, path, payload, key=None)
        assert resp.status_code == 401
    elif case == "other_key":
        assert post(app_client, path, payload, key=PHARMACY).status_code == 403
    elif case == "stale_ts":
        assert post(app_client, path, payload, ts=int(time.time()) - 3600).status_code == 401
    else:
        body = json.dumps(payload).encode()
        headers = {"content-type": "application/json", **sign_request(MAYA, path, body)}
        resp = app_client.post(path, content=body.replace(b"Maya", b"Eve!"), headers=headers)
        assert resp.status_code == 401


def test_unknown_region_and_bad_strings_are_rejected(app_client):
    pub = b64u_encode(crypto.public_key_bytes(MAYA))
    assert post(app_client, "/v1/residents/register",
                {"display_name": "Maya", "holder_pub": pub, "region_id": "atlantis"}).status_code == 400
    assert post(app_client, "/v1/residents/register",
                {"display_name": "Ma|ya", "holder_pub": pub}).status_code == 400


def test_storm_mode_tops_escrow_to_50_and_issues_v2(app_client, deps, fake_nessie):
    out = register_maya(app_client)
    cert_id = out["cert"]["ci"]
    resp = post(app_client, "/v1/storm-mode", {"cert_id": cert_id, "cap_cents": 5000})
    assert resp.status_code == 200, resp.text
    v2 = Cert.from_json(resp.json()["cert"])
    assert v2.verify(SERVER_PUB)
    assert (v2.cert_ver, v2.cap_cents) == (2, 5000)

    with deps.pool.connection() as conn:
        res = one(conn, "SELECT * FROM residents")
        status = one(conn, "SELECT * FROM cert_status")
        assert ledger.balance(conn, ledger.escrow(v2.cert_id)) == 5000
        assert ledger.unbalanced_txns(conn) == []
        summaries = [r["summary"] for r in all_rows(conn, "SELECT summary FROM nessie_calls ORDER BY call_id")]
    assert status["storm_mode"] and status["max_cap_cents"] == 5000
    assert fake_nessie.balance_dollars(res["escrow_account_id"]) == 50
    assert fake_nessie.balance_dollars(res["checking_account_id"]) == 450
    assert any("Storm Mode top-up" in s and "$30" in s for s in summaries)

    # The Nessie call log endpoint shows the lock and the top-up.
    log_rows = app_client.get("/v1/nessie/log").json()
    assert [r["summary"].split(",")[0] for r in log_rows[:4]] == [
        "Storm Mode top-up", "Storm Mode top-up", "Lock escrow", "Lock escrow",
    ]

    # Same cap again changes nothing.
    again = post(app_client, "/v1/storm-mode", {"cert_id": cert_id, "cap_cents": 5000}).json()
    assert again["cert"] == resp.json()["cert"]


def test_storm_mode_checks_caller_and_cap(app_client):
    cert_id = register_maya(app_client)["cert"]["ci"]
    assert post(app_client, "/v1/storm-mode", {"cert_id": cert_id, "cap_cents": 5000}, key=PHARMACY).status_code == 403
    assert post(app_client, "/v1/storm-mode", {"cert_id": cert_id, "cap_cents": 9000}).status_code == 400
    assert post(app_client, "/v1/storm-mode", {"cert_id": cert_id, "cap_cents": 4550}).status_code == 400
    unknown = b64u_encode(bytes(16))
    assert post(app_client, "/v1/storm-mode", {"cert_id": unknown, "cap_cents": 5000}).status_code == 404


def test_frozen_cert_cannot_enter_storm_mode(app_client, deps):
    cert_id = register_maya(app_client)["cert"]["ci"]
    with deps.pool.connection() as conn:
        conn.execute("UPDATE cert_status SET status = 'frozen'")
    assert post(app_client, "/v1/storm-mode", {"cert_id": cert_id, "cap_cents": 5000}).status_code == 409


def test_close_then_refund_after_grace(app_client, deps, fake_nessie):
    cert_id = register_maya(app_client)["cert"]["ci"]
    v2 = Cert.from_json(post(app_client, "/v1/storm-mode", {"cert_id": cert_id, "cap_cents": 5000}).json()["cert"])
    resp = post(app_client, "/v1/storm-mode/close", {"cert_id": cert_id})
    v3 = Cert.from_json(resp.json()["cert"])
    assert (v3.cert_ver, v3.cap_cents) == (3, 2000) and v3.verify(SERVER_PUB)

    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM cert_status") == "closing"
        due = registry.escrow_release_at(conn, v3.cert_id)
    assert due == v2.expires_at + 24 * 3600

    assert registry.release_due_escrows(deps, now=due - 1) == []
    assert registry.release_due_escrows(deps, now=due) == [v3.cert_id]
    with deps.pool.connection() as conn:
        res = one(conn, "SELECT * FROM residents")
        assert ledger.balance(conn, ledger.escrow(v3.cert_id)) == 2000
        assert scalar(conn, "SELECT status FROM cert_status") == "active"
        assert ledger.unbalanced_txns(conn) == []
    assert fake_nessie.balance_dollars(res["escrow_account_id"]) == 20
    assert fake_nessie.balance_dollars(res["checking_account_id"]) == 480
    # Nothing left to release.
    assert registry.release_due_escrows(deps, now=due + 10) == []


def test_nessie_down_during_account_creation_is_503(app_client, fake_nessie):
    fake_nessie.down = True
    payload = {"display_name": "Maya", "holder_pub": b64u_encode(crypto.public_key_bytes(MAYA))}
    resp = post(app_client, "/v1/residents/register", payload)
    assert resp.status_code == 503
    assert "NESSIE_DISABLED" in resp.json()["detail"]


def test_failed_half_is_queued_and_replay_creates_only_the_missing_half(app_client, deps, fake_nessie):
    fake_nessie.fail.add("deposits")
    out = register_maya(app_client)  # registration still succeeds: money is queued
    with deps.pool.connection() as conn:
        move = one(conn, "SELECT * FROM nessie_moves")
        res = one(conn, "SELECT * FROM residents")
    assert move["status"] == "queued" and move["withdrawal_id"] and move["deposit_id"] is None
    assert Cert.from_json(out["cert"]).cap_cents == 2000

    fake_nessie.fail.clear()
    assert deps.mover.replay_queued() == 1
    with deps.pool.connection() as conn:
        move = one(conn, "SELECT * FROM nessie_moves")
    assert move["status"] == "executed"
    withdrawals = [r for r in fake_nessie.records[res["checking_account_id"]] if r["type"] == "withdrawals"]
    assert len(withdrawals) == 1  # the withdrawal was not repeated
    assert fake_nessie.balance_dollars(res["escrow_account_id"]) == 20


def test_replay_finds_a_half_that_succeeded_without_a_response(app_client, deps, fake_nessie):
    """A timeout after Nessie stored the withdrawal: replay finds it by txn_id."""
    out = register_maya(app_client)
    with deps.pool.connection() as conn:
        res = one(conn, "SELECT * FROM residents")
        conn.execute("UPDATE nessie_moves SET status = 'queued', withdrawal_id = NULL, deposit_id = NULL, attempts = 1")
    assert deps.mover.replay_queued() == 1
    assert len(fake_nessie.records[res["checking_account_id"]]) == 1
    assert len(fake_nessie.records[res["escrow_account_id"]]) == 1
    assert out["resident_id"]


def test_register_merchant_with_contact(app_client, deps, fake_nessie):
    payload = {
        "display_name": "Pharmacy", "merchant_pub": b64u_encode(crypto.public_key_bytes(PHARMACY)),
        "region_id": "asheville-downtown", "x": 12, "y": 5, "contact": {"channel": "telegram", "handle": "@pharm"},
    }
    resp = post(app_client, "/v1/merchants/register", payload, key=PHARMACY)
    assert resp.status_code == 200, resp.text
    mcert = Mcert.from_json(resp.json()["mcert"])
    assert mcert.verify(SERVER_PUB)
    assert b64u_decode(resp.json()["merchant_id"]) == mcert.merchant_id
    assert (mcert.display_name, mcert.region_id, mcert.merchant_ver) == ("Pharmacy", "asheville-downtown", 1)
    assert mcert.expires_at - time.time() > 29 * 86400
    with deps.pool.connection() as conn:
        m = one(conn, "SELECT * FROM merchants")
        contact = one(conn, "SELECT * FROM merchant_contacts")
    assert fake_nessie.accounts[m["nessie_account_id"]]["balance"] == 0
    assert (m["x"], m["y"], m["simulated"]) == (12, 5, False)
    assert bytes(contact["merchant_id"]) == mcert.merchant_id and contact["handle"] == "@pharm"

    again = post(app_client, "/v1/merchants/register", payload, key=PHARMACY).json()
    assert again["merchant_id"] == resp.json()["merchant_id"]


def test_simulated_entities_never_touch_nessie(app_client, deps, fake_nessie):
    rid, cert, created = registry.register_resident(
        deps, "Sim resident", crypto.public_key_bytes(MAYA), "swannanoa", simulated=True
    )
    mid, mcert, _ = registry.register_merchant(
        deps, "Corner Store", crypto.public_key_bytes(PHARMACY), "asheville-downtown", simulated=True
    )
    registry.raise_storm_mode(deps, cert.cert_id, 5000)
    assert fake_nessie.calls == []
    assert created and cert.escrow_ref == f"sim-{rid}"
    with deps.pool.connection() as conn:
        assert ledger.balance(conn, ledger.escrow(cert.cert_id)) == 5000
        assert scalar(conn, "SELECT count(*) FROM nessie_moves") == 0


def test_ledger_only_when_nessie_disabled(clean_db):
    from fastapi.testclient import TestClient

    from stormcash.app import create_app

    from .conftest import make_settings

    app = create_app(make_settings(clean_db, nessie_enabled=False))
    with TestClient(app) as client:
        out = register_maya(client)
        assert Cert.from_json(out["cert"]).escrow_ref == "ledger-only"
        deps = client.app.state.deps
        with deps.pool.connection() as conn:
            assert scalar(conn, "SELECT count(*) FROM nessie_calls") == 0
            assert ledger.balance(conn, ledger.escrow(Cert.from_json(out["cert"]).cert_id)) == 2000


def test_unsigned_writes_allowed_when_switched_off(clean_db, fake_nessie):
    from fastapi.testclient import TestClient

    from stormcash.app import create_app

    from .conftest import make_settings

    app = create_app(make_settings(clean_db, api_sig_required=False), nessie_transport=fake_nessie.transport())
    with TestClient(app) as client:
        payload = {"display_name": "Maya", "holder_pub": b64u_encode(crypto.public_key_bytes(MAYA))}
        assert post(client, "/v1/residents/register", payload, key=None).status_code == 200


def test_broker_delivers_events_to_subscribers():
    async def scenario():
        broker = Broker()
        stream = broker.subscribe()
        first = asyncio.ensure_future(stream.__anext__())
        await asyncio.sleep(0)
        broker.publish("nessie_call", {"call_id": 1, "raw": b"\x01\x02"})
        message = await asyncio.wait_for(first, 1)
        await stream.aclose()
        return message

    message = asyncio.run(scenario())
    assert message["event"] == "nessie_call"
    assert json.loads(message["data"]) == {"call_id": 1, "raw": "AQI"}


def test_nessie_writes_are_published_as_sse(app_client, deps, monkeypatch):
    seen = []
    monkeypatch.setattr(deps.events, "publish", lambda event, data: seen.append((event, data["summary"])))
    register_maya(app_client)
    assert [e for e, _ in seen] == ["nessie_call"] * 5
