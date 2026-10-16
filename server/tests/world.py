"""The demo cast for server tests: Maya, the Pharmacy and the Gas Station,
registered through the API, plus a wallet that builds signed payments."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from stormcash.auth import sign_request
from stormcash.protocol import crypto
from stormcash.protocol.objects import Cert, Det, Dlog, Item, Mcert, Pay, Tag, b64u_encode, dlog_genesis, genesis

MAYA = crypto.private_key_from_scalar(0x111)
PHARMACY = crypto.private_key_from_scalar(0x222)
GAS = crypto.private_key_from_scalar(0x333)
CORNER = crypto.private_key_from_scalar(0x444)


def pub(key) -> bytes:
    return crypto.public_key_bytes(key)


def signed_post(client, path: str, payload: dict, key):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json", **sign_request(key, path, body)}
    return client.post(path, content=body, headers=headers)


@dataclass
class Wallet:
    cert_id: bytes
    counter: int = 0
    head: bytes = b""
    cum: int = 0
    history: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.head = genesis(self.cert_id)


class World:
    def __init__(self, client) -> None:
        self.client = client
        self.deps = client.app.state.deps
        out = self.post("/v1/residents/register",
                        {"display_name": "Maya", "holder_pub": b64u_encode(pub(MAYA)), "region_id": "asheville-downtown"},
                        MAYA)
        self.resident_id = out["resident_id"]
        self.cert = Cert.from_json(out["cert"])
        self.wallet = Wallet(self.cert.cert_id)
        self.mcerts: dict[str, Mcert] = {}
        self.keys = {"pharmacy": PHARMACY, "gas_station": GAS}
        for name, key, label in (("pharmacy", PHARMACY, "Pharmacy"), ("gas_station", GAS, "Gas Station")):
            out = self.post("/v1/merchants/register",
                            {"display_name": label, "merchant_pub": b64u_encode(pub(key)),
                             "region_id": "asheville-downtown"}, key)
            self.mcerts[name] = Mcert.from_json(out["mcert"])
        self.logs: dict[bytes, list[Dlog]] = {}
        self.nonces = 0

    def post(self, path: str, payload: dict, key) -> dict:
        resp = signed_post(self.client, path, payload, key)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def storm(self, cap: int = 5000) -> Cert:
        self.cert = Cert.from_json(self.post("/v1/storm-mode", {"cert_id": b64u_encode(self.cert.cert_id),
                                                                "cap_cents": cap}, MAYA)["cert"])
        return self.cert

    def pay(self, merchant: str, amount: int, *, cum: int | None = None, counter: int | None = None,
            prev: bytes | None = None, signer=MAYA, cert: Cert | None = None) -> Pay:
        """Build Maya's next payment (advancing the wallet unless overridden)."""
        w = self.wallet
        self.nonces += 1
        det = Det(self.mcerts[merchant].merchant_pub, self.nonces.to_bytes(16, "big"), int(time.time()))
        counter = w.counter + 1 if counter is None else counter
        prev = w.head if prev is None else prev
        cum = w.cum + amount if cum is None else cum
        tag = Tag(w.cert_id, counter, prev, amount, cum, det.digest()).signed(signer)
        w.history.append((w.counter, w.head, w.cum))
        w.counter, w.head, w.cum = counter, tag.tag_hash, cum
        return Pay(cert or self.cert, tag, det)

    def rollback(self, steps: int = 1) -> None:
        """Judge mode: restore the wallet to an earlier state."""
        for _ in range(steps):
            self.wallet.counter, self.wallet.head, self.wallet.cum = self.wallet.history.pop()

    def log(self, key, **entry) -> Dlog:
        """Append a signed DLOG entry to a device's chain."""
        device = pub(key)
        chain = self.logs.setdefault(device, [])
        prev = chain[-1].entry_hash if chain else dlog_genesis(device)
        e = Dlog(device_pub=device, seq=len(chain) + 1, prev_hash=prev, **entry).signed(key)
        chain.append(e)
        return e

    def sync(self, key, items: list, path=()) -> dict:
        payload = {"device_pub": b64u_encode(pub(key)),
                   "items": [it if isinstance(it, dict) else self.item(it, path).to_json() for it in items]}
        return self.post("/v1/sync", payload, key)

    @staticmethod
    def item(body, path=()) -> Item:
        kind = {"Pay": "PAY", "Tag": "TAG", "Dlog": "DLOG", "Renew": "RENEW", "Proof": "PROOF",
                "Policy": "POLICY", "Rcpt": "RCPT", "Cert": "CERT"}[type(body).__name__]
        return Item(kind, body, tuple(path))
