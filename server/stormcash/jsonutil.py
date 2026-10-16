"""JSON for the API and SSE: bytes become base64url without padding (§12)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from .protocol.encoding import EncodingError
from .protocol.objects import b64u_decode, b64u_encode


def jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return b64u_encode(bytes(value))
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime):
        return int(value.timestamp())
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def b64_field(value: str, name: str, size: int | None = None) -> bytes:
    """Decode a base64url request field or answer 400."""
    try:
        data = b64u_decode(value)
    except EncodingError as exc:
        raise HTTPException(400, f"{name}: invalid base64url") from exc
    if size is not None and len(data) != size:
        raise HTTPException(400, f"{name}: expected {size} bytes")
    return data
