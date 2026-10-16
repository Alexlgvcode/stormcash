"""Protocol objects (spec §7.4, §9.2, §10.2) and their two codecs.

Each object lists its fields in canonical order (= spec table order). Two
JSON forms exist:

- transport JSON (`to_json` / `from_json`): short keys, bytes as base64url
  without padding (§7.3). This is the only place base64url is handled.
- vector form (`to_fields` / `from_fields`): long field names, bytes as
  lowercase hex, as used in spec/vectors.json (§20).

Signatures are over `digest()` = SHA-256 of `canonical()`; the signature
itself is never part of the canonical string.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from . import crypto, encoding
from .encoding import EncodingError

INT = "int"
BYTES = "bytes"
STRING = "string"
ENUM = "enum"
BYTES_LIST = "bytes_list"
STRING_LIST = "string_list"

DLOG_KINDS = ("ACCEPT", "REFUSE", "CONTACT")
CHECKS = ("C1", "C2", "C3", "C4", "C5", "C6")
PROOF_RULES = ("SAME_COUNTER", "BROKEN_LINK", "TOTAL_BACKWARDS")
CONTACT_IDS_CAP = 200
ID8_LEN = 8

ITEM_PRIORITY = {
    "PROOF": 1,
    "POLICY": 2,
    "RCPT": 2,
    "CERT": 2,
    "PAY": 3,
    "DLOG": 3,
    "RENEW": 3,
    "TAG": 4,
}

_MERCHANT_LIMIT_RE = re.compile(r"([0-9a-f]{32}):(0|[1-9][0-9]*)\Z")
_B64U_RE = re.compile(r"[A-Za-z0-9_-]*\Z")


# base64url ------------------------------------------------------------------


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    """Strict base64url without padding; rejects non-canonical encodings."""
    if not isinstance(text, str) or not _B64U_RE.match(text) or len(text) % 4 == 1:
        raise EncodingError(f"invalid base64url {text!r}")
    data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if b64u_encode(data) != text:
        raise EncodingError(f"non-canonical base64url {text!r}")
    return data


# Field specs ----------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    name: str
    key: str
    kind: str
    size: int | None = None
    allowed: tuple[str, ...] | None = None

    def render(self, value: Any) -> str:
        if self.kind == INT:
            return encoding.render_int(value)
        if self.kind == BYTES:
            return encoding.render_bytes(value, self.size)
        if self.kind == STRING:
            return encoding.render_string(value)
        if self.kind == ENUM:
            return encoding.render_enum(value, self.allowed)
        if self.kind == BYTES_LIST:
            return encoding.render_bytes_list(value, self.size)
        if self.kind == STRING_LIST:
            return encoding.render_string_list(value)
        raise AssertionError(self.kind)

    def _encode(self, value: Any, enc) -> Any:
        if self.kind == BYTES:
            return enc(value)
        if self.kind == BYTES_LIST:
            return [enc(v) for v in value]
        if self.kind == STRING_LIST:
            return list(value)
        return value

    def _decode(self, value: Any, dec) -> Any:
        if self.kind == BYTES:
            return dec(value)
        if self.kind == BYTES_LIST:
            if not isinstance(value, list):
                raise EncodingError(f"{self.name}: list expected")
            return tuple(dec(v) for v in value)
        if self.kind == STRING_LIST:
            if not isinstance(value, list):
                raise EncodingError(f"{self.name}: list expected")
            return tuple(value)
        return value

    def to_hex(self, value: Any) -> Any:
        return self._encode(value, bytes.hex)

    def from_hex(self, value: Any) -> Any:
        return self._decode(value, _hex_decode)

    def to_b64(self, value: Any) -> Any:
        return self._encode(value, b64u_encode)

    def from_b64(self, value: Any) -> Any:
        return self._decode(value, b64u_decode)


def _hex_decode(text: str) -> bytes:
    if not isinstance(text, str) or text != text.lower():
        raise EncodingError(f"lowercase hex expected, got {text!r}")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise EncodingError(f"invalid hex {text!r}") from exc


def _int(name: str, key: str) -> Field:
    return Field(name, key, INT)


def _bytes(name: str, key: str, size: int) -> Field:
    return Field(name, key, BYTES, size)


SIG = Field("sig", "sig", BYTES, crypto.SIG_LEN)


# Base class -----------------------------------------------------------------


class ProtocolObject:
    """A canonical object. Subclasses are frozen dataclasses."""

    TYPE: ClassVar[str]
    FIELDS: ClassVar[tuple[Field, ...]]
    SIGNED: ClassVar[bool] = True

    @classmethod
    def specs_for(cls, kind: str | None = None) -> tuple[Field, ...]:
        return cls.FIELDS

    def specs(self) -> tuple[Field, ...]:
        return self.FIELDS

    def __post_init__(self) -> None:
        for f in self.specs():
            if f.kind in (BYTES_LIST, STRING_LIST):
                value = getattr(self, f.name)
                if isinstance(value, list):
                    object.__setattr__(self, f.name, tuple(value))
        self.validate()

    def validate(self) -> None:
        self.canonical()
        sig = getattr(self, "sig", None)
        if sig is not None:
            SIG.render(sig)

    def canonical(self) -> str:
        return encoding.canonical(
            self.TYPE, [f.render(getattr(self, f.name)) for f in self.specs()]
        )

    def digest(self) -> bytes:
        return encoding.digest(self.canonical())

    # Signing

    def signed(self, key) -> ProtocolObject:
        return replace(self, sig=crypto.sign_digest(key, self.digest()))

    def verify(self, pub: bytes) -> bool:
        sig = getattr(self, "sig", None)
        if sig is None:
            return False
        return crypto.verify_digest(pub, self.digest(), sig)

    # Vector form (long names, hex)

    def to_fields(self) -> dict[str, Any]:
        return {f.name: f.to_hex(getattr(self, f.name)) for f in self.specs()}

    @classmethod
    def from_fields(cls, fields: dict[str, Any], sig: str | None = None):
        specs = cls.specs_for(fields.get("kind"))
        _check_keys(fields, {f.name for f in specs}, cls.TYPE)
        kwargs = {f.name: f.from_hex(fields[f.name]) for f in specs}
        if cls.SIGNED:
            kwargs["sig"] = None if sig is None else SIG.from_hex(sig)
        return cls(**kwargs)

    # Transport JSON (short keys, base64url)

    def to_json(self) -> dict[str, Any]:
        out = {f.key: f.to_b64(getattr(self, f.name)) for f in self.specs()}
        sig = getattr(self, "sig", None)
        if sig is not None:
            out[SIG.key] = SIG.to_b64(sig)
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]):
        if not isinstance(data, dict):
            raise EncodingError(f"{cls.TYPE}: object expected")
        specs = cls.specs_for(data.get("kd"))
        allowed = {f.key for f in specs} | ({SIG.key} if cls.SIGNED else set())
        _check_keys(data, allowed, cls.TYPE, required={f.key for f in specs})
        kwargs = {f.name: f.from_b64(data[f.key]) for f in specs}
        if cls.SIGNED:
            kwargs["sig"] = SIG.from_b64(data[SIG.key]) if SIG.key in data else None
        return cls(**kwargs)


def _check_keys(
    data: dict[str, Any], allowed: set[str], type_: str, required: set[str] | None = None
) -> None:
    required = allowed if required is None else required
    missing = required - data.keys()
    extra = data.keys() - allowed
    if missing or extra:
        raise EncodingError(
            f"{type_}: missing keys {sorted(missing)}, unknown keys {sorted(extra)}"
        )


# Objects (§7.4) ---------------------------------------------------------------


@dataclass(frozen=True)
class Cert(ProtocolObject):
    """Resident certificate, signed by the server."""

    TYPE: ClassVar[str] = "CERT"
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _bytes("cert_id", "ci", 16),
        _int("cert_ver", "cv"),
        _bytes("holder_pub", "hp", 33),
        _int("cap_cents", "cap"),
        _int("issued_at", "ia"),
        _int("expires_at", "ea"),
        Field("escrow_ref", "er", STRING),
    )

    cert_id: bytes
    cert_ver: int
    holder_pub: bytes
    cap_cents: int
    issued_at: int
    expires_at: int
    escrow_ref: str
    sig: bytes | None = None


@dataclass(frozen=True)
class Mcert(ProtocolObject):
    """Merchant certificate, signed by the server."""

    TYPE: ClassVar[str] = "MCERT"
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _bytes("merchant_id", "mi", 16),
        _int("merchant_ver", "mv"),
        _bytes("merchant_pub", "mp", 33),
        Field("display_name", "dn", STRING),
        Field("region_id", "rg", STRING),
        _int("expires_at", "ea"),
    )

    merchant_id: bytes
    merchant_ver: int
    merchant_pub: bytes
    display_name: str
    region_id: str
    expires_at: int
    sig: bytes | None = None


@dataclass(frozen=True)
class Req(ProtocolObject):
    """Payment request, signed by the merchant."""

    TYPE: ClassVar[str] = "REQ"
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _bytes("merchant_id", "mi", 16),
        _int("amount_cents", "amt"),
        _bytes("nonce", "n", 16),
        _int("req_expires_at", "rx"),
    )

    merchant_id: bytes
    amount_cents: int
    nonce: bytes
    req_expires_at: int
    sig: bytes | None = None


@dataclass(frozen=True)
class Det(ProtocolObject):
    """Payment details. Unsigned; its digest is the tag's details_hash."""

    TYPE: ClassVar[str] = "DET"
    SIGNED: ClassVar[bool] = False
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _bytes("merchant_pub", "mp", 33),
        _bytes("nonce", "n", 16),
        _int("ts", "ts"),
    )

    merchant_pub: bytes
    nonce: bytes
    ts: int


