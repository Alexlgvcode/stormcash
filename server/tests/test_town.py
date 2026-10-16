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
