"""Focused unit tests for stormcash.protocol beyond the shared vectors."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from stormcash.protocol import crypto, rules
from stormcash.protocol.encoding import EncodingError
from stormcash.protocol.objects import (
    Cert,
    Det,
    Dlog,
    Item,
    Mcert,
    Pay,
    Policy,
    Req,
    Tag,
    b64u_decode,
    b64u_encode,
    contact_id,
    dlog_genesis,
    genesis,
    id8,
)

MAYA = crypto.private_key_from_scalar(7)
SHOP = crypto.private_key_from_scalar(11)
SERVER = crypto.private_key_from_scalar(13)
CERT_ID = bytes(range(16))


def test_canonical_tag_by_hand():
    """A TAG's canonical string, assembled by hand from §7.2 and §7.4."""
    det_hash = b"\xab" * 32
    tag = Tag(CERT_ID, 1, genesis(CERT_ID), 1200, 1200, det_hash)
    gen = hashlib.sha256(("SC1|GEN|" + CERT_ID.hex()).encode()).digest()
    expected = f"SC1|TAG|000102030405060708090a0b0c0d0e0f|1|{gen.hex()}|1200|1200|{'ab' * 32}"
    assert tag.canonical() == expected
    assert tag.tag_hash == hashlib.sha256(expected.encode()).digest()


def test_rfc6979_p256_sha256_sample():
    """RFC 6979 A.2.5 (P-256, SHA-256, "sample"): our deterministic signer
    matches the RFC, so noble (also RFC 6979) yields the same r and low-S s."""
    if not crypto.DETERMINISTIC_SIGNING:
        pytest.skip("OpenSSL build lacks deterministic ECDSA")
    key = crypto.private_key_from_scalar(0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721)
    sig = crypto.sign_digest(key, hashlib.sha256(b"sample").digest())
    r, s = crypto.raw_to_rs(sig)
    assert r == 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
    assert s == crypto.N - 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8


def test_sign_is_low_s_and_high_s_verifies():
    pub = crypto.public_key_bytes(MAYA)
    for i in range(20):
        digest = hashlib.sha256(bytes([i])).digest()
        sig = crypto.sign_digest(MAYA, digest)
        assert crypto.is_low_s(sig)
        r, s = crypto.raw_to_rs(sig)
        assert crypto.verify_digest(pub, digest, sig)
        assert crypto.verify_digest(pub, digest, crypto.rs_to_raw(r, crypto.N - s))


@pytest.mark.parametrize(
    "pub, sig",
    [
        (crypto.public_key_bytes(MAYA)[:32], None),  # short key
        (b"\x04" + bytes(32), None),  # bad prefix
        (b"\x02" + b"\xff" * 32, None),  # x not on the curve
        (None, b"\x01" * 63),  # short signature
        (None, bytes(64)),  # r = s = 0
    ],
)
def test_verify_rejects_malformed(pub, sig):
    digest = hashlib.sha256(b"x").digest()
    good_sig = crypto.sign_digest(MAYA, digest)
    pub = crypto.public_key_bytes(MAYA) if pub is None else pub
    assert crypto.verify_digest(pub, digest, good_sig if sig is None else sig) is False


def test_public_key_is_compressed_33_bytes():
    pub = crypto.public_key_bytes(MAYA)
    assert len(pub) == 33 and pub[0] in (2, 3)
    assert crypto.public_key_bytes(crypto.load_public_key(pub)) == pub


def test_random_ids():
    assert len(crypto.random_id()) == 16 and len(crypto.random_nonce()) == 16
    assert crypto.random_id() != crypto.random_id()


def test_base64url_is_strict():
    assert b64u_encode(b"\xfb\xff") == "-_8"
    assert b64u_decode("-_8") == b"\xfb\xff"
    for bad in ("-_8=", "+/8", "AB", "A", "a b"):
        with pytest.raises(EncodingError):
            b64u_decode(bad)


def test_from_json_rejects_unknown_and_missing_keys():
    tag = Tag(CERT_ID, 1, genesis(CERT_ID), 100, 100, bytes(32)).signed(MAYA)
    data = tag.to_json()
    assert Tag.from_json(data) == tag
    with pytest.raises(EncodingError):
        Tag.from_json({**data, "extra": 1})
    with pytest.raises(EncodingError):
        Tag.from_json({k: v for k, v in data.items() if k != "cum"})


def test_constructor_rejects_unencodable_values():
    with pytest.raises(EncodingError):
        Tag(CERT_ID, -1, bytes(32), 100, 100, bytes(32))
    with pytest.raises(EncodingError):
        Tag(CERT_ID[:15], 1, bytes(32), 100, 100, bytes(32))
    with pytest.raises(EncodingError):
        Cert(CERT_ID, 1, crypto.public_key_bytes(MAYA), 2000, 0, 1, "bad|ref")