@dataclass(frozen=True)
class Tag(ProtocolObject):
    """Spend tag, signed by the holder. Its digest is the tag_hash."""

    TYPE: ClassVar[str] = "TAG"
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _bytes("cert_id", "ci", 16),
        _int("counter", "k"),
        _bytes("prev_hash", "ph", 32),
        _int("amount_cents", "amt"),
        _int("cum_cents", "cum"),
        _bytes("details_hash", "dh", 32),
    )

    cert_id: bytes
    counter: int
    prev_hash: bytes
    amount_cents: int
    cum_cents: int
    details_hash: bytes
    sig: bytes | None = None

    @property
    def tag_hash(self) -> bytes:
        return self.digest()


@dataclass(frozen=True)
class Policy(ProtocolObject):
    """Signed policy list: frozen certs and per-merchant payment limits."""

    TYPE: ClassVar[str] = "POLICY"
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _int("policy_ver", "pv"),
        _int("issued_at", "ia"),
        Field("frozen_certs", "fc", BYTES_LIST, 16),
        Field("merchant_limits", "ml", STRING_LIST),
    )

    policy_ver: int
    issued_at: int
    frozen_certs: tuple[bytes, ...]
    merchant_limits: tuple[str, ...]
    sig: bytes | None = None

    def validate(self) -> None:
        super().validate()
        seen = set()
        for entry in self.merchant_limits:
            m = _MERCHANT_LIMIT_RE.match(entry)
            if not m:
                raise EncodingError(f"invalid merchant limit {entry!r}")
            encoding.render_int(int(m.group(2)))
            if m.group(1) in seen:
                raise EncodingError(f"duplicate merchant limit for {m.group(1)}")
            seen.add(m.group(1))

    def merchant_limit(self, merchant_id: bytes) -> int | None:
        prefix = merchant_id.hex() + ":"
        for entry in self.merchant_limits:
            if entry.startswith(prefix):
                return int(entry[len(prefix) :])
        return None


