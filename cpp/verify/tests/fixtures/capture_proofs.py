"""Capture real GET /v1/proof/{case_id} responses for the C++ proof checker.

Runs the real server app (FastAPI, settlement, cases, Postgres) through the
server's own test harness: Maya, the Pharmacy and the Gas Station register
through the API, phones upload signed items to POST /v1/sync, the server opens
the cases, and each GET /v1/proof response is saved verbatim as proof_*.json
next to this file. Nothing here builds the proof JSON, so the fixtures have
exactly the shape the server serves. Needs a throwaway Postgres (the harness
creates and drops its own `stormcash_test` database there):

    cd server
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \\
      python -m pytest -p tests.conftest ../cpp/verify/tests/fixtures/capture_proofs.py -q

Re-run it after any change to routes/cases.py and commit the new fixtures.
The keys are the harness's test keys; signatures are deterministic but item
timestamps come from the clock, so a re-run changes some bytes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from tests.test_cases import world  # noqa: F401  (pytest fixture: a fresh World on a clean DB)
from tests.world import GAS, PHARMACY, World, pub

from stormcash.protocol.objects import contact_id, id8

OUT = Path(__file__).resolve().parent


def save(world: World, rule: str, name: str) -> None:
    cases = [c for c in world.client.get("/v1/cases").json() if c["rule"] == rule]
    assert len(cases) == 1, cases
    resp = world.client.get(f"/v1/proof/{cases[0]['case_id']}")
    assert resp.status_code == 200, resp.text
    (OUT / f"proof_{name}.json").write_text(json.dumps(resp.json(), indent=2) + "\n")


def test_same_counter(world: World):
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 800)
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [cheat])
    save(world, "SAME_COUNTER", "same_counter")


def test_broken_link(world: World):
    first = world.pay("pharmacy", 1200)
    # Right counter and running total, but it doesn't link back to the first tag.
    unlinked = world.pay("gas_station", 800, prev=b"\x01" * 32)
    world.sync(PHARMACY, [first])
    world.sync(GAS, [unlinked])
    save(world, "BROKEN_LINK", "broken_link")


def test_total_backwards(world: World):
    first = world.pay("pharmacy", 1200)
    skipped = world.pay("gas_station", 800, counter=3, prev=b"\x01" * 32, cum=800)
    world.sync(PHARMACY, [first])
    world.sync(GAS, [skipped])
    save(world, "TOTAL_BACKWARDS", "total_backwards")


def test_merchant_knew_held_ids(world: World):
    """§9.4 clause (a): the Gas Station's own ACCEPT entry lists the tag it double-spends."""
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 1200)
    accept = world.log(GAS, ts=int(time.time()), kind="ACCEPT", tag_hash=cheat.tag.tag_hash,
                       cert_id=cheat.tag.cert_id, held_ids=(honest.tag.tag_hash,))
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [accept, cheat])
    save(world, "MERCHANT_KNEW", "merchant_knew_held_ids")


def test_merchant_knew_paired_contact(world: World):
    """§9.4 clause (b): a paired contact delivered the tag before the Gas Station accepted."""
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 1200)
    now = int(time.time())
    n_pharmacy, n_gas = b"\x01" * 16, b"\x02" * 16
    cid = contact_id(pub(PHARMACY), n_pharmacy, pub(GAS), n_gas)
    x8 = id8(honest.tag.tag_hash)
    pharmacy_contact = world.log(PHARMACY, ts=now - 120, kind="CONTACT", contact_id=cid, peer_pub=pub(GAS),
                                 sent_ids=(x8,), recv_ids=(), sent_overflow=0, recv_overflow=0)
    gas_contact = world.log(GAS, ts=now - 120, kind="CONTACT", contact_id=cid, peer_pub=pub(PHARMACY),
                            sent_ids=(), recv_ids=(x8,), sent_overflow=0, recv_overflow=0)
    accept = world.log(GAS, ts=now, kind="ACCEPT", tag_hash=cheat.tag.tag_hash, cert_id=cheat.tag.cert_id,
                       held_ids=())
    world.sync(PHARMACY, [honest, pharmacy_contact])
    world.sync(GAS, [gas_contact, accept, cheat])
    save(world, "MERCHANT_KNEW", "merchant_knew_paired_contact")