def test_dlog_body_must_match_kind():
    pub = crypto.public_key_bytes(SHOP)
    base = dict(device_pub=pub, seq=1, prev_hash=dlog_genesis(pub), ts=1)
    with pytest.raises(EncodingError):
        Dlog(**base, kind="REFUSE", tag_hash=bytes(32), cert_id=CERT_ID, check="C6", held_ids=())
    with pytest.raises(EncodingError):
        Dlog(**base, kind="REFUSE", tag_hash=bytes(32), cert_id=CERT_ID, check="C7")
    with pytest.raises(EncodingError):
        Dlog(**base, kind="CONTACT", contact_id=bytes(32), peer_pub=pub, sent_ids=[bytes(8)] * 201,
             recv_ids=(), sent_overflow=0, recv_overflow=0)
    entry = Dlog(**base, kind="ACCEPT", tag_hash=bytes(32), cert_id=CERT_ID, held_ids=[bytes(32)]).signed(SHOP)
    assert entry.held_ids == (bytes(32),)
    assert Dlog.from_json(entry.to_json()) == entry
    assert entry.verify_self()


def test_policy_merchant_limits():
    shop_id = b"\xab" * 16
    policy = Policy(1, 0, (), (f"{shop_id.hex()}:500",))
    assert policy.merchant_limit(shop_id) == 500
    assert policy.merchant_limit(b"\x02" * 16) is None
    for bad in ("nothex:500", f"{shop_id.hex()}:05", f"{shop_id.hex().upper()}:5"):
        with pytest.raises(EncodingError):
            Policy(1, 0, (), (bad,))
    with pytest.raises(EncodingError):
        Policy(1, 0, (), (f"{shop_id.hex()}:1", f"{shop_id.hex()}:2"))


def test_contact_id_is_symmetric_and_needs_two_devices():
    a, b = crypto.public_key_bytes(MAYA), crypto.public_key_bytes(SHOP)
    na, nb = b"\x0a" * 16, b"\x0b" * 16
    assert contact_id(a, na, b, nb) == contact_id(b, nb, a, na)
    assert contact_id(a, na, b, nb) != contact_id(a, nb, b, na)
    with pytest.raises(EncodingError):
        contact_id(a, na, a, nb)


def _payment(counter, prev, amount, cum, nonce=b"\x05" * 16):
    det = Det(crypto.public_key_bytes(SHOP), nonce, 100)
    return det, Tag(CERT_ID, counter, prev, amount, cum, det.digest()).signed(MAYA)


def test_item_round_trip_and_shared_ids():
    cert = Cert(CERT_ID, 1, crypto.public_key_bytes(MAYA), 2000, 0, 72 * 3600, "e").signed(SERVER)
    det, tag = _payment(1, genesis(CERT_ID), 500, 500)
    item = Item("PAY", Pay(cert, tag, det), (("a1b2c3d4", 100),))
    assert Item.from_json(item.to_json()) == item
    assert item.id == tag.tag_hash == Item("TAG", tag).id
    assert len(id8(item.id)) == 8
    assert item.priority == 3 and Item("TAG", tag).priority == 4


def test_merchant_knew_requires_paired_contact_even_if_merchant_logged_receipt():
    """Only M's own CONTACT names x; without the peer's matching entry R5 does not fire."""
    _, x = _payment(1, genesis(CERT_ID), 500, 500, nonce=b"\x01" * 16)
    _, z = _payment(1, genesis(CERT_ID), 700, 700, nonce=b"\x02" * 16)
    shop, peer = crypto.public_key_bytes(SHOP), crypto.public_key_bytes(SERVER)
    own = Dlog(shop, 1, dlog_genesis(shop), 10, "CONTACT", contact_id=bytes(32), peer_pub=peer,
               sent_ids=(), recv_ids=(id8(x.tag_hash),), sent_overflow=0, recv_overflow=0)
    assert rules.merchant_knew(z, merchant_pub=shop, t_accept=20, cert_tags=[x, z], logs=[own]) is None


def test_log_tamper_one_device_at_a_time():
    a, b = crypto.public_key_bytes(MAYA), crypto.public_key_bytes(SHOP)
    body = dict(kind="REFUSE", tag_hash=bytes(32), cert_id=CERT_ID, check="C1")
    with pytest.raises(ValueError):
        rules.log_tamper([Dlog(a, 1, dlog_genesis(a), 1, **body), Dlog(b, 1, dlog_genesis(b), 1, **body)])
    assert rules.log_tamper([]) is None


def test_over_cap_needs_caps():
    _, tag = _payment(1, genesis(CERT_ID), 500, 500)
    with pytest.raises(ValueError):
        rules.over_cap([tag], [])
    assert rules.over_cap([], [2000]) is False


def test_c6_ignores_stored_tags_of_other_certs():
    other = bytes(16)
    _, foreign = _payment(5, bytes(32), 100, 100)
    foreign = replace(foreign, cert_id=other).signed(MAYA)
    pub = crypto.public_key_bytes(MAYA)
    cert = Cert(CERT_ID, 1, pub, 2000, 0, 10_000, "e").signed(SERVER)
    req_nonce = b"\x05" * 16
    det, tag = _payment(1, genesis(CERT_ID), 500, 500, nonce=req_nonce)
    mcert = Mcert(b"\x09" * 16, 1, crypto.public_key_bytes(SHOP), "Shop", "r", 10_000).signed(SERVER)
    req = Req(mcert.merchant_id, 500, req_nonce, 200).signed(SHOP)
    result = rules.merchant_check(
        Pay(cert, tag, det), server_pub=crypto.public_key_bytes(SERVER), merchant=mcert, req=req,
        policy=None, stored_tags=[foreign], now=100,
    )
    assert result == rules.PASSED
