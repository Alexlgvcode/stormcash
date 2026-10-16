"""POST /v1/demo/reset (spec §12.1, §21.1)."""

from __future__ import annotations

import time

import pytest

from stormcash import ledger, registry
from stormcash.db import all_rows, one, scalar
from stormcash.protocol import crypto
from stormcash.protocol.objects import Cert, Policy, b64u_encode

from .conftest import SERVER_KEY
from .world import CORNER, GAS, MAYA, PHARMACY, World, pub

OPERATOR = {"X-SC-Operator": "test"}


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


def test_reset_clears_the_table_and_keeps_the_town(world, app_client, deps, fake_nessie):
    # The simulated town: one simulated shop with a payment from a simulated resident.
    sim_key = crypto.private_key_from_scalar(0x999)
    _, sim_cert, _ = registry.register_resident(deps, "Sim", pub(sim_key), "swannanoa", simulated=True)
    _, sim_mcert, _ = registry.register_merchant(deps, "Corner Store", pub(CORNER), "asheville-downtown", 5, 5,
                                                 simulated=True)
    from stormcash.protocol.objects import Det, Item, Pay, Tag, genesis
    from stormcash.settlement import ingest_items

    det = Det(sim_mcert.merchant_pub, b"\x05" * 16, 1)
    sim_tag = Tag(sim_cert.cert_id, 1, genesis(sim_cert.cert_id), 500, 500, det.digest()).signed(sim_key)
    ingest_items(deps, pub(CORNER), [Item("PAY", Pay(sim_cert, sim_tag, det))], simulated=True)

    # The real phones: Storm Mode, a payment and a double spend (a case, a freeze).
    world.storm(5000)
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 1200)
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [cheat])
    old_cert = world.cert
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM cases") == 1

    out = app_client.post("/v1/demo/reset", headers=OPERATOR).json()
    assert out["ok"] and out["nessie_accounts_opened"] == 4  # Maya checking + escrow, 2 shops

    new_cert = Cert.from_json(out["residents"][0]["cert"])
    assert new_cert.verify(crypto.public_key_bytes(SERVER_KEY))
    assert new_cert.cert_id != old_cert.cert_id
    assert (new_cert.cert_ver, new_cert.cap_cents, new_cert.holder_pub) == (1, 2000, old_cert.holder_pub)
    with deps.pool.connection() as conn:
        # Real-device data gone; the simulated payment, resident and shop stay.
        assert [bytes(r["tag_hash"]) for r in all_rows(conn, "SELECT tag_hash FROM payments")] == [sim_tag.tag_hash]
        assert scalar(conn, "SELECT count(*) FROM cases") == 0
        assert scalar(conn, "SELECT count(*) FROM device_log") == 0
        assert scalar(conn, "SELECT count(*) FROM certificates WHERE cert_id = %s", (old_cert.cert_id,)) == 0
        assert scalar(conn, "SELECT count(*) FROM residents") == 2 and scalar(conn, "SELECT count(*) FROM merchants") == 3
        assert ledger.unbalanced_txns(conn) == []
        assert ledger.balance(conn, ledger.escrow(new_cert.cert_id)) == 2000
        assert ledger.balance(conn, ledger.merchant(sim_mcert.merchant_id)) == 500
        res = one(conn, "SELECT * FROM residents WHERE NOT simulated")
        shops = all_rows(conn, "SELECT * FROM merchants WHERE NOT simulated")
        policy = one(conn, "SELECT * FROM policy_versions ORDER BY policy_ver DESC LIMIT 1")
    # Fresh Nessie accounts: checking $480 after the $20 lock, escrow $20, shops $0.
    assert fake_nessie.balance_dollars(res["checking_account_id"]) == 480
    assert fake_nessie.balance_dollars(res["escrow_account_id"]) == 20
    assert all(fake_nessie.balance_dollars(s["nessie_account_id"]) == 0 and s["pool_eligible"] for s in shops)
    assert [bytes(c) for c in policy["frozen_certs"]] == []  # Maya's old cert left the frozen list

    # The phone re-registers and gets the new cert; the shops keep their merchant ids.
    again = world.post("/v1/residents/register",
                       {"display_name": "Maya", "holder_pub": b64u_encode(old_cert.holder_pub)}, MAYA)
    assert Cert.from_json(again["cert"]) == new_cert
    latest_policy = Policy.from_json(app_client.get("/v1/policy").json()["policy"])
    assert latest_policy.policy_ver == policy["policy_ver"]


def test_reset_three_times_under_30_seconds(world, app_client):
    for _ in range(3):
        started = time.monotonic()
        out = app_client.post("/v1/demo/reset", headers=OPERATOR).json()
        assert out["ok"] and time.monotonic() - started < 30


def test_reset_can_prestage_storm_mode_and_needs_an_operator(world, app_client):
    assert app_client.post("/v1/demo/reset").status_code == 401
    out = app_client.post("/v1/demo/reset", json={"storm_cap_cents": 5000}, headers=OPERATOR).json()
    cert = Cert.from_json(out["residents"][0]["cert"])
    assert (cert.cert_ver, cert.cap_cents) == (2, 5000)
