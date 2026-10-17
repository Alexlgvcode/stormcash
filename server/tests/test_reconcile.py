"""GET /v1/accounts/reconcile: our ledger against Nessie's own records (spec §11.4a)."""

from __future__ import annotations

import uuid

import pytest

from stormcash import ledger, registry
from stormcash.db import scalar
from stormcash.protocol import crypto
from stormcash.protocol.objects import Det, Pay, Tag, genesis

from .conftest import make_settings
from .world import CORNER, GAS, PHARMACY, World, pub

OPERATOR = {"X-SC-Operator": "test"}


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


def check(client) -> dict:
    client.app.state.deps.nessie._balance_cache.clear()  # read Nessie now, not up to 10 s ago
    resp = client.get("/v1/accounts/reconcile")
    assert resp.status_code == 200, resp.text
    return resp.json()


def by_label(result: dict) -> dict:
    return {a["label"]: a for a in result["accounts"]}


def kinds(account: dict) -> dict:
    return {k["kind"]: k["cents"] for k in account["by_kind"]}


def assert_items_add_up(result: dict) -> None:
    for a in result["accounts"]:
        if a["status"] in ("reconciled", "difference"):
            assert a["nessie_cents"] - a["expected_cents"] == a["difference_cents"]
            assert sum(i["cents"] for i in a["items"]) == a["difference_cents"]


def test_everything_reconciles_after_a_storm_and_a_payment(world, app_client):
    world.storm(5000)
    world.sync(PHARMACY, [world.pay("pharmacy", 1200)])
    result = check(app_client)
    accounts = by_label(result)
    assert list(accounts) == ["Maya Checking", "Maya Escrow", "Gas Station", "Pharmacy", "Guarantee Pool"]
    assert all(a["status"] == "reconciled" and a["items"] == [] for a in accounts.values())
    checking = accounts["Maya Checking"]
    # Nessie keeps the $500 opening as the account's fixed balance; our ledger books only movements.
    assert checking["opening"]["cents"] == checking["opening"]["nessie_cents"] == 50000
    assert checking["opening"]["source"] == "call_log"
    assert (checking["ledger_cents"], checking["expected_cents"], checking["nessie_cents"]) == (-5000, 45000, 45000)
    assert (accounts["Maya Escrow"]["nessie_cents"], accounts["Pharmacy"]["nessie_cents"]) == (3800, 1200)
    # The pool was opened by nessie_setup before this database existed: only Nessie knows its opening.
    assert accounts["Guarantee Pool"]["opening"] == {"cents": 100000, "source": "nessie", "call_id": None,
                                                     "at": None, "nessie_cents": 100000}
    # lock $20, Storm Mode top-up $30, payment $12: three complete pairs.
    assert result["pairs"] == {"checked": 3, "complete": 3, "problems": [], "problems_total": 0}
    assert result["ok"] and result["last_ok_at"] == result["checked_at"]


def test_a_queued_payout_is_the_difference(world, app_client, fake_nessie):
    fake_nessie.down = True
    world.sync(PHARMACY, [world.pay("pharmacy", 1200)])
    fake_nessie.down = False  # back up, but the replay loop hasn't run yet
    result = check(app_client)
    accounts = by_label(result)
    assert (accounts["Pharmacy"]["status"], accounts["Pharmacy"]["difference_cents"]) == ("difference", -1200)
    assert kinds(accounts["Pharmacy"]) == {"queued": -1200}
    assert kinds(accounts["Maya Escrow"]) == {"queued": 1200}
    assert "Escrow → Pharmacy $12.00: queued since" in accounts["Pharmacy"]["items"][0]["text"]
    assert accounts["Maya Checking"]["status"] == "reconciled"
    assert [p["kind"] for p in result["pairs"]["problems"]] == ["queued"]
    assert_items_add_up(result)

    assert app_client.app.state.deps.mover.replay_queued() == 1
    result = check(app_client)
    assert all(a["status"] == "reconciled" for a in result["accounts"])
    assert result["pairs"]["complete"] == result["pairs"]["checked"] == 2


