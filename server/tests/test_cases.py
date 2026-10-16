"""WS2 #19: cases R1–R6, freezes, POLICY versions, contact pairing, case/proof/policy endpoints.

The R5 and R6 checks replay the shared vectors (spec/vectors.json) through the
real ingest path, with the app signing as the vector server key.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stormcash import ledger, settlement
from stormcash.app import create_app
from stormcash.db import all_rows, one, scalar
from stormcash.protocol import crypto, encoding, rules
from stormcash.protocol.objects import Item, Pay, Policy, Proof, b64u_decode, object_from_fields

from .conftest import make_settings
from .world import GAS, MAYA, PHARMACY, World, pub

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "spec" / "vectors.json").read_text())
VKEYS = {name: crypto.private_key_from_scalar(bytes.fromhex(k["priv"])) for name, k in VECTORS["keys"].items()}


def vobj(v):
    return object_from_fields(v["type"], v["fields"], v["sig"])


def vnamed(section: str, name: str) -> dict:
    return next(v for v in VECTORS[section] if v["name"] == name)


# Live cast (test server key) ------------------------------------------------------------------


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


def test_same_counter_opens_case_freezes_cert_and_publishes_policy(world, deps, app_client):
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 1200)
    world.sync(PHARMACY, [honest])
    out = world.sync(GAS, [cheat])

    policy = Policy.from_json(out["policy"])
    assert policy.policy_ver == 2 and policy.frozen_certs == (world.cert.cert_id,)
    assert policy.verify(crypto.public_key_bytes(deps.server_key))
    with deps.pool.connection() as conn:
        case = one(conn, "SELECT * FROM cases")
        assert scalar(conn, "SELECT status FROM cert_status") == "frozen"
        # The merchant didn't know: still paid, and the ledger balances.
        assert scalar(conn, "SELECT status FROM payments WHERE tag_hash = %s", (cheat.tag.tag_hash,)) == "settled"
        assert ledger.unbalanced_txns(conn) == []
    assert (case["rule"], case["detected_where"], case["exposure_cents"]) == ("SAME_COUNTER", "server", 1200)
    assert {bytes(case["tag_a"]), bytes(case["tag_b"])} == {honest.tag.tag_hash, cheat.tag.tag_hash}

    # Re-ingesting opens nothing new and publishes no new policy.
    world.sync(GAS, [cheat, honest])
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM cases") == 1
        assert scalar(conn, "SELECT max(policy_ver) FROM policy_versions") == 2

    assert app_client.get("/v1/policy").json()["policy"] == out["policy"]
    assert app_client.get("/v1/policy?since=2").json()["policy"] is None


def test_proof_item_from_a_phone_marks_the_case_offline(world, deps):
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 800)
    proof = rules.make_proof(honest.tag, cheat.tag)
    world.sync(GAS, [proof])
    with deps.pool.connection() as conn:
        case = one(conn, "SELECT * FROM cases")
        assert scalar(conn, "SELECT count(*) FROM tags") == 2
    assert (case["rule"], case["detected_where"]) == ("SAME_COUNTER", "offline")

    bogus = Proof(honest.tag, world.pay("gas_station", 100).tag, "SAME_COUNTER")
    out = world.sync(GAS, [bogus])
    assert out["rcpt"]["ids"] == []


def test_skipped_counter_and_broken_link_open_cases(world, deps):
    first = world.pay("pharmacy", 1200)
    skipped = world.pay("gas_station", 800, counter=3, prev=b"\x01" * 32, cum=800)
    world.sync(PHARMACY, [first])
    world.sync(GAS, [skipped])
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT rule FROM cases") == "TOTAL_BACKWARDS"


def test_settled_payment_over_every_cap_opens_r4(world, deps):
    """A merchant skipped C5: cum $25 on a $20 cert settles, then R4 freezes it."""
    world.sync(PHARMACY, [world.pay("pharmacy", 1500)])
    over = world.pay("gas_station", 1000)
    assert over.tag.cum_cents == 2500
    world.sync(GAS, [over])
    with deps.pool.connection() as conn:
        case = one(conn, "SELECT * FROM cases")
        assert scalar(conn, "SELECT status FROM payments WHERE tag_hash = %s", (over.tag.tag_hash,)) == "settled"
        assert scalar(conn, "SELECT status FROM cert_status") == "frozen"
        assert ledger.unbalanced_txns(conn) == []
    assert (case["rule"], case["exposure_cents"], bytes(case["tag_a"])) == ("OVER_CAP", 500, over.tag.tag_hash)


def test_storm_cap_counts_for_r4(world, deps):
    """cum $45 is over the current $20 version but not over the $50 one ever issued."""
    world.storm(5000)
    world.sync(PHARMACY, [world.pay("pharmacy", 4500)])
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM cases") == 0


def test_cases_and_proof_endpoints(world, app_client):
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 1200)
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [cheat])

    listed = app_client.get("/v1/cases").json()
    assert [c["rule"] for c in listed] == ["SAME_COUNTER"]
    case_id = listed[0]["case_id"]
    detail = app_client.get(f"/v1/cases/{case_id}").json()
    assert detail["case"]["evidence"]["rules_fired"] == ["SAME_COUNTER"]

    proof = app_client.get(f"/v1/proof/{case_id}").json()
    assert proof["rule"] == "SAME_COUNTER" and proof["holder_pub"]
    # A browser can verify each signature over the canonical string it is given.
    assert b64u_decode(proof["holder_pub"]) == pub(MAYA)
    for key in ("tag_a", "tag_b"):
        t = proof[key]
        assert object_from_fields("TAG", t["fields"], None).canonical() == t["canonical"]
        assert crypto.verify_digest(pub(MAYA), encoding.digest(t["canonical"]), b64u_decode(t["json"]["sig"]))
    assert app_client.get("/v1/proof/999").status_code == 404


# Shared vectors through the server ---------------------------------------------------------------


@pytest.fixture
def vector_deps(clean_db):
    """App signing as the vector server, with Maya's certs and the three shops
    from vectors.json seeded (simulated, so no Nessie)."""
    app = create_app(make_settings(clean_db, server_key=VKEYS["server"], nessie_enabled=False))
    with TestClient(app) as client:
        deps = client.app.state.deps
        cert_v1, cert_v2 = vobj(vnamed("objects", "cert_v1")), vobj(vnamed("objects", "cert_v2_storm_mode"))
        rid = uuid.uuid4()
        with deps.pool.connection() as conn:
            conn.execute(
                "INSERT INTO residents (resident_id, display_name, holder_pub, simulated) VALUES (%s, 'Maya', %s, TRUE)",
                (rid, cert_v1.holder_pub),
            )
            for c in (cert_v1, cert_v2):
                conn.execute(
                    """INSERT INTO certificates VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (c.cert_id, c.cert_ver, rid, c.holder_pub, c.cap_cents, c.issued_at, c.expires_at, c.escrow_ref,
                     c.sig),
                )
            conn.execute("INSERT INTO cert_status (cert_id, status, max_cap_cents) VALUES (%s, 'active', 5000)",
                         (cert_v1.cert_id,))
            ledger.post(conn, ledger.escrow(cert_v1.cert_id), ledger.checking(rid), 5000, "lock escrow")
            for name in ("pharmacy", "gas_station", "corner_store"):
                m = vobj(vnamed("objects", f"mcert_{name}"))
                conn.execute(
                    """INSERT INTO merchants (merchant_id, display_name, merchant_pub, region_id, simulated)
                       VALUES (%s, %s, %s, 'asheville-downtown', TRUE)""",
                    (m.merchant_id, name, m.merchant_pub),
                )
        yield deps