@dataclass(frozen=True)
class Renew(ProtocolObject):
    """Renewal request, signed by the holder."""

    TYPE: ClassVar[str] = "RENEW"
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _bytes("cert_id", "ci", 16),
        _bytes("chain_head", "ch", 32),
        _int("counter", "k"),
        _int("ts", "ts"),
    )

    cert_id: bytes
    chain_head: bytes
    counter: int
    ts: int
    sig: bytes | None = None


@dataclass(frozen=True)
class Rcpt(ProtocolObject):
    """Server receipt for uploaded items."""

    TYPE: ClassVar[str] = "RCPT"
    FIELDS: ClassVar[tuple[Field, ...]] = (
        _int("ts", "ts"),
        Field("item_ids", "ids", BYTES_LIST, 32),
    )

    ts: int
    item_ids: tuple[bytes, ...]
    sig: bytes | None = None


# Device log (§9.2) -------------------------------------------------------------

DLOG_HEADER: tuple[Field, ...] = (
    _bytes("device_pub", "dp", 33),
    _int("seq", "q"),
    _bytes("prev_hash", "ph", 32),
    _int("ts", "ts"),
    Field("kind", "kd", ENUM, allowed=DLOG_KINDS),
)

DLOG_BODY: dict[str, tuple[Field, ...]] = {
    "ACCEPT": (
        _bytes("tag_hash", "th", 32),
        _bytes("cert_id", "ci", 16),
        Field("held_ids", "hi", BYTES_LIST, 32),
    ),
    "REFUSE": (
        _bytes("tag_hash", "th", 32),
        _bytes("cert_id", "ci", 16),
        Field("check", "ck", ENUM, allowed=CHECKS),
    ),
    "CONTACT": (
        _bytes("contact_id", "cid", 32),
        _bytes("peer_pub", "pp", 33),
        Field("sent_ids", "si", BYTES_LIST, ID8_LEN),
        Field("recv_ids", "ri", BYTES_LIST, ID8_LEN),
        _int("sent_overflow", "so"),
        _int("recv_overflow", "ro"),
    ),
}