def test_half_a_pair_names_the_missing_half(world, app_client, fake_nessie):
    fake_nessie.fail = {"deposits"}
    world.sync(PHARMACY, [world.pay("pharmacy", 1200)])
    fake_nessie.fail = set()
    result = check(app_client)
    accounts = by_label(result)
    assert accounts["Maya Escrow"]["status"] == "reconciled"  # the withdrawal half is there
    assert kinds(accounts["Pharmacy"]) == {"half_pair": -1200}
    assert "the withdrawal is in Nessie, the deposit isn't yet" in accounts["Pharmacy"]["items"][0]["text"]
    problems = result["pairs"]["problems"]
    assert [p["kind"] for p in problems] == ["half_pair"]
    assert "the deposit on Pharmacy is missing" in problems[0]["text"]
    assert_items_add_up(result)


def test_non_whole_dollars_are_ledger_only(world, app_client):
    world.sync(PHARMACY, [world.pay("pharmacy", 1250)])
    result = check(app_client)
    accounts = by_label(result)
    assert kinds(accounts["Pharmacy"]) == {"ledger_only": -1250}
    assert kinds(accounts["Maya Escrow"]) == {"ledger_only": 1250}
    assert "not whole dollars" in accounts["Pharmacy"]["items"][0]["text"]
    assert result["pairs"]["problems"] == []  # nothing was sent, so no pair to check
    assert_items_add_up(result)


def test_a_movement_with_no_reason_to_skip_nessie_is_unexplained(world, app_client, deps):
    with deps.pool.connection() as conn:
        ledger.post(conn, ledger.merchant(world.mcerts["gas_station"].merchant_id),
                    ledger.escrow(world.cert.cert_id), 500, "manual entry")
    result = check(app_client)
    gas = by_label(result)["Gas Station"]
    assert (gas["status"], kinds(gas)) == ("difference", {"unexplained": -500})
    assert "whole dollars between real accounts, but no Nessie move was queued" in gas["items"][0]["text"]
    assert_items_add_up(result)


def test_nessie_records_we_do_not_have_are_listed(world, app_client, fake_nessie):
    stray = uuid.uuid4()
    fake_nessie.records[fake_nessie.pool_id] += [
        {"_id": "w1", "type": "withdrawals", "amount": 4, "status": "completed", "transaction_date": "2026-10-16",
         "description": f"SC {stray} Guarantee pool → Smoke Gas", "medium": "balance"},
        {"_id": "d1", "type": "deposits", "amount": 7, "status": "completed", "transaction_date": "2026-10-16",
         "description": "manual top-up", "medium": "balance"},
        {"_id": "d2", "type": "deposits", "amount": 9, "status": "pending", "transaction_date": "2026-10-16",
         "description": "still pending", "medium": "balance"},
    ]
    result = check(app_client)
    pool = by_label(result)["Guarantee Pool"]
    assert (pool["nessie_cents"], pool["expected_cents"]) == (100300, 100000)
    assert kinds(pool) == {"not_in_ledger": -400, "unlinked": 700}
    text = next(i["text"] for i in pool["items"] if i["kind"] == "not_in_ledger")
    assert f"SC {str(stray)[:8]}… \"Guarantee pool → Smoke Gas\"" in text and "not in our call log either" in text
    assert pool["records"] == {"deposits": 2, "withdrawals": 1, "linked": 1, "unlinked": 2, "not_completed": 1}
    assert [p["kind"] for p in result["pairs"]["problems"]] == ["not_in_ledger"]
    assert_items_add_up(result)


def test_after_a_demo_reset_every_account_reconciles_on_fresh_accounts(world, app_client, fake_nessie):
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [world.pay("gas_station", 1200)])  # $8 from escrow, $4 from the pool
    fake_nessie.records[fake_nessie.pool_id].append(  # a stray record, like the live pool's smoke test
        {"_id": "w1", "type": "withdrawals", "amount": 4, "status": "completed", "transaction_date": "2026-10-16",
         "description": f"SC {uuid.uuid4()} Guarantee pool → Smoke Gas", "medium": "balance"})
    assert by_label(check(app_client))["Guarantee Pool"]["status"] == "difference"

    out = app_client.post("/v1/demo/reset", headers=OPERATOR).json()
    result = check(app_client)
    assert result["ok"] and all(a["status"] == "reconciled" for a in result["accounts"])
    pool = by_label(result)["Guarantee Pool"]
    assert pool["nessie_account_id"] == out["pool"]["account_id"] != fake_nessie.pool_id
    # The fresh pool's opening is read from our own call log, not taken from Nessie.
    assert pool["opening"]["source"] == "call_log" and pool["opening"]["cents"] == 100000
    assert (pool["expected_cents"], pool["nessie_cents"], pool["items"]) == (100000, 100000, [])
    assert result["pairs"]["problems"] == []


