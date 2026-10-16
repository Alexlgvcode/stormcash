"""Server settings from environment variables and server/.env (spec §6.3)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from dotenv import dotenv_values

from .protocol import crypto

SERVER_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    server_key: ec.EllipticCurvePrivateKey
    nessie_api_key: str = ""
    nessie_base_url: str = "https://api.nessieisreal.com"
    # The guarantee pool's Nessie account (python -m stormcash.nessie_setup creates it).
    nessie_pool_account_id: str = ""
    # Fallback switch (§22.4): NESSIE_DISABLED=1 keeps everything ledger-only.
    nessie_enabled: bool = True
    # Fallback switch: API_SIG_REQUIRED=0 accepts unsigned writes (§12).
    api_sig_required: bool = True
    demo_mode: bool = True
    public_base_url: str = ""
    nws_user_agent: str = "StormCash HackHarvard demo"
    factory_api_key: str = ""
    chalk_client_id: str = ""
    chalk_client_secret: str = ""
    chalk_environment: str = ""
    photon_api_key: str = ""
    # Background loops (Nessie replay, escrow release). Off in tests.
    background_tasks: bool = True

    @property
    def server_pub(self) -> bytes:
        return crypto.public_key_bytes(self.server_key)


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_server_key(pem: str) -> ec.EllipticCurvePrivateKey:
    key = load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        raise ValueError("SERVER_SIGNING_KEY_PEM must be a P-256 private key")
    return key


def load_settings(env_file: Path | None = SERVER_DIR / ".env") -> Settings:
    """Read server/.env, then let real environment variables override it."""
    env = {}
    if env_file is not None and env_file.exists():
        env.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    env.update(os.environ)

    missing = [k for k in ("DATABASE_URL", "SERVER_SIGNING_KEY_PEM") if not env.get(k)]
    if missing:
        raise RuntimeError(f"missing settings: {', '.join(missing)} (see server/.env.example)")
    return Settings(
        database_url=env["DATABASE_URL"],
        server_key=load_server_key(env["SERVER_SIGNING_KEY_PEM"]),
        nessie_api_key=env.get("NESSIE_API_KEY", ""),
        nessie_base_url=env.get("NESSIE_BASE_URL") or "https://api.nessieisreal.com",
        nessie_pool_account_id=env.get("NESSIE_POOL_ACCOUNT_ID", ""),
        nessie_enabled=not _flag(env.get("NESSIE_DISABLED"), False) and bool(env.get("NESSIE_API_KEY")),
        api_sig_required=_flag(env.get("API_SIG_REQUIRED"), True),
        demo_mode=_flag(env.get("DEMO_MODE"), True),
        public_base_url=env.get("PUBLIC_BASE_URL", ""),
        nws_user_agent=env.get("NWS_USER_AGENT") or "StormCash HackHarvard demo",
        factory_api_key=env.get("FACTORY_API_KEY", ""),
        chalk_client_id=env.get("CHALK_CLIENT_ID", ""),
        chalk_client_secret=env.get("CHALK_CLIENT_SECRET", ""),
        chalk_environment=env.get("CHALK_ENVIRONMENT", ""),
        photon_api_key=env.get("PHOTON_API_KEY", ""),
        background_tasks=_flag(env.get("BACKGROUND_TASKS"), True),
    )
