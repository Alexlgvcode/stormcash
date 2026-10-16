"""Shared protocol vectors (spec §20).

Loads spec/vectors.json and checks that this library reproduces every
canonical string and digest byte for byte, verifies every valid signature,
rejects every invalid vector, and agrees on every rule outcome. The TypeScript
twin (mobile/src/protocol/__tests__/vectors.test.ts) runs the same file.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from stormcash.protocol import crypto, encoding, rules
from stormcash.protocol.objects import (
    OBJECT_TYPES,
    Pay,
    Proof,
    contact_canonical,
    contact_id,
    dgen_canonical,
    gen_canonical,
    id8,
    item_id,
    object_from_fields,
    proof_canonical,
    proof_id,
)

SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"
VECTORS_PATH = SPEC_DIR / "vectors.json"
VECTORS = json.loads(VECTORS_PATH.read_text())


def section(name: str):
    vectors = VECTORS[name]
    return pytest.mark.parametrize("v", vectors, ids=[v["name"] for v in vectors])


def h(text: str) -> bytes:
    return bytes.fromhex(text)


def obj(v: dict):
    return object_from_fields(v["type"], v["fields"], v["sig"])


def pay(v: dict) -> Pay:
    return Pay(obj(v["c"]), obj(v["t"]), obj(v["d"]))


def independent_verify(pub_hex: str, digest_hex: str, sig_hex: str) -> bool:
    """Verify with `cryptography` directly, bypassing stormcash.protocol.crypto."""
    sig = h(sig_hex)
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if not (0 < r < crypto.N and 0 < s < crypto.N):
        return False
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), h(pub_hex))
    try:
        key.verify(utils.encode_dss_signature(r, s), h(digest_hex), ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    except InvalidSignature:
        return False
    return True


# Encoding ---------------------------------------------------------------------


@section("encoding")
def test_encoding(v):
    value = v["value"]
    kind = v["kind"]
    if kind == "bytes":
        render = lambda: encoding.render_bytes(h(value), v["size"])
    elif kind == "bytes_list":
        render = lambda: encoding.render_bytes_list([h(x) for x in value], v["size"])
    elif kind == "int":
        render = lambda: encoding.render_int(value)
    elif kind == "string":
        render = lambda: encoding.render_string(value)
    elif kind == "enum":
        render = lambda: encoding.render_enum(value, v["allowed"])
    else:
        render = lambda: encoding.render_string_list(value)
    if v.get("error"):
        with pytest.raises(encoding.EncodingError):
            render()
    else:
        assert render() == v["rendered"]


# Objects ----------------------------------------------------------------------


@section("objects")
def test_object(v):
    # The digest is SHA-256 of the UTF-8 canonical string, computed independently.
    assert hashlib.sha256(v["canonical"].encode("utf-8")).hexdigest() == v["digest"]

    if v["type"] == "GEN":
        assert gen_canonical(h(v["fields"]["cert_id"])) == v["canonical"]
        return
    if v["type"] == "DGEN":
        assert dgen_canonical(h(v["fields"]["device_pub"])) == v["canonical"]
        return

    o = obj(v)
    assert o.canonical() == v["canonical"]
    assert o.digest().hex() == v["digest"]
    assert o.to_fields() == v["fields"]

    # Transport JSON: exact encoding and lossless round trip.
    assert o.to_json() == v["json"]
    assert OBJECT_TYPES[v["type"]].from_json(v["json"]) == o

    if o.SIGNED:
        assert o.verify(h(v["pub"])) is v["valid"]
        if v["sig"] is not None:
            assert independent_verify(v["pub"], v["digest"], v["sig"]) is v["valid"]
        if v["valid"]:
            assert crypto.is_low_s(o.sig)
    else:
        assert v["valid"] and v["sig"] is None

    if "item_kind" in v:
        full = item_id(v["item_kind"], o)
        assert full.hex() == v["item_id"]
        assert id8(full).hex() == v["id8"]


@section("pays")
def test_pay(v):
    p = pay(v)
    assert p.to_json() == v["json"]
    assert Pay.from_json(v["json"]) == p
    assert item_id("PAY", p).hex() == v["item_id"] == p.tag.tag_hash.hex()
    assert item_id("TAG", p.tag) == item_id("PAY", p)
    assert id8(item_id("PAY", p)).hex() == v["id8"]
    assert p.tag.details_hash == p.det.digest()


# Signatures ---------------------------------------------------------------------


@section("signatures")
def test_signature(v):
    assert crypto.verify_digest(h(v["pub"]), h(v["digest"]), h(v["sig"])) is v["valid"]
    assert independent_verify(v["pub"], v["digest"], v["sig"]) is v["valid"]
    if v["valid"]:
        assert crypto.is_low_s(h(v["sig"])) is v["low_s"]


def test_high_s_vector_present():
    assert any(v["valid"] and not v["low_s"] for v in VECTORS["signatures"])


@section("der")
def test_der(v):
    raw = crypto.der_to_raw(h(v["der"]))
    assert raw.hex() == v["raw"]
    assert crypto.normalize_low_s(raw).hex() == v["raw_low_s"]
    assert crypto.raw_to_der(raw).hex() == v["der"]
    assert crypto.verify_digest(h(v["pub"]), h(v["digest"]), raw)
    assert crypto.verify_digest(h(v["pub"]), h(v["digest"]), h(v["raw_low_s"]))


@section("contact_ids")
def test_contact_id(v):
    a, b = v["a"], v["b"]
    from_a = contact_id(h(a["pub"]), h(a["nonce"]), h(b["pub"]), h(b["nonce"]))
    from_b = contact_id(h(b["pub"]), h(b["nonce"]), h(a["pub"]), h(a["nonce"]))
    assert from_a.hex() == from_b.hex() == v["contact_id"]
    assert contact_canonical(h(a["pub"]), h(a["nonce"]), h(b["pub"]), h(b["nonce"])) == v["canonical"]


# Rules --------------------------------------------------------------------------


@section("single_tag")
def test_single_tag(v):
    assert rules.tag_valid(obj(v["tag"])) is v["valid"]


@section("equivocation")
def test_equivocation(v):
    a, b = obj(v["a"]), obj(v["b"])
    assert rules.rules_fired(a, b) == v["rules_fired"]
    assert rules.rules_fired(b, a) == v["rules_fired"]
    assert rules.equivocation(a, b) == v["rule"]
    proof = rules.make_proof(a, b)
    assert (proof.rule if proof else None) == v["rule"]


@section("proofs")
def test_proof(v):
    proof = Proof(obj(v["a"]), obj(v["b"]), v["rule"])
    assert proof.to_json() == v["json"]
    assert Proof.from_json(v["json"]) == proof
    assert rules.verify_proof(proof, h(v["holder_pub"])) is v["valid"]
    assert proof_canonical(proof.a.tag_hash, proof.b.tag_hash) == v["canonical"]
    assert proof_id(proof).hex() == v["item_id"] == item_id("PROOF", proof).hex()


@section("merchant_checks")
def test_merchant_check(v):
    result = rules.merchant_check(
        pay(v["pay"]),
        server_pub=h(v["server_pub"]),
        merchant=obj(v["merchant"]),
        req=obj(v["req"]),
        policy=None if v["policy"] is None else obj(v["policy"]),
        stored_tags=[obj(t) for t in v["stored_tags"]],
        now=v["now"],
    )
    expect = v["expect"]
    assert result.ok is expect["ok"]
    assert result.check == expect["check"]
    assert result.reason == expect["reason"]
    assert result.rule == expect["rule"]
    assert (None if result.conflict is None else result.conflict.tag_hash.hex()) == expect["conflict"]


@section("over_cap")
def test_over_cap(v):
    settled = []
    for step in v["steps"]:
        settled.append(obj(step["tag"]))
        assert rules.over_cap(settled, v["caps"]) is step["over_cap"]


@section("log_tamper")
def test_log_tamper(v):
    entries = [obj(e) for e in v["entries"]]
    assert all(e.verify_self() for e in entries)
    got = rules.log_tamper(entries)
    assert (None if got is None else {"kind": got.kind, "seq": got.seq}) == v["expect"]


@section("merchant_knew")
def test_merchant_knew(v):
    logs = [obj(e) for e in v["logs"]]
    assert all(e.verify_self() for e in logs)
    got = rules.merchant_knew(
        obj(v["z"]),
        merchant_pub=h(v["merchant_pub"]),
        t_accept=v["t_accept"],
        cert_tags=[obj(t) for t in v["cert_tags"]],
        logs=logs,
    )
    expect = v["expect"]
    assert (got is not None) is expect["fired"]
    if got is not None:
        assert got.clause == expect["clause"]
        assert got.conflict.hex() == expect["conflict"]
        assert (None if got.contact_id is None else got.contact_id.hex()) == expect["contact_id"]


# Coverage of §20 and freshness ----------------------------------------------------------


def names(section_name: str) -> set[str]:
    return {v["name"] for v in VECTORS[section_name]}


def test_required_vectors_present():
    """Every vector §20 lists exists."""
    # 1. GEN, CERT v1, CERT v2 (Storm Mode), MCERT, REQ, DET, TAG 1, TAG 2, PAY; 8. POLICY, RCPT, RENEW.
    assert {
        "gen_maya", "cert_v1", "cert_v2_storm_mode", "mcert_pharmacy", "req_pharmacy", "det_pharmacy",
        "tag_counter1", "tag_counter2", "policy", "rcpt", "renew",
    } <= names("objects")
    assert VECTORS["pays"]
    # 2. A negative vector per offline check C1-C6.
    failed = {v["expect"]["check"] for v in VECTORS["merchant_checks"] if not v["expect"]["ok"]}
    assert failed == {"C1", "C2", "C3", "C4", "C5", "C6"}
    # 3. A pair per R1-R3, plus a valid 3-tag chain.
    assert {v["rule"] for v in VECTORS["equivocation"]} >= {"SAME_COUNTER", "BROKEN_LINK", "TOTAL_BACKWARDS", None}
    assert {"chain_1_2", "chain_2_3", "chain_1_3"} <= names("equivocation")
    # 4. R4 over-cap scenario.
    assert any(step["over_cap"] for v in VECTORS["over_cap"] for step in v["steps"])
    # 5. DLOG chain ACCEPT, CONTACT, CONTACT, REFUSE + a fork + a broken link.
    chain = next(v for v in VECTORS["log_tamper"] if v["name"] == "chain_of_4")
    assert [e["fields"]["kind"] for e in chain["entries"]] == ["ACCEPT", "CONTACT", "CONTACT", "REFUSE"]
    assert {v["expect"]["kind"] for v in VECTORS["log_tamper"] if v["expect"]} == {"FORK", "BROKEN_LINK"}
    # 6. R5 via held_ids, via paired contact, and a one-sided contact that must not fire.
    knew = {v["name"]: v["expect"] for v in VECTORS["merchant_knew"]}
    assert knew["a_held_ids"]["clause"] == "HELD_IDS"
    assert knew["b_paired_contact"]["clause"] == "PAIRED_CONTACT"
    assert knew["c_one_sided_contact"]["fired"] is False
    # 7. CONTACT id computed by both sides.
    assert VECTORS["contact_ids"]
    # 9. A high-S signature that must verify (test_high_s_vector_present). 10. DER to raw.
    assert VECTORS["der"]


def test_vectors_file_is_current():
    """spec/vectors.json matches what spec/gen_vectors.py produces now."""
    if not crypto.DETERMINISTIC_SIGNING:
        pytest.skip("OpenSSL build lacks deterministic ECDSA")
    spec = importlib.util.spec_from_file_location("gen_vectors", SPEC_DIR / "gen_vectors.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.dump(gen.build()) == VECTORS_PATH.read_text(), (
        "spec/vectors.json is stale: run `python spec/gen_vectors.py` and commit the result"
    )