_DLOG_BODY_NAMES = {f.name for body in DLOG_BODY.values() for f in body}


@dataclass(frozen=True)
class Dlog(ProtocolObject):
    """Device log entry, signed by device_pub. Its digest is the entry_hash.

    Body fields not used by `kind` must be None.
    """

    TYPE: ClassVar[str] = "DLOG"
    FIELDS: ClassVar[tuple[Field, ...]] = DLOG_HEADER

    device_pub: bytes
    seq: int
    prev_hash: bytes
    ts: int
    kind: str
    tag_hash: bytes | None = None
    cert_id: bytes | None = None
    held_ids: tuple[bytes, ...] | None = None
    check: str | None = None
    contact_id: bytes | None = None
    peer_pub: bytes | None = None
    sent_ids: tuple[bytes, ...] | None = None
    recv_ids: tuple[bytes, ...] | None = None
    sent_overflow: int | None = None
    recv_overflow: int | None = None
    sig: bytes | None = None

    @classmethod
    def specs_for(cls, kind: str | None = None) -> tuple[Field, ...]:
        if kind not in DLOG_BODY:
            raise EncodingError(f"unknown DLOG kind {kind!r}")
        return DLOG_HEADER + DLOG_BODY[kind]

    def specs(self) -> tuple[Field, ...]:
        return self.specs_for(self.kind)

    def validate(self) -> None:
        super().validate()
        used = {f.name for f in DLOG_BODY[self.kind]}
        for name in _DLOG_BODY_NAMES - used:
            if getattr(self, name) is not None:
                raise EncodingError(f"DLOG {self.kind} must not set {name}")
        if self.kind == "CONTACT":
            if len(self.sent_ids) > CONTACT_IDS_CAP or len(self.recv_ids) > CONTACT_IDS_CAP:
                raise EncodingError(f"CONTACT id lists are capped at {CONTACT_IDS_CAP}")
        if self.seq < 1:
            raise EncodingError("DLOG seq starts at 1")

    @property
    def entry_hash(self) -> bytes:
        return self.digest()

    def verify_self(self) -> bool:
        return self.verify(self.device_pub)


# Composites -------------------------------------------------------------------


@dataclass(frozen=True)
class Pay:
    """Payment: certificate + tag + details. JSON {c, t, d}."""

    cert: Cert
    tag: Tag
    det: Det

    def to_json(self) -> dict[str, Any]:
        return {"c": self.cert.to_json(), "t": self.tag.to_json(), "d": self.det.to_json()}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Pay:
        _check_keys(data, {"c", "t", "d"}, "PAY")
        return cls(Cert.from_json(data["c"]), Tag.from_json(data["t"]), Det.from_json(data["d"]))


@dataclass(frozen=True)
class Proof:
    """Equivocation proof: two tags and the rule they break. No signature."""

    a: Tag
    b: Tag
    rule: str

    def __post_init__(self) -> None:
        if self.rule not in PROOF_RULES:
            raise EncodingError(f"unknown proof rule {self.rule!r}")

    def to_json(self) -> dict[str, Any]:
        return {"a": self.a.to_json(), "b": self.b.to_json(), "rule": self.rule}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Proof:
        _check_keys(data, {"a", "b", "rule"}, "PROOF")
        return cls(Tag.from_json(data["a"]), Tag.from_json(data["b"]), data["rule"])


OBJECT_TYPES: dict[str, type[ProtocolObject]] = {
    cls.TYPE: cls for cls in (Cert, Mcert, Req, Det, Tag, Policy, Renew, Rcpt, Dlog)
}


def object_from_fields(type_: str, fields: dict[str, Any], sig: str | None = None):
    return OBJECT_TYPES[type_].from_fields(fields, sig)


# Derived hashes and ids --------------------------------------------------------


