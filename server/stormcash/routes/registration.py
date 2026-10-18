"""POST /v1/residents/register, /v1/merchants/register, /v1/storm-mode, /v1/storm-mode/close."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import registry
from ..auth import signer_pub
from ..jsonutil import b64_field
from ..protocol.crypto import ID_LEN, PUB_LEN

router = APIRouter()


class ResidentIn(BaseModel):
    display_name: str
    holder_pub: str
    region_id: str | None = None


class MerchantIn(BaseModel):
    display_name: str
    merchant_pub: str
    region_id: str | None = None
    x: int | None = None
    y: int | None = None


class StormModeIn(BaseModel):
    cert_id: str
    cap_cents: int = registry.MAX_CAP_CENTS


class CloseIn(BaseModel):
    cert_id: str


def _same_key(signer: bytes | None, key: bytes) -> None:
    if signer is not None and signer != key:
        raise HTTPException(403, "request must be signed by the key being registered")


@router.post("/v1/residents/register")
def register_resident(body: ResidentIn, request: Request, signer: bytes | None = Depends(signer_pub)) -> dict:
    holder_pub = b64_field(body.holder_pub, "holder_pub", PUB_LEN)
    _same_key(signer, holder_pub)
    resident_id, cert, _ = registry.register_resident(
        request.app.state.deps, body.display_name, holder_pub, body.region_id,
    )
    return {"resident_id": str(resident_id), "cert": cert.to_json()}


@router.post("/v1/merchants/register")
def register_merchant(body: MerchantIn, request: Request, signer: bytes | None = Depends(signer_pub)) -> dict:
    merchant_pub = b64_field(body.merchant_pub, "merchant_pub", PUB_LEN)
    _same_key(signer, merchant_pub)
    merchant_id, mcert, _ = registry.register_merchant(
        request.app.state.deps, body.display_name, merchant_pub, body.region_id, body.x, body.y,
    )
    return {"merchant_id": mcert.to_json()["mi"], "mcert": mcert.to_json()}


@router.post("/v1/storm-mode")
def storm_mode(body: StormModeIn, request: Request, signer: bytes | None = Depends(signer_pub)) -> dict:
    cert = registry.raise_storm_mode(
        request.app.state.deps, b64_field(body.cert_id, "cert_id", ID_LEN), body.cap_cents, caller_pub=signer
    )
    return {"cert": cert.to_json()}


@router.post("/v1/storm-mode/close")
def storm_mode_close(body: CloseIn, request: Request, signer: bytes | None = Depends(signer_pub)) -> dict:
    cert = registry.close_storm_mode(
        request.app.state.deps, b64_field(body.cert_id, "cert_id", ID_LEN), caller_pub=signer
    )
    return {"cert": cert.to_json()}
