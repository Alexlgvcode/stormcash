"""The demo dry run (spec §21.6): every beat against the app with a fake Nessie, the reset it ends with,
and StormDesk never queued for its identities (no Droid, no Factory credits)."""

from __future__ import annotations

import asyncio
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from stormcash import registry
from stormcash.app import create_app
from stormcash.db import all_rows, scalar
from stormcash.dryrun import VERIFY_BIN, DryRun, NessieReader, Phone, Wallet, schema_problems
from stormcash.protocol import crypto, rules
from stormcash.protocol.objects import Cert, Mcert, Req, b64u_encode, genesis
from stormcash.stormdesk.worker import Worker, pending_jobs

from .conftest import SERVER_DIR, SERVER_KEY, make_settings
from .world import CORNER, GAS, MAYA, World, pub
from .world import Wallet as WorldWallet

SERVER_PUB = crypto.public_key_bytes(SERVER_KEY)
OPERATOR = {"X-SC-Operator": "test"}
TABLES_SKIPPED = {"policy_versions"}  # versions only go up; the content is compared instead


def seed_corner_store(deps) -> int:
    """A stand-in for the seeded town: the simulated Corner Store with Droid's flag and an agreeing review."""
    merchant_id, _, _ = registry.register_merchant(deps, "Corner Store", pub(CORNER), "asheville-downtown", 5, 5,
                                                   simulated=True)
    with deps.pool.connection() as conn:
        candidate = scalar(conn, """INSERT INTO candidates (kind, subject_id, window_start, window_end, features)
                                    VALUES ('merchant_silence', %s, 0, 21600, '{}') RETURNING candidate_id""",
                           (merchant_id.hex(),))
        run_id = scalar(conn, """INSERT INTO stormdesk_runs (job, candidate_id, runner, status, transcript)
                                 VALUES ('triage', %s, 'droid', 'succeeded', %s) RETURNING run_id""",
                        (candidate, Jsonb({"runner": "droid", "model": "claude-sonnet-5-5", "steps": []})))
        return scalar(conn, """INSERT INTO flags (candidate_id, kind, severity, subject_id, evidence_ids, exposure_cents,
                                                  summary, proposed_action, citations_valid, agent_transcript, review)
                               VALUES (%s, 'merchant_silence', 'urgent', %s, %s, 4000, 'Silent shop', 'hold_pool_payout',
                                       TRUE, %s, %s) RETURNING flag_id""",
                      (candidate, merchant_id.hex(), [merchant_id.hex()], Jsonb({"runner": "droid", "run_id": run_id}),
                       Jsonb({"verdict": "agree", "runner": "droid", "status": "succeeded"})))


