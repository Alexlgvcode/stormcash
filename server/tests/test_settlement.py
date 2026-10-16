"""WS2 #18: /v1/sync ingest, settlement, ledger, Nessie payouts (spec §11.2–§11.4, §12.2)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from stormcash import ledger, registry, settlement
from stormcash.db import all_rows, one, scalar
from stormcash.protocol import crypto
from stormcash.protocol.objects import Cert, Item, Policy, Rcpt, Renew, b64u_encode

from .conftest import SERVER_KEY
from .world import CORNER, GAS, MAYA, PHARMACY, World, pub, signed_post

SERVER_PUB = crypto.public_key_bytes(SERVER_KEY)


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


def counts(deps) -> dict:
    with deps.pool.connection() as conn:
        return {t: scalar(conn, f"SELECT count(*) FROM {t}")
                for t in ("tags", "payments", "payouts", "ledger_entries", "nessie_moves", "device_log", "contacts")}


def nessie_writes(fake) -> int:
    return sum(1 for m, _ in fake.calls if m == "POST")


def test_pay_settles_from_escrow_in_nessie(world, deps, fake_nessie):
    world.storm(5000)
    pay = world.pay("pharmacy", 1200)
    path = [["9f1c2a3b", 1], ["44aa01de", 2], ["0b0b0b0b", 3]]
    out = world.sync(GAS, [pay], path=path)

    rcpt = Rcpt.from_json(out["rcpt"])
    assert rcpt.verify(SERVER_PUB) and rcpt.item_ids == (pay.tag.tag_hash,)
    policy = Policy.from_json(out["policy"])
    assert policy.verify(SERVER_PUB) and policy.policy_ver == 1
    assert out["certs"] == []

    with deps.pool.connection() as conn:
        p = one(conn, "SELECT * FROM payments")
        payout = one(conn, "SELECT * FROM payouts")
        res = one(conn, "SELECT * FROM residents")
        m = one(conn, "SELECT * FROM merchants WHERE display_name = 'Pharmacy'")
        assert ledger.unbalanced_txns(conn) == []
        assert ledger.balance(conn, ledger.merchant(bytes(m["merchant_id"]))) == 1200
        assert ledger.balance(conn, ledger.escrow(world.cert.cert_id)) == 3800
    assert (p["status"], p["funded_escrow_cents"], p["funded_pool_cents"]) == ("settled", 1200, 0)
    assert (p["hops"], bytes(p["relay_device"])) == (2, pub(GAS))
    assert p["path"] == path
    assert (payout["source"], payout["status"], payout["amount_cents"]) == ("escrow", "executed", 1200)
    assert payout["nessie_transfer_id"]
    assert fake_nessie.balance_dollars(res["escrow_account_id"]) == 38
    assert fake_nessie.balance_dollars(m["nessie_account_id"]) == 12


def test_reingesting_changes_nothing(world, deps, fake_nessie):
    world.storm(5000)
    items = [world.pay("pharmacy", 1200), world.pay("gas_station", 800)]
    first = world.sync(GAS, items)
    before, writes = counts(deps), nessie_writes(fake_nessie)
    again = world.sync(GAS, items)
    assert counts(deps) == before
    assert nessie_writes(fake_nessie) == writes
    assert Rcpt.from_json(again["rcpt"]).item_ids == Rcpt.from_json(first["rcpt"]).item_ids


def test_double_spend_beyond_escrow_is_paid_from_the_pool(world, deps, fake_nessie):
    """Cap $20: the pharmacy takes $12, the rolled-back wallet spends $12 again."""
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 1200)
    assert honest.tag.counter == cheat.tag.counter == 1
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [cheat])

    with deps.pool.connection() as conn:
        rows = {bytes(r["tag_hash"]): r for r in all_rows(conn, "SELECT * FROM payments")}
        pool_payout = one(conn, "SELECT * FROM payouts WHERE source = 'pool'")
        assert ledger.balance(conn, ledger.fraud_receivable(world.cert.cert_id)) == 400
        assert ledger.balance(conn, ledger.POOL) == -400
        assert ledger.balance(conn, ledger.escrow(world.cert.cert_id)) == 0
        assert ledger.unbalanced_txns(conn) == []
    c = rows[cheat.tag.tag_hash]
    assert (c["status"], c["funded_escrow_cents"], c["funded_pool_cents"]) == ("settled", 800, 400)
    assert pool_payout["status"] == "executed"
    assert fake_nessie.balance_dollars(fake_nessie.pool_id) == 996


def test_invalid_items_are_dropped(world, deps):
    world.storm(5000)
    good = world.pay("pharmacy", 1200)
    forged_cert = replace(good, cert=replace(world.cert, cap_cents=50000))
    wrong_signer = world.pay("pharmacy", 500, signer=CORNER)
    unknown_shop = replace(good, det=replace(good.det, merchant_pub=pub(CORNER)))
    garbage = {"kind": "PAY", "body": {"c": "nope"}, "path": []}
    out = world.sync(GAS, [forged_cert, wrong_signer, unknown_shop, garbage])
    assert Rcpt.from_json(out["rcpt"]).item_ids == ()
    assert counts(deps)["payments"] == 0 and counts(deps)["tags"] == 0


def test_over_cap_payment_is_stored_but_not_paid(world, deps):
    pay = world.pay("pharmacy", 2100)  # cap is $20: a merchant must have skipped C5
    out = world.sync(PHARMACY, [pay])
    assert Rcpt.from_json(out["rcpt"]).item_ids == (pay.tag.tag_hash,)
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM payments") == "invalid"
        assert scalar(conn, "SELECT count(*) FROM payouts") == 0


def test_dlog_entries_are_stored_and_a_refused_pay_is_evidence(world, deps):
    honest = world.pay("pharmacy", 1200)
    world.rollback()
    cheat = world.pay("gas_station", 800)
    refuse = world.log(GAS, ts=100, kind="REFUSE", tag_hash=cheat.tag.tag_hash, cert_id=world.cert.cert_id, check="C6")
    contact = world.log(GAS, ts=101, kind="CONTACT", contact_id=b"\x07" * 32, peer_pub=pub(MAYA),
                        sent_ids=(), recv_ids=(honest.tag.tag_hash[:8],), sent_overflow=0, recv_overflow=0)
    # PAY listed before the DLOG: ingest still processes the REFUSE entry first.
    out = world.sync(GAS, [cheat, refuse, contact])
    assert set(Rcpt.from_json(out["rcpt"]).item_ids) == {cheat.tag.tag_hash, refuse.entry_hash, contact.entry_hash}
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM payments") == "refused_evidence"
        assert scalar(conn, "SELECT count(*) FROM payouts") == 0
        assert scalar(conn, "SELECT count(*) FROM device_log") == 2
        c = one(conn, "SELECT * FROM contacts")
    assert bytes(c["peer_pub"]) == pub(MAYA) and [bytes(x) for x in c["recv_ids"]] == [honest.tag.tag_hash[:8]]

    tampered = replace(contact, ts=999)  # signature no longer matches
    out = world.sync(GAS, [tampered])
    assert Rcpt.from_json(out["rcpt"]).item_ids == ()


def test_renew_issues_a_new_version_once(world, deps):
    later = world.cert.issued_at + 3600
    renew = Renew(world.cert.cert_id, world.wallet.head, 0, later).signed(MAYA)
    first = settlement.ingest_items(deps, pub(MAYA), [Item("RENEW", renew)], now=later)
    assert [c.cert_ver for c in first.certs] == [2]
    v2 = first.certs[0]
    assert v2.verify(SERVER_PUB) and v2.cap_cents == 2000 and v2.expires_at == later + 72 * 3600
    again = settlement.ingest_items(deps, pub(MAYA), [Item("RENEW", renew)], now=later + 60)
    assert again.certs == [v2]

    with deps.pool.connection() as conn:
        conn.execute("UPDATE cert_status SET status = 'frozen'")
    renew2 = Renew(world.cert.cert_id, world.wallet.head, 0, later + 7200).signed(MAYA)
    frozen = settlement.ingest_items(deps, pub(MAYA), [Item("RENEW", renew2)], now=later + 7200)
    assert frozen.certs == [] and frozen.accepted == [renew2.digest()]

    forged = Renew(world.cert.cert_id, world.wallet.head, 0, later).signed(CORNER)
    assert settlement.ingest_items(deps, pub(MAYA), [Item("RENEW", forged)]).dropped == 1


def test_sync_over_http_returns_renewed_certs(world, app_client):
    # A RENEW sent now is answered with the latest version (issued moments ago).
    renew = Renew(world.cert.cert_id, world.wallet.head, 0, world.cert.issued_at).signed(MAYA)
    out = world.sync(MAYA, [renew])
    assert [Cert.from_json(c) for c in out["certs"]] == [world.cert]


def test_payout_is_queued_while_nessie_is_down_then_replayed(world, deps, fake_nessie):
    pay = world.pay("pharmacy", 1200)
    fake_nessie.down = True
    world.sync(PHARMACY, [pay])
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT status FROM payments") == "settled"
        assert scalar(conn, "SELECT status FROM payouts") == "queued"
    fake_nessie.down = False
    assert deps.mover.replay_queued() == 1
    with deps.pool.connection() as conn:
        payout = one(conn, "SELECT * FROM payouts")
    assert payout["status"] == "executed" and payout["nessie_transfer_id"]


def test_simulated_merchant_and_fractional_amounts_are_ledger_only(world, deps, fake_nessie):
    _, mcert, _ = registry.register_merchant(deps, "Corner Store", pub(CORNER), "asheville-downtown", simulated=True)
    world.mcerts["corner_store"] = mcert
    writes = nessie_writes(fake_nessie)
    world.sync(CORNER, [world.pay("corner_store", 500), world.pay("pharmacy", 1250)])
    with deps.pool.connection() as conn:
        statuses = sorted(r["status"] for r in all_rows(conn, "SELECT status FROM payouts"))
        assert ledger.unbalanced_txns(conn) == []
    assert statuses == ["ledger_only", "ledger_only"]
    assert nessie_writes(fake_nessie) == writes


def test_sync_must_be_signed_by_the_device(world, app_client):
    payload = {"device_pub": b64u_encode(pub(GAS)), "items": []}
    assert signed_post(app_client, "/v1/sync", payload, PHARMACY).status_code == 403


def test_upload_and_payment_events_are_published(world, deps, monkeypatch):
    seen = []
    monkeypatch.setattr(deps.events, "publish", lambda event, data: seen.append((event, data)))
    world.sync(PHARMACY, [world.pay("pharmacy", 1200)])
    kinds = [e for e, _ in seen]
    assert "payment" in kinds and kinds[-1] == "upload"
    payment = next(d for e, d in seen if e == "payment")
    assert payment["status"] == "settled" and payment["merchant_name"] == "Pharmacy"
    upload = seen[-1][1]
    assert (upload["item_count"], upload["accepted"], upload["region_id"]) == (1, 1, "asheville-downtown")
    assert bytes(upload["device_pub"]) == pub(PHARMACY)
