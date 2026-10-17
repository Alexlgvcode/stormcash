"""WS4 #25 (+ #26's Done-when): seed 42 plants every scenario, and the real
server code catches them: hard cases incl. the R5 at Corner Store, and
candidates of all three soft kinds, each on a labeled subject."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from stormcash.app import create_app
from stormcash.config import Settings
from stormcash.db import all_rows, scalar
from stormcash.protocol import crypto
from stormcash.stormdesk.runner import Job
from stormcash.stormdesk.service import StormDesk
from stormcash_sim import outputs
from stormcash_sim.engine import Params, Sim

START = 1792238400  # 08:00 in Asheville


def test_seed_42_plants_every_scenario(sim_deps, tmp_path):
    sim = Sim(sim_deps, Params(seed=42, hours=72, start=START))
    summary = sim.run()
    assert summary["wall_seconds"] < 60
    folder = outputs.write(sim, summary, out_dir=tmp_path)
    labels = json.loads((folder / "labels.json").read_text())
    stats = json.loads((folder / "stats.json").read_text())
    by_subject = {s["subject_id"]: s for s in labels["subjects"]}

    with sim_deps.pool.connection() as conn:
        rules = {r["rule"] for r in all_rows(conn, "SELECT rule FROM cases")}
        knew = all_rows(
            conn,
            """SELECT m.display_name, c.evidence->>'clause' AS clause, p.status FROM cases c
               JOIN merchants m ON m.merchant_id = c.merchant_id JOIN payments p ON p.tag_hash = c.tag_b
               WHERE c.rule = 'MERCHANT_KNEW'""",
        )
        candidates = all_rows(conn, "SELECT kind, subject_id FROM candidates")
        corner_eligible = scalar(conn, "SELECT pool_eligible FROM merchants WHERE display_name = 'Corner Store'")
        corner_pool = all_rows(
            conn,
            """SELECT p.cert_id, p.status, p.funded_pool_cents FROM payments p JOIN merchants m USING (merchant_id)
               WHERE m.display_name = 'Corner Store' AND p.funded_pool_cents > 0""",
        )
        corner_silence = all_rows(
            conn,
            """SELECT c.features FROM candidates c JOIN merchants m ON encode(m.merchant_id, 'hex') = c.subject_id
               WHERE c.kind = 'merchant_silence' AND m.display_name = 'Corner Store'""",
        )

    # Hard cases: the double spenders (R1/R2/R3) and the planted MERCHANT_KNEW.
    assert {"SAME_COUNTER", "TOTAL_BACKWARDS", "MERCHANT_KNEW"} <= rules
    assert knew == [{"display_name": "Corner Store", "clause": "HELD_IDS", "status": "denied_knowing"}]
    assert corner_eligible is False
    # The colluder story (§16.4): while silent, Corner Store took pool money from 3 cheaters' re-spends that
    # R5 can't deny (no paired contact, nothing in held_ids). Only merchant_silence points at the shop.
    assert len({bytes(r["cert_id"]) for r in corner_pool}) >= 3
    assert all(r["status"] != "denied_knowing" for r in corner_pool)
    assert sum(r["funded_pool_cents"] for r in corner_pool) >= 6000
    assert any(c["features"]["distinct_cheater_certs"] >= 3 for c in corner_silence)

    # Soft signals: all three kinds, every one on a labeled subject.
    assert {c["kind"] for c in candidates} == {"merchant_silence", "cap_drain", "region_dark"}
    assert all(c["subject_id"] in by_subject for c in candidates)
    caught = {(c["kind"], by_subject[c["subject_id"]]["scenario"]) for c in candidates}
    assert {("merchant_silence", "colluder"), ("cap_drain", "stolen_phone"), ("region_dark", "dark_region")} <= caught
    assert ("cap_drain", "trap_stockup") in caught  # traps fire too; telling them apart is StormDesk's job

    # stats.json has every metric the Town tab charts (§16.5).
    ds = stats["double_spends"]
    assert ds["attempts"] >= 6 and ds["refused_offline"] + ds["accepted_offline"] == ds["attempts"]
    assert ds["share_refused_offline"] is not None and ds["share_caught_at_settlement"] is not None
    assert stats["mean_loss_per_cheater_cents"] > 0
    assert stats["median_hours_to_settlement"] > 0
    assert sum(stats["hops_histogram"].values()) > 500
    scenarios = {s["scenario"] for s in labels["subjects"]}
    assert scenarios == {"double_spender", "colluder", "stolen_phone", "dark_region", "trap_remote_shop",
                         "trap_victim_shop", "trap_stockup", "trap_clock_drift", "trap_quiet_region"}

    # StormDesk (#27 Done-when, fake runner): every hard case and every candidate from the
    # seeded town gets a valid output whose citations all exist.
    desk = StormDesk(sim_deps)
    jobs = [Job("investigate", case_id=r["case_id"]) for r in _rows(sim_deps, "SELECT case_id FROM cases")]
    jobs += [Job("triage", candidate_id=r["candidate_id"]) for r in _rows(sim_deps, "SELECT candidate_id FROM candidates")]
    results = [asyncio.run(desk.run(job)) for job in jobs]
    assert all(r["runner"] == "fake" for r in results)
    assert [r for r in results if r["status"] != "succeeded"] == []
    knew = next(r for r, j in zip(results, jobs, strict=True)
                if j.kind == "investigate" and r["output"]["rule"] == "MERCHANT_KNEW")
    assert knew["output"]["verified_independently"] and len(knew["output"]["evidence_ids"]) == 3  # 2 tags + ACCEPT
    silence = [r for r in results if r.get("flag") and r["flag"]["kind"] == "merchant_silence"]
    assert silence and all(r["flag"]["citations_valid"] and r["flag"]["evidence_ids"] for r in silence)


def _rows(deps, sql):
    with deps.pool.connection() as conn:
        return all_rows(conn, sql)


@pytest.fixture
def app(fresh_db):
    settings = Settings(database_url=fresh_db, server_key=crypto.private_key_from_scalar(0x5EED),
                        nessie_enabled=False, background_tasks=False)
    with TestClient(create_app(settings)) as client:
        yield client


def test_seed_town_endpoint(app, tmp_path, monkeypatch):
    monkeypatch.setattr(outputs, "OUT_DIR", tmp_path)
    body = {"seed": 9001, "hours": 3, "residents": 60,
            "corner_store_contact": {"channel": "telegram", "handle": "@cornerstore"}}
    assert app.post("/v1/demo/seed-town", json=body).status_code == 401
    started = app.post("/v1/demo/seed-town", json=body, headers={"X-SC-Operator": "test"})
    assert started.status_code == 202 and started.json()["status"] == "running"
    deadline = time.monotonic() + 60
    while (status := app.get("/v1/demo/seed-town").json())["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.2)
    assert status["status"] == "done", status
    assert status["summary"]["shops"] == 38
    assert (tmp_path / "9001" / "stats.json").exists()
    deps = app.app.state.deps
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT bool_and(simulated) FROM merchants") is True
        assert scalar(conn, """SELECT m.display_name FROM merchant_contacts c JOIN merchants m USING (merchant_id)
                               WHERE c.handle = '@cornerstore'""") == "Corner Store"
