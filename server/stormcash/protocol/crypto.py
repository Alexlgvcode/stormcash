"""ECDSA P-256 over prehashed SHA-256 digests (spec §7.1).

- Signatures are raw 64 bytes r || s (big-endian, 32 bytes each).
- Signers always emit low-S. Verifiers accept low-S and high-S.
- Public keys are SEC1 compressed, 33 bytes.
- Signing is deterministic (RFC 6979) when the OpenSSL build supports it, so
  regenerating spec/vectors.json is reproducible.
"""

from __future__ import annotations

import secrets

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

CURVE = ec.SECP256R1()
# Order of the P-256 group.
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
HALF_N = N // 2

PUB_LEN = 33
SIG_LEN = 64
DIGEST_LEN = 32
ID_LEN = 16


class CryptoError(ValueError):
    pass


def _ecdsa(deterministic: bool) -> ec.ECDSA:
    prehashed = utils.Prehashed(hashes.SHA256())
    if deterministic:
        return ec.ECDSA(prehashed, deterministic_signing=True)
    return ec.ECDSA(prehashed)


def _deterministic_supported() -> bool:
    key = ec.derive_private_key(1, CURVE)
    try:
        key.sign(b"\x00" * DIGEST_LEN, _ecdsa(True))
    except (UnsupportedAlgorithm, TypeError):
        return False
    return True


DETERMINISTIC_SIGNING = _deterministic_supported()


# Keys ----------------------------------------------------------------------


def private_key_from_scalar(scalar: int | bytes) -> ec.EllipticCurvePrivateKey:
    if isinstance(scalar, bytes):
        scalar = int.from_bytes(scalar, "big")
    if not 0 < scalar < N:
        raise CryptoError("private scalar out of range")
    return ec.derive_private_key(scalar, CURVE)


def generate_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(CURVE)


def private_scalar(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_numbers().private_value.to_bytes(32, "big")


def public_key_bytes(
    key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey,
) -> bytes:
    """SEC1 compressed, 33 bytes."""
    if isinstance(key, ec.EllipticCurvePrivateKey):
        key = key.public_key()
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
    )


def load_public_key(pub: bytes) -> ec.EllipticCurvePublicKey:
    if not isinstance(pub, bytes) or len(pub) != PUB_LEN or pub[0] not in (2, 3):
        raise CryptoError("public key must be 33-byte SEC1 compressed")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pub)
    except ValueError as exc:
        raise CryptoError("public key is not a point on P-256") from exc


# Signature formats ----------------------------------------------------------


def raw_to_rs(sig: bytes) -> tuple[int, int]:
    if not isinstance(sig, bytes) or len(sig) != SIG_LEN:
        raise CryptoError("raw signature must be 64 bytes")
    return int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")


def rs_to_raw(r: int, s: int) -> bytes:
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def der_to_raw(der: bytes) -> bytes:
    """DER (as emitted by `cryptography` and the Secure Enclave) to raw r || s.

    Does not normalize S; call normalize_low_s for that.
    """
    try:
        r, s = utils.decode_dss_signature(der)
    except ValueError as exc:
        raise CryptoError("invalid DER signature") from exc
    if not (0 < r < N and 0 < s < N):
        raise CryptoError("signature scalar out of range")
    return rs_to_raw(r, s)


def raw_to_der(sig: bytes) -> bytes:
    r, s = raw_to_rs(sig)
    return utils.encode_dss_signature(r, s)


def is_low_s(sig: bytes) -> bool:
    _, s = raw_to_rs(sig)
    return s <= HALF_N


def normalize_low_s(sig: bytes) -> bytes:
    r, s = raw_to_rs(sig)
    return rs_to_raw(r, N - s) if s > HALF_N else sig


# Sign / verify --------------------------------------------------------------


def sign_digest_der(key: ec.EllipticCurvePrivateKey, digest: bytes) -> bytes:
    """Sign a 32-byte digest; returns DER exactly as `cryptography` emits it
    (S not normalized). Protocol code wants sign_digest instead."""
    if len(digest) != DIGEST_LEN:
        raise CryptoError("digest must be 32 bytes")
    return key.sign(digest, _ecdsa(DETERMINISTIC_SIGNING))


def sign_digest(key: ec.EllipticCurvePrivateKey, digest: bytes) -> bytes:
    """Sign a 32-byte digest; returns raw low-S r || s."""
    return normalize_low_s(der_to_raw(sign_digest_der(key, digest)))


def verify_digest(pub: bytes, digest: bytes, sig: bytes) -> bool:
    """True iff sig (raw r || s, low-S or high-S) is valid for digest under pub."""
    try:
        key = load_public_key(pub)
        r, s = raw_to_rs(sig)
    except CryptoError:
        return False
    if len(digest) != DIGEST_LEN or not (0 < r < N and 0 < s < N):
        return False
    try:
        key.verify(utils.encode_dss_signature(r, s), digest, _ecdsa(False))
    except InvalidSignature:
        return False
    return True


# Random ---------------------------------------------------------------------


def random_id() -> bytes:
    """16-byte id from the OS CSPRNG (cert_id, merchant_id)."""
    return secrets.token_bytes(ID_LEN)


def random_nonce() -> bytes:
    """16-byte nonce from the OS CSPRNG (REQ nonce, HELLO nonce)."""
    return secrets.token_bytes(ID_LEN)
