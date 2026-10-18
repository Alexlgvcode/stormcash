"""WS3/WS5 #30: operator decisions on StormDesk flags run the §14.6 actions."""

from __future__ import annotations

import asyncio

import pytest

from stormcash import detectors, ledger
from stormcash.db import all_rows, one, scalar
from stormcash.protocol.objects import Policy
from stormcash.stormdesk.runner import Job
from stormcash.stormdesk.service import StormDesk

from .world import GAS, PHARMACY, World

OPERATOR = {"X-SC-Operator": "alex"}


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


@pytest.fixture
def silence_flag(world, deps, fake_nessie):
    """A merchant_silence flag on the Gas Station, whose pool payout is still queued (Nessie was down)."""
    honest = world.pay("pharmacy", 1500)
    world.rollback()
    cheat = world.pay("gas_station", 1500)  # $5 escrow + $10 pool
    world.sync(PHARMACY, [honest])
    fake_nessie.down = True
    world.sync(GAS, [cheat])
    fake_nessie.down = False
    with deps.pool.connection() as conn:
        conn.execute("UPDATE merchants SET x = 10, y = 10")
        [cand] = detectors.merchant_silence(conn, (cheat.det.ts // 3600 + 1) * 3600)
    out = asyncio.run(StormDesk(deps).run(Job("triage", candidate_id=cand["candidate_id"])))
    assert out["flag"]["status"] == "open" and out["flag"]["proposed_action"] == "hold_pool_payout"
    return {"flag_id": out["flag"]["flag_id"], "cheat": cheat, "merchant_id": out["flag"]["subject_id"]}


def make_flag(deps, action: str, subject: str, params: dict | None = None) -> int:
    from psycopg.types.json import Jsonb

    with deps.pool.connection() as conn:
        n = scalar(conn, "SELECT count(*) FROM candidates")  # a fresh window each time
        cand = scalar(conn, """INSERT INTO candidates (kind, subject_id, window_start, window_end, features)
                               VALUES ('cap_drain', %s, %s, %s, '{}') RETURNING candidate_id""", (subject, n, n + 1))
        return scalar(
            conn,
            """INSERT INTO flags (candidate_id, kind, severity, subject_id, evidence_ids, exposure_cents, summary,
                                  proposed_action, citations_valid, agent_transcript, status)
               VALUES (%s, 'cap_drain', 'review', %s, '{}', 0, 's', %s, TRUE, %s, 'open') RETURNING flag_id""",
            (cand, subject, action, Jsonb({"action_params": params or {}})),
        )


def test_approving_a_silence_flag_holds_pool_money_live(app_client, deps, silence_flag, monkeypatch):
    """Done-when for #30."""
    seen = []
    monkeypatch.setattr(deps.events, "publish", lambda e, d: seen.append((e, d)))
    mid = bytes.fromhex(silence_flag["merchant_id"])
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM payouts WHERE source = 'pool'") == "queued"
        merchant_before = ledger.balance(conn, ledger.merchant(mid))

    out = app_client.post(f"/v1/flags/{silence_flag['flag_id']}/approve", json={"note": "silent 6 h"},
                          headers=OPERATOR).json()
    assert out["status"] == "approved"
    assert out["executed_actions"] == {"action": "hold_pool_payout", "merchant": "Gas Station", "payouts_held": 1,
                                       "held_cents": 1000, "future_pool_payouts": "held"}
    assert (out["approval"]["operator"], out["approval"]["note"]) == ("alex", "silent 6 h")
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM payouts WHERE source = 'pool'") == "held"
        assert scalar(conn, "SELECT count(*) FROM nessie_moves WHERE payout_id IS NOT NULL AND status = 'queued'") == 1
        assert scalar(conn, "SELECT status FROM payments WHERE tag_hash = %s",
                      (silence_flag["cheat"].tag.tag_hash,)) == "held"
        assert ledger.balance(conn, ledger.merchant(mid)) == merchant_before - 1000
        assert ledger.balance(conn, ledger.fraud_receivable(silence_flag["cheat"].cert.cert_id)) == 0
        assert ledger.unbalanced_txns(conn) == []
        assert scalar(conn, "SELECT pool_eligible FROM merchants WHERE merchant_id = %s", (mid,)) is False
        assert scalar(conn, "SELECT status FROM flags") == "approved"
    # The escrow half (still queued) goes ahead; the held pool half never reaches Nessie.
    assert deps.mover.replay_queued() == 1
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM payouts WHERE source = 'pool'") == "held"
    assert any(e == "approval" for e, _ in seen)  # the dashboard sees it live


def test_future_pool_money_is_held_after_approval(app_client, world, deps, silence_flag):
    app_client.post(f"/v1/flags/{silence_flag['flag_id']}/approve", headers=OPERATOR)
    world.rollback()
    again = world.pay("gas_station", 1500)
    world.sync(GAS, [again])
    with deps.pool.connection() as conn:
        row = one(conn, "SELECT * FROM payments WHERE tag_hash = %s", (again.tag.tag_hash,))
    assert (row["status"], row["funded_pool_cents"]) == ("held", 0)


def test_reject_runs_nothing_and_decisions_are_final(app_client, deps, silence_flag):
    flag_id = silence_flag["flag_id"]
    assert app_client.post(f"/v1/flags/{flag_id}/reject").status_code == 401
    out = app_client.post(f"/v1/flags/{flag_id}/reject", json={"note": "remote shop"}, headers=OPERATOR).json()
    assert out["status"] == "rejected" and out["executed_actions"] == {"action": "none"}
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM payouts WHERE source = 'pool'") == "queued"
        assert scalar(conn, "SELECT pool_eligible FROM merchants WHERE display_name = 'Gas Station'") is True
    assert app_client.post(f"/v1/flags/{flag_id}/approve", headers=OPERATOR).status_code == 409
    assert [a["decision"] for a in app_client.get(f"/v1/flags/{flag_id}/approvals").json()] == ["reject"]


def test_lower_limit_freeze_and_relay(app_client, world, deps):
    shop = world.mcerts["gas_station"].merchant_id.hex()
    limit = make_flag(deps, "lower_merchant_limit", shop, {"limit_cents": 1000})
    out = app_client.post(f"/v1/flags/{limit}/approve", headers=OPERATOR).json()
    assert out["executed_actions"]["limit_cents"] == 1000
    policy = Policy.from_json(app_client.get("/v1/policy").json()["policy"])
    assert policy.merchant_limit(bytes.fromhex(shop)) == 1000

    freeze = make_flag(deps, "freeze_cert", world.cert.cert_id.hex())
    app_client.post(f"/v1/flags/{freeze}/approve", headers=OPERATOR)
    policy = Policy.from_json(app_client.get("/v1/policy").json()["policy"])
    assert world.cert.cert_id in policy.frozen_certs

    relay = make_flag(deps, "dispatch_relay", "swannanoa")
    out = app_client.post(f"/v1/flags/{relay}/approve", headers=OPERATOR).json()
    assert out["executed_actions"] == {"action": "dispatch_relay", "task": "Send a relay to swannanoa"}

    bad = make_flag(deps, "lower_merchant_limit", shop, {})
    assert app_client.post(f"/v1/flags/{bad}/approve", headers=OPERATOR).status_code == 400


def test_invalid_flags_cannot_be_approved(app_client, deps, world):
    flag_id = make_flag(deps, "freeze_cert", world.cert.cert_id.hex())
    with deps.pool.connection() as conn:
        conn.execute("UPDATE flags SET citations_valid = FALSE")
    assert app_client.post(f"/v1/flags/{flag_id}/approve", headers=OPERATOR).status_code == 400
    assert app_client.post("/v1/flags/999/approve", headers=OPERATOR).status_code == 404


def test_reset_clears_approvals(app_client, deps, silence_flag):
    app_client.post(f"/v1/flags/{silence_flag['flag_id']}/approve", headers=OPERATOR)
    assert app_client.post("/v1/demo/reset", headers=OPERATOR).json()["ok"]
    with deps.pool.connection() as conn:
        assert all_rows(conn, "SELECT * FROM approvals") == []
        assert scalar(conn, "SELECT bool_and(pool_eligible) FROM merchants") is True