def snapshot(deps) -> dict[str, int]:
    with deps.pool.connection() as conn:
        tables = [r["tablename"] for r in all_rows(conn, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
        return {t: scalar(conn, f"SELECT count(*) FROM {t}") for t in sorted(set(tables) - TABLES_SKIPPED)}


def latest_policy_lists(deps) -> tuple[list[bytes], list[str]]:
    with deps.pool.connection() as conn:
        row = all_rows(conn, "SELECT * FROM policy_versions ORDER BY policy_ver DESC LIMIT 1")[0]
    return sorted(bytes(c) for c in row["frozen_certs"]), sorted(row["merchant_limits"])


def dry_run(app_client, deps, fake_nessie, **kwargs) -> tuple[DryRun, bool, str]:
    out = io.StringIO()
    run = DryRun(app_client, deps.pool, server_pub=SERVER_PUB, server_pub_source="test",
                 nessie=NessieReader("https://nessie.test", "test-key", transport=fake_nessie.transport()),
                 verify_bin=VERIFY_BIN if VERIFY_BIN.is_file() else None, out=out, **kwargs)
    ok = run.run()
    return run, ok, out.getvalue()


@pytest.fixture
def table(app_client, deps):
    """The demo table: the real cast registered, the town's Corner Store flag, then a reset."""
    world = World(app_client)
    seed_corner_store(deps)
    assert app_client.post("/v1/demo/reset", headers=OPERATOR).status_code == 200
    return world


def test_every_beat_passes_and_the_table_ends_as_a_reset_leaves_it(table, app_client, deps, fake_nessie):
    # What one more plain reset changes (new Nessie accounts, their call log, Maya's new lock)...
    before_reset = snapshot(deps)
    assert app_client.post("/v1/demo/reset", headers=OPERATOR).status_code == 200
    after_reset = snapshot(deps)
    policy_after_reset = latest_policy_lists(deps)

    run, ok, out = dry_run(app_client, deps, fake_nessie)
    assert ok, out
    assert [r[2] for r in run.results] == [True] * 9, out
    assert out.count("✓") == 9 and "All 9 steps passed" in out
    assert "C6 SAME_COUNTER" in out and "C6 BROKEN_LINK + TOTAL_BACKWARDS" in out
    assert "escrow $20 → $50 in Nessie" in out and "Pharmacy → Maya → Gas Station → server (2 hops)" in out
    assert "reviewer (Droid): agree" in out

    # ...is exactly what the dry run changes: nothing of it is left, and no StormDesk run was written.
    after_dry_run = snapshot(deps)
    assert {t: after_dry_run[t] - after_reset[t] for t in after_dry_run} == \
        {t: after_reset[t] - before_reset[t] for t in after_reset}
    assert latest_policy_lists(deps) == policy_after_reset
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM residents WHERE display_name LIKE 'Dry-run%%'") == 0
        assert scalar(conn, "SELECT count(*) FROM nessie_calls WHERE summary LIKE '%%Dry-run%%'") == 0
        assert scalar(conn, "SELECT count(*) FROM merchants WHERE simulated") == 1  # the town is untouched


def test_the_dry_runs_hard_case_never_enqueues_a_droid_job(table, app_client, deps, fake_nessie):
    run, ok, out = dry_run(app_client, deps, fake_nessie, keep=True)
    assert ok, out
    assert "kept everything (--keep)" in out
    with deps.pool.connection() as conn:
        dry_cases = [r["case_id"] for r in all_rows(conn, "SELECT case_id FROM cases")]
        assert len(dry_cases) == 2 and run.case_id in dry_cases  # SAME_COUNTER and BROKEN_LINK, no case file
        # A candidate on a dry-run shop is skipped too; one on a real shop is not.
        shop = bytes(run.shops[run.pharmacy.name]["merchant_id"]).hex()
        real = scalar(conn, "SELECT encode(merchant_id, 'hex') FROM merchants WHERE display_name = 'Pharmacy'")
        candidates = [scalar(conn, """INSERT INTO candidates (kind, subject_id, window_start, window_end, features)
                                      VALUES ('merchant_silence', %s, 0, 1, '{}') RETURNING candidate_id""", (s,))
                      for s in (shop, real)]
        runs = scalar(conn, "SELECT count(*) FROM stormdesk_runs")

    # The real Maya's double spend still gets an investigation (her phone registers again after the reset).
    table.cert = Cert.from_json(table.post("/v1/residents/register", {"display_name": "Maya",
                                                                      "holder_pub": b64u_encode(pub(MAYA))}, MAYA)["cert"])
    table.wallet = WorldWallet(table.cert.cert_id)
    table.storm(5000)
    honest = table.pay("pharmacy", 1200)
    table.rollback()
    table.sync(GAS, [honest, table.pay("gas_station", 1200)])
    with deps.pool.connection() as conn:
        real_case = scalar(conn, "SELECT case_id FROM cases WHERE NOT case_id = ANY(%s)", (dry_cases,))

    jobs = pending_jobs(deps)
    assert [(j.kind, j.case_id, j.candidate_id) for j in jobs] == [("investigate", real_case, None),
                                                                   ("triage", None, candidates[1])]

    class Desk:  # records what the worker would start
        def __init__(self) -> None:
            self.deps, self.jobs = deps, []

        async def run(self, job):
            self.jobs.append(job)

    async def tick() -> int:
        started = await Worker(desk).tick()
        await asyncio.sleep(0)  # let the started jobs reach the desk
        return started

    desk = Desk()
    assert asyncio.run(tick()) == 2
    assert [j.kind for j in desk.jobs] == ["investigate", "triage"]
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM stormdesk_runs") == runs  # the dry run wrote none

    # A reset removes the dry run's leftovers first; the real phones and the town stay.
    out = app_client.post("/v1/demo/reset", headers=OPERATOR).json()
    assert out["dry_run_removed"] == {"residents": 1, "shops": 2, "tags": 3, "cases": 2}
    assert [r["display_name"] for r in out["residents"]] == ["Maya"]
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM merchants WHERE display_name LIKE 'Dry-run%%'") == 0
        assert scalar(conn, "SELECT count(*) FROM candidates WHERE subject_id = %s", (shop,)) == 0
        assert scalar(conn, "SELECT count(*) FROM merchants WHERE display_name = 'Corner Store'") == 1


def test_ledger_only_fallback_passes_too(clean_db):
    """NESSIE_DISABLED=1 (§22.4): money is checked in the ledger instead, and said so."""
    app = create_app(make_settings(clean_db, nessie_enabled=False))
    with TestClient(app) as client:
        deps = client.app.state.deps
        seed_corner_store(deps)
        out = io.StringIO()
        run = DryRun(client, deps.pool, server_pub=SERVER_PUB, server_pub_source="test", nessie=None, verify_bin=None,
                     out=out)
        assert run.run(), out.getvalue()
    text = out.getvalue()
    assert "escrow $20 → $50 in the ledger (NESSIE_DISABLED=1)" in text and "ledger only, Pharmacy $12" in text
    assert "stormcash-verify not built" in text


def _fake_server(routes: dict[str, httpx.Response]) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return routes.get(request.url.path, httpx.Response(404, json={"detail": "not found"}))

    return httpx.Client(base_url="http://old-server", transport=httpx.MockTransport(handle)), seen


def test_refuses_a_server_whose_stormdesk_could_run_on_the_dry_run():
    health = {"ok": True, "server_pub": b64u_encode(SERVER_PUB), "nessie_enabled": True}
    http, seen = _fake_server({"/v1/health": httpx.Response(200, json=health)})
    out = io.StringIO()
    run = DryRun(http, None, server_pub=SERVER_PUB, server_pub_source="test", nessie=None, out=out)
    assert run.run() is False
    text = out.getvalue()
    assert "refusing to run" in text and "could start Droid" in text
    assert text.count("not run: nothing was written") == 8
    assert all(s.startswith("GET") for s in seen)  # it wrote nothing


def test_refuses_a_server_signing_with_another_key():
    other = crypto.public_key_bytes(crypto.private_key_from_scalar(0xBAD))
    http, seen = _fake_server({"/v1/health": httpx.Response(200, json={"ok": True, "server_pub": b64u_encode(other)})})
    out = io.StringIO()
    assert DryRun(http, None, server_pub=SERVER_PUB, server_pub_source="test", nessie=None, out=out).run() is False
    assert f"the server signs with {other.hex()[:12]}" in out.getvalue()
    assert seen == ["GET /v1/health"]


def test_schema_check_names_what_a_migration_would_add(clean_db, deps):
    schema = (SERVER_DIR / "schema.sql").read_text()
    with deps.pool.connection() as conn:
        assert schema_problems(conn, schema) == []
        newer = schema.replace("agents_disagree BOOLEAN", "second_look TEXT,\n  agents_disagree BOOLEAN").replace(
            "('investigate','triage','review','author')",
            "('investigate','triage','review','author','audit')")
        assert schema_problems(conn, newer) == ["flags.second_look", "stormdesk_runs.job CHECK without audit"]


def test_judge_mode_rollbacks_match_the_phone():
    """mobile/src/store/wallet.ts: reuse repeats the counter; clever skips one, with the old head and total."""
    maya, shop = Phone("Dry-run Maya"), Phone("Dry-run Pharmacy")
    cert = Cert(b"\x01" * 16, 2, maya.pub, 5000, 0, 10 ** 9, "escrow").signed(SERVER_KEY)
    mcert = Mcert(b"\x02" * 16, 1, shop.pub, shop.name, "", 10 ** 9).signed(SERVER_KEY)
    wallet = Wallet(cert)

    def req() -> Req:
        return Req(mcert.merchant_id, 1200, crypto.random_nonce(), 10 ** 9).signed(shop.key)

    honest = wallet.pay(maya.key, mcert, req(), 1)
    wallet.roll_back("reuse")
    reuse = wallet.pay(maya.key, mcert, req(), 2)
    assert (reuse.tag.counter, reuse.tag.prev_hash, reuse.tag.cum_cents) == (1, genesis(cert.cert_id), 1200)
    assert rules.equivocation(honest.tag, reuse.tag) == rules.SAME_COUNTER
    wallet.roll_back("clever")
    clever = wallet.pay(maya.key, mcert, req(), 3)
    assert (clever.tag.counter, clever.tag.prev_hash, clever.tag.cum_cents) == (2, genesis(cert.cert_id), 1200)
    assert rules.rules_fired(honest.tag, clever.tag) == [rules.BROKEN_LINK, rules.TOTAL_BACKWARDS]
    assert json.loads(json.dumps(clever.to_json()))["t"]["k"] == 2
