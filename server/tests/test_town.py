"""GET /v1/town and /v1/relay/paths (spec §12.1, §18.4)."""

from __future__ import annotations

import pytest

from .world import GAS, MAYA, PHARMACY, World, pub


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


def test_town_lists_regions_and_placed_merchants(world, app_client, deps):
    with deps.pool.connection() as conn:
        conn.execute("UPDATE merchants SET x = 13, y = 10 WHERE display_name = 'Pharmacy'")
    town = app_client.get("/v1/town").json()
    assert [r["region_id"] for r in town["regions"]] == [
        "west-asheville", "asheville-downtown", "swannanoa", "black-mountain"]
    assert [(m["display_name"], m["x"], m["simulated"]) for m in town["merchants"]] == [("Pharmacy", 13, False)]
    assert town["grid"] == {"w": 40, "h": 24}
    assert town["dark_regions"] == [] and town["alerts"] == []


def test_relay_paths_name_the_carriers(world, app_client):
    from stormcash.protocol.objects import device_short_id

    pay = world.pay("pharmacy", 1200)
    path = [[device_short_id(pub(PHARMACY)), 100], [device_short_id(pub(MAYA)), 200], [device_short_id(pub(GAS)), 300]]
    world.sync(GAS, [pay], path=path)
    [row] = app_client.get("/v1/relay/paths").json()
    assert [h["name"] for h in row["path"]] == ["Pharmacy", "Maya", "Gas Station"]
    assert row["hops"] == 2 and row["uploaded_by"] == "Gas Station" and row["merchant"] == "Pharmacy"
    assert row["amount_cents"] == 1200


def test_a_real_payment_keeps_the_seeded_towns_dark_areas_and_alerts(world, app_client, deps):
    """The town runs on sim time; a real phone paying now mustn't push its dark areas and alerts out of view."""
    import time

    world.sync(GAS, [world.pay("gas_station", 500)])
    world.sync(PHARMACY, [world.pay("pharmacy", 700)])  # a real payment, now
    sim_now = int(time.time()) - 3 * 24 * 3600  # the seeded town's clock: days ago
    with deps.pool.connection() as conn:
        # The gas station stands in for a simulated shop whose payment is the town's latest.
        conn.execute("UPDATE merchants SET simulated = true WHERE display_name = 'Gas Station'")
        conn.execute("""UPDATE payments SET device_ts = %s
                        WHERE merchant_id = (SELECT merchant_id FROM merchants WHERE display_name = 'Gas Station')""",
                     (sim_now,))
        conn.execute("""INSERT INTO candidates (kind, subject_id, window_start, window_end, features)
                        VALUES ('region_dark', 'swannanoa', %s, %s, '{}')""", (sim_now - 7200, sim_now - 600))
        conn.execute("""INSERT INTO weather_alerts (alert_id, region_id, event, onset, expires, source)
                        VALUES ('replayed-1', 'swannanoa', 'Flash Flood Warning', %s, %s, 'replayed')""",
                     (sim_now - 7200, sim_now + 3600))
    town = app_client.get("/v1/town").json()
    assert town["dark_regions"] == ["swannanoa"]
    assert [a["event"] for a in town["alerts"]] == ["Flash Flood Warning"]
