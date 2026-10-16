"""POST /v1/sync: upload carried items, get back RCPT, POLICY and renewed CERTs (§10.5, §12.2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import signer_pub
from ..jsonutil import b64_field
from ..protocol.crypto import PUB_LEN
from ..protocol.encoding import EncodingError
from ..protocol.objects import Item
from ..settlement import ingest_items

router = APIRouter()


class SyncIn(BaseModel):
    device_pub: str
    items: list[Any]


@router.post("/v1/sync")
def sync(body: SyncIn, request: Request, signer: bytes | None = Depends(signer_pub)) -> dict:
    device_pub = b64_field(body.device_pub, "device_pub", PUB_LEN)
    if signer is not None and signer != device_pub:
        raise HTTPException(403, "request must be signed by device_pub")
    items, dropped = [], 0
    for raw in body.items:
        try:
            items.append(Item.from_json(raw))
        except (EncodingError, KeyError, TypeError, ValueError):
            dropped += 1
    result = ingest_items(request.app.state.deps, device_pub, items, dropped=dropped)
    return result.to_json()