def ingest(deps, device: str, items: list) -> settlement.SyncResult:
    return settlement.ingest_items(deps, crypto.public_key_bytes(VKEYS[device]), items)


def pay_for(z_tag) -> Pay:
    """The PAY behind a scenario's z, from the merchant_checks vectors."""
    for v in VECTORS["merchant_checks"]:
        p = v["pay"]
        tag = vobj(p["t"])
        if tag.tag_hash == z_tag.tag_hash and vobj(p["c"]).verify(crypto.public_key_bytes(VKEYS["server"])):
            return Pay(vobj(p["c"]), tag, vobj(p["d"]))
    raise LookupError("no PAY for z")


@pytest.mark.parametrize("scenario", [v["name"] for v in VECTORS["merchant_knew"]])
@pytest.mark.parametrize("x_first", [True, False], ids=["x-uploaded-first", "x-after-z"])
def test_r5_vectors_through_ingest(vector_deps, scenario, x_first):
    v = vnamed("merchant_knew", scenario)
    z = vobj(v["z"])
    x_tags = [vobj(t) for t in v["cert_tags"] if vobj(t).tag_hash != z.tag_hash]
    logs = [Item("DLOG", vobj(e)) for e in v["logs"]]
    pay = Item("PAY", pay_for(z))
    tags = [Item("TAG", t) for t in x_tags]
    if x_first:
        ingest(vector_deps, "pharmacy", tags)
        ingest(vector_deps, "gas_station", logs + [pay])
    else:
        ingest(vector_deps, "gas_station", logs + [pay] + tags)  # TAGs are processed last

    expect = v["expect"]
    with vector_deps.pool.connection() as conn:
        knew = one(conn, "SELECT * FROM cases WHERE rule = 'MERCHANT_KNEW'")
        status = scalar(conn, "SELECT status FROM payments WHERE tag_hash = %s", (z.tag_hash,))
        eligible = scalar(conn, "SELECT pool_eligible FROM merchants WHERE display_name = 'gas_station'")
    if expect["fired"]:
        assert knew is not None and knew["evidence"]["clause"] == expect["clause"]
        assert bytes(knew["tag_a"]).hex() == expect["conflict"] and bytes(knew["tag_b"]) == z.tag_hash
        assert status == "denied_knowing" and eligible is False
    else:
        assert knew is None and status in ("settled", "held") and eligible is True


