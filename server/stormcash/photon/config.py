"""Photon settings, read like stormcash.config: server/.env, then real environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

SERVER_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PhotonSettings:
    disabled: bool = False  # fallback (§22.4): store messages, send nothing
    bridge_url: str = "http://127.0.0.1:8787"  # the Node sender in photon/bridge
    bridge_token: str = ""
    webhook_secret: str = ""  # Spectrum webhook signing secret (X-Spectrum-Signature)
    allow_unsigned: bool = False  # local testing only: accept inbound without a signature
    transport: object | None = field(default=None, compare=False, repr=False)  # tests: httpx.MockTransport

    @property
    def can_send(self) -> bool:
        return not self.disabled and bool(self.bridge_token)


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load(env_file: Path | None = SERVER_DIR / ".env") -> PhotonSettings:
    env: dict[str, str] = {}
    if env_file is not None and env_file.exists():
        env.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    env.update(os.environ)
    return PhotonSettings(
        disabled=_flag(env.get("PHOTON_DISABLED"), False),
        bridge_url=(env.get("PHOTON_BRIDGE_URL") or "http://127.0.0.1:8787").rstrip("/"),
        bridge_token=env.get("PHOTON_BRIDGE_TOKEN", ""),
        webhook_secret=env.get("SPECTRUM_WEBHOOK_SECRET", ""),
        allow_unsigned=_flag(env.get("PHOTON_ALLOW_UNSIGNED"), False),
    )