def genesis(cert_id: bytes) -> bytes:
    """GENESIS(cert_id): prev_hash of a tag with counter 1 (§7.4)."""
    return encoding.digest(gen_canonical(cert_id))


def gen_canonical(cert_id: bytes) -> str:
    return encoding.canonical("GEN", [encoding.render_bytes(cert_id, 16)])


def dlog_genesis(device_pub: bytes) -> bytes:
    """prev_hash of a device's DLOG entry with seq 1 (§9.2)."""
    return encoding.digest(dgen_canonical(device_pub))


def dgen_canonical(device_pub: bytes) -> str:
    return encoding.canonical("DGEN", [encoding.render_bytes(device_pub, 33)])


def contact_canonical(pub_a: bytes, nonce_a: bytes, pub_b: bytes, nonce_b: bytes) -> str:
    """canonical(CONTACT, pub_low, pub_high, nonce_low, nonce_high) (§9.2).

    Each side passes its own (pub, HELLO nonce) and the peer's, in any order.
    """
    if pub_a == pub_b:
        raise EncodingError("a contact needs two different devices")
    (pub_lo, nonce_lo), (pub_hi, nonce_hi) = sorted([(pub_a, nonce_a), (pub_b, nonce_b)])
    return encoding.canonical(
        "CONTACT",
        [
            encoding.render_bytes(pub_lo, 33),
            encoding.render_bytes(pub_hi, 33),
            encoding.render_bytes(nonce_lo, 16),
            encoding.render_bytes(nonce_hi, 16),
        ],
    )


def contact_id(pub_a: bytes, nonce_a: bytes, pub_b: bytes, nonce_b: bytes) -> bytes:
    return encoding.digest(contact_canonical(pub_a, nonce_a, pub_b, nonce_b))


def proof_canonical(hash_a: bytes, hash_b: bytes) -> str:
    """canonical(PRF, tag_hash, tag_hash) with the two hashes sorted (§10.2)."""
    lo, hi = sorted([hash_a, hash_b])
    return encoding.canonical(
        "PRF", [encoding.render_bytes(lo, 32), encoding.render_bytes(hi, 32)]
    )


def proof_id(proof: Proof) -> bytes:
    return encoding.digest(proof_canonical(proof.a.tag_hash, proof.b.tag_hash))


def item_id(kind: str, body: Any) -> bytes:
    """Item id (§10.2). PAY and TAG of one payment share the tag_hash."""
    if kind == "PROOF":
        return proof_id(body)
    if kind == "PAY":
        return body.tag.tag_hash
    expected = {"POLICY": Policy, "RCPT": Rcpt, "CERT": Cert, "RENEW": Renew, "DLOG": Dlog, "TAG": Tag}
    if kind not in expected or not isinstance(body, expected[kind]):
        raise EncodingError(f"invalid item kind {kind!r} for {type(body).__name__}")
    return body.digest()


def id8(full_id: bytes) -> bytes:
    """First 8 bytes of an item id; used in HELLO inventories and CONTACT entries."""
    return full_id[:ID8_LEN]


def device_short_id(device_pub: bytes) -> str:
    """First 4 bytes of a device pub as hex; only for `path` display (§10.2)."""
    return device_pub[:4].hex()


_ITEM_BODY_DECODERS = {
    "PROOF": Proof.from_json,
    "POLICY": Policy.from_json,
    "RCPT": Rcpt.from_json,
    "CERT": Cert.from_json,
    "PAY": Pay.from_json,
    "DLOG": Dlog.from_json,
    "RENEW": Renew.from_json,
    "TAG": Tag.from_json,
}


@dataclass(frozen=True)
class Item:
    """A syncable item {kind, body, path}. `path` is unsigned display metadata."""

    kind: str
    body: Any
    path: tuple[tuple[str, int], ...] = ()

    @property
    def id(self) -> bytes:
        return item_id(self.kind, self.body)

    @property
    def priority(self) -> int:
        return ITEM_PRIORITY[self.kind]

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "body": self.body.to_json(),
            "path": [[short, ts] for short, ts in self.path],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Item:
        _check_keys(data, {"kind", "body", "path"}, "item", required={"kind", "body"})
        kind = data["kind"]
        if kind not in _ITEM_BODY_DECODERS:
            raise EncodingError(f"unknown item kind {kind!r}")
        path = tuple((str(short), int(ts)) for short, ts in data.get("path", []))
        return cls(kind, _ITEM_BODY_DECODERS[kind](data["body"]), path)