def test_r5_denied_payment_gets_no_pool_money(vector_deps):
    v = vnamed("merchant_knew", "a_held_ids")
    z = vobj(v["z"])
    ingest(vector_deps, "pharmacy", [Item("TAG", vobj(t)) for t in v["cert_tags"] if vobj(t).tag_hash != z.tag_hash])
    ingest(vector_deps, "gas_station", [Item("DLOG", vobj(e)) for e in v["logs"]] + [Item("PAY", pay_for(z))])
    with vector_deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM payouts WHERE tag_hash = %s", (z.tag_hash,)) == 0


@pytest.mark.parametrize("scenario", [v["name"] for v in VECTORS["log_tamper"]])
def test_r6_vectors_through_ingest(vector_deps, scenario):
    v = vnamed("log_tamper", scenario)
    ingest(vector_deps, "gas_station", [Item("DLOG", vobj(e)) for e in v["entries"]])
    with vector_deps.pool.connection() as conn:
        case = one(conn, "SELECT * FROM cases WHERE rule = 'LOG_TAMPER'")
        eligible = scalar(conn, "SELECT pool_eligible FROM merchants WHERE display_name = 'gas_station'")
    if v["expect"] is None:
        assert case is None and eligible is True
    else:
        assert (case["evidence"]["kind"], case["evidence"]["seq"]) == (v["expect"]["kind"], v["expect"]["seq"])
        assert eligible is False
        # Uploading the same entries again opens nothing new.
        ingest(vector_deps, "gas_station", [Item("DLOG", vobj(e)) for e in v["entries"]])
        with vector_deps.pool.connection() as conn:
            assert scalar(conn, "SELECT count(*) FROM cases") == 1


def test_contacts_pair_when_both_sides_upload(vector_deps):
    v = vnamed("merchant_knew", "b_paired_contact")
    entries = [vobj(e) for e in v["logs"] if e["fields"]["kind"] == "CONTACT"]
    gas_entry = next(e for e in entries if e.device_pub == crypto.public_key_bytes(VKEYS["gas_station"]))
    corner_entry = next(e for e in entries if e is not gas_entry)
    ingest(vector_deps, "gas_station", [Item("DLOG", gas_entry)])
    with vector_deps.pool.connection() as conn:
        assert scalar(conn, "SELECT bool_or(paired) FROM contacts") is False
    ingest(vector_deps, "corner_store", [Item("DLOG", corner_entry)])
    with vector_deps.pool.connection() as conn:
        assert [r["paired"] for r in all_rows(conn, "SELECT paired FROM contacts")] == [True, True]
