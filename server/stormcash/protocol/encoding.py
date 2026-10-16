"""Canonical encoding (spec §7.2): the exact string that gets hashed and signed.

canonical(TYPE, f1, ..., fn) = "SC1|" + TYPE + "|" + f1 + "|" + ... + "|" + fn
digest = SHA-256(UTF-8(canonical))

Every renderer raises EncodingError on a value the spec does not allow, so an
invalid field can never be signed or silently verified.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Sequence

PREFIX = "SC1"
MAX_STRING_CHARS = 48
# Largest integer JavaScript represents exactly (Number.MAX_SAFE_INTEGER).
MAX_INT = 2**53 - 1

_FORBIDDEN_CHARS = ("|", ",", "\n")
_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")


class EncodingError(ValueError):
    """A field value that has no canonical rendering."""


def render_int(value: int) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        raise EncodingError(f"integer expected, got {type(value).__name__}")
    if value < 0:
        raise EncodingError("negative integers are invalid")
    if value > MAX_INT:
        raise EncodingError("integer exceeds 2^53 - 1")
    return str(value)


def render_bytes(value: bytes, size: int | None = None) -> str:
    if not isinstance(value, bytes):
        raise EncodingError(f"bytes expected, got {type(value).__name__}")
    if size is not None and len(value) != size:
        raise EncodingError(f"expected {size} bytes, got {len(value)}")
    return value.hex()


def normalize_string(value: str) -> str:
    """NFC-normalize and validate a string field. Length counts code points."""
    if not isinstance(value, str):
        raise EncodingError(f"string expected, got {type(value).__name__}")
    value = unicodedata.normalize("NFC", value)
    for ch in _FORBIDDEN_CHARS:
        if ch in value:
            raise EncodingError(f"string contains forbidden character {ch!r}")
    if len(value) > MAX_STRING_CHARS:
        raise EncodingError(f"string longer than {MAX_STRING_CHARS} code points")
    return value


def render_string(value: str) -> str:
    return normalize_string(value)


def render_enum(value: str, allowed: Iterable[str] | None = None) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.match(value):
        raise EncodingError(f"invalid enum token {value!r}")
    if allowed is not None and value not in allowed:
        raise EncodingError(f"enum token {value!r} not allowed")
    return value


def render_bytes_list(values: Sequence[bytes], size: int | None = None) -> str:
    if not isinstance(values, (list, tuple)):
        raise EncodingError("list of bytes expected")
    # Lowercase hex sorts in the same order as the raw bytes.
    return ",".join(sorted(render_bytes(v, size) for v in values))


def render_string_list(values: Sequence[str]) -> str:
    if not isinstance(values, (list, tuple)):
        raise EncodingError("list of strings expected")
    rendered = [render_string(v) for v in values]
    # Sort by UTF-8 bytes (= code point order), not by UTF-16 code units.
    return ",".join(sorted(rendered, key=lambda s: s.encode("utf-8")))


def canonical(type_: str, fields: Sequence[str]) -> str:
    render_enum(type_)
    return "|".join([PREFIX, type_, *fields])


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def digest(canonical_string: str) -> bytes:
    return sha256(canonical_string.encode("utf-8"))
