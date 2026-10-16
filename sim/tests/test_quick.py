"""WS4/WS3 #32: the Town tab's quick in-memory re-sim (spec §16.6)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from stormcash.app import create_app
from stormcash.config import Settings
from stormcash.protocol import crypto
from stormcash_sim.quick import QuickParams, run_quick

KEYS = ("share_refused_offline", "share_caught_at_settlement", "mean_loss_per_cheater_cents",
        "median_hours_to_settlement")


def test_quick_model_is_seeded_fast_and_sane():
    started = time.monotonic()
    a = run_quick(QuickParams())
    assert time.monotonic() - started < 3  # the slider budget (§16.6)
    assert a == run_quick(QuickParams())  # seeded: same settings, same answer
    assert a["double_spend_attempts"] > 50
    assert 0 <= a["share_refused_offline"] <= 1 and 0 <= a["share_caught_at_settlement"] <= 1
    assert a["share_refused_offline"] + a["share_caught_at_settlement"] <= 1
    # More relays get payments to the server sooner.
    assert run_quick(QuickParams(p_uplink=0.2))["median_hours_to_settlement"] < a["median_hours_to_settlement"]


def test_quick_endpoint(fresh_db):
    settings = Settings(database_url=fresh_db, server_key=crypto.private_key_from_scalar(0x5EED),
                        nessie_enabled=False, background_tasks=False)
    with TestClient(create_app(settings)) as client:
        body = client.get("/v1/town/quick?adoption=0.4&p_link=0.5&p_uplink=0.05").json()
        assert body["simulated"] is True
        assert set(KEYS) <= set(body["current"]) and set(KEYS) <= set(body["baseline"])
        assert body["current"]["params"]["adoption"] == 0.4
        assert client.get("/v1/town/quick?adoption=5").status_code == 422
