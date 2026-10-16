"""GET /v1/accounts and /v1/health (spec §12.1, §18.2)."""

from __future__ import annotations

import pytest

from stormcash import registry
from stormcash.protocol import crypto
from stormcash.protocol.objects import b64u_decode

from .world import CORNER, GAS, PHARMACY, World, pub


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


def by_label(snapshot: dict) -> dict:
    return {a["label"]: a for a in snapshot["accounts"]}


def test_accounts_show_live_nessie_balances_and_ledger(world, app_client, deps):
    world.storm(5000)
    world.sync(PHARMACY, [world.pay("pharmacy", 1200)])
    snap = app_client.get("/v1/accounts").json()
    cards = by_label(snap)
    assert list(cards) == ["Maya Checking", "Maya Escrow", "Gas Station", "Pharmacy", "Guarantee Pool"]
    assert cards["Maya Checking"]["nessie_cents"] == 45000
    assert cards["Maya Escrow"]["nessie_cents"] == 3800
    assert cards["Pharmacy"]["nessie_cents"] == 1200
    assert cards["Guarantee Pool"]["nessie_cents"] == 100000
    assert cards["Maya Escrow"]["ledger_cents"] == 3800
    assert cards["Maya Checking"]["ledger_cents"] == -5000
    assert snap["ledger"]["balanced"] is True
    assert snap["ledger"]["totals"]["merchant"] == 1200
    assert snap["nessie"] == {"enabled": True, "queued": 0}


def test_simulated_town_is_ledger_only_totals(world, app_client, deps):
    _, mcert, _ = registry.register_merchant(deps, "Corner Store", pub(CORNER), "asheville-downtown", simulated=True)
    world.mcerts["corner_store"] = mcert
    world.sync(CORNER, [world.pay("corner_store", 500)])
    snap = app_client.get("/v1/accounts").json()
    assert "Corner Store" not in by_label(snap)
    assert snap["simulated_town"]["merchants"] == 1
    assert snap["simulated_town"]["merchant_cents"] == 500


def test_nessie_outage_shows_an_error_not_a_number(world, app_client, fake_nessie):
    fake_nessie.down = True
    deps = app_client.app.state.deps
    deps.nessie._balance_cache.clear()
    world.sync(GAS, [world.pay("gas_station", 800)])
    snap = app_client.get("/v1/accounts").json()
    gas = by_label(snap)["Gas Station"]
    assert gas["nessie_cents"] is None and gas["nessie_error"]
    assert gas["ledger_cents"] == 800
    assert snap["nessie"]["queued"] == 1


def test_health(app_client, deps):
    h = app_client.get("/v1/health").json()
    assert h["ok"] and h["nessie_enabled"] and h["api_sig_required"]
    assert b64u_decode(h["server_pub"]) == crypto.public_key_bytes(deps.server_key)