def test_nessie_records_whose_ledger_txn_is_gone_are_explained_by_our_call_log(world, app_client, deps):
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [world.pay("gas_station", 1200)])
    with deps.pool.connection() as conn:  # the pool payout's ledger txn and move disappear; Nessie keeps the pair
        txn = scalar(conn, "SELECT txn_id FROM ledger_entries WHERE account = 'pool'")
        conn.execute("DELETE FROM ledger_entries WHERE txn_id = %s", (txn,))
        conn.execute("DELETE FROM nessie_moves WHERE txn_id = %s", (txn,))
    result = check(app_client)
    pool, gas = by_label(result)["Guarantee Pool"], by_label(result)["Gas Station"]
    assert kinds(pool) == {"not_in_ledger": -400} and kinds(gas) == {"not_in_ledger": 400}
    text = pool["items"][0]["text"]
    assert "\"Guarantee pool → Gas Station\"" in text and "our call log has the POST" in text
    assert "its other half went to Gas Station" in text
    assert_items_add_up(result)


def test_simulated_money_is_ledger_only_not_a_difference(world, app_client, deps):
    sim_key = crypto.private_key_from_scalar(0x999)
    _, cert, _ = registry.register_resident(deps, "Sim resident", pub(sim_key), "swannanoa", simulated=True)
    pharmacy = world.mcerts["pharmacy"].merchant_pub
    pays = []
    for nonce, amount in ((b"\x09", 2000), (b"\x0a", 1500)):  # the second one needs the pool
        det = Det(pharmacy, nonce * 16, 1)
        tag = Tag(cert.cert_id, 1, genesis(cert.cert_id), amount, amount, det.digest()).signed(sim_key)
        pays.append(Pay(cert, tag, det))
    world.sync(PHARMACY, pays)
    _, mcert, _ = registry.register_merchant(deps, "Corner Store", pub(CORNER), "asheville-downtown", simulated=True)
    world.mcerts["corner_store"] = mcert
    world.sync(CORNER, [world.pay("corner_store", 500)])

    result = check(app_client)
    accounts = by_label(result)
    assert "Corner Store" not in accounts
    assert all(a["status"] == "reconciled" for a in accounts.values())
    assert accounts["Pharmacy"]["simulated"]["cents"] == 3500 and accounts["Pharmacy"]["ledger_cents"] == 3500
    assert accounts["Pharmacy"]["expected_cents"] == accounts["Pharmacy"]["nessie_cents"] == 0
    assert accounts["Guarantee Pool"]["simulated"] == {"cents": -1500, "txns": 1,
                                                       "label": "ledger only, never sent to Nessie"}
    assert accounts["Maya Escrow"]["simulated"]["cents"] == -500
    assert result["simulated_town"]["merchant_cents"] == 500


def test_an_opening_balance_nessie_disagrees_with(world, app_client, fake_nessie):
    checking = by_label(check(app_client))["Maya Checking"]["nessie_account_id"]
    fake_nessie.accounts[checking]["balance"] = 400
    result = check(app_client)
    account = by_label(result)["Maya Checking"]
    assert kinds(account) == {"opening": -10000}
    assert "Nessie's opening balance is $400.00; our call log #" in account["items"][0]["text"]


def test_nessie_down_says_so_and_keeps_the_last_good_time(world, app_client, fake_nessie):
    first = check(app_client)
    fake_nessie.down = True
    result = check(app_client)
    assert result["ok"] is False and result["nessie"]["error"]
    assert all(a["status"] == "error" and "nessie_cents" not in a for a in result["accounts"])
    assert result["last_ok_at"] == first["checked_at"]


def test_nessie_switched_off_is_ledger_only(clean_db, fake_nessie):
    from fastapi.testclient import TestClient

    from stormcash.app import create_app
    from stormcash.photon.config import PhotonSettings

    app = create_app(make_settings(clean_db, nessie_enabled=False), photon=PhotonSettings(disabled=True))
    with TestClient(app) as client:
        World(client)
        result = client.get("/v1/accounts/reconcile").json()
    assert result["nessie"] == {"enabled": False, "error": None} and result["last_ok_at"] is None
    assert {a["status"] for a in result["accounts"]} == {"no_nessie_account"}
