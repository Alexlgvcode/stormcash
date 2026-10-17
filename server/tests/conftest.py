"""Shared fixtures: a throwaway Postgres database with schema.sql applied, an
in-memory fake Nessie, and an app wired to both.

The database comes from TEST_DATABASE_URL (default: the CI service at
localhost:5432). Tests create and use a separate `stormcash_test` database there
and never read DATABASE_URL, so they can't touch the hosted demo database.
DB tests are skipped when no Postgres is reachable, except in CI where that fails.
"""

from __future__ import annotations

import itertools
import os
import re
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from stormcash.app import create_app
from stormcash.config import Settings
from stormcash.photon.config import PhotonSettings
from stormcash.protocol import crypto

SERVER_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
TEST_DB = "stormcash_test"


def _with_dbname(url: str, dbname: str) -> str:
    return psycopg.conninfo.make_conninfo(url, dbname=dbname)


@pytest.fixture(scope="session")
def database_url() -> str:
    admin_url = os.environ.get("TEST_DATABASE_URL", DEFAULT_ADMIN_URL)
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"no test Postgres at TEST_DATABASE_URL ({exc.__class__.__name__})")
    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    url = _with_dbname(admin_url, TEST_DB)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute((SERVER_DIR / "schema.sql").read_text())
    return url


@pytest.fixture
def clean_db(database_url: str) -> str:
    with psycopg.connect(database_url, autocommit=True) as conn:
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
        conn.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(sql.SQL(", ").join(map(sql.Identifier, tables)))
        )
    return database_url


class FakeNessie:
    """Just enough of the Nessie API (§11.4) to test against, in memory."""

    def __init__(self) -> None:
        self.ids = (f"{n:024x}" for n in itertools.count(0xA000))
        self.customers: dict[str, dict] = {}
        self.accounts: dict[str, dict] = {}
        self.records: dict[str, list[dict]] = {}  # account_id -> deposits and withdrawals
        self.calls: list[tuple[str, str]] = []
        self.fail: set[str] = set()  # e.g. {"deposits"} makes deposits answer 500
        self.down = False
        # The guarantee pool exists before the server starts (stormcash.nessie_setup).
        self.pool_id = next(self.ids)
        self.accounts[self.pool_id] = {"_id": self.pool_id, "type": "Checking", "nickname": "Guarantee Pool",
                                       "rewards": 0, "balance": 1000}
        self.records[self.pool_id] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        import json

        path, method = request.url.path, request.method
        self.calls.append((method, path))
        assert request.url.params.get("key") == "test-key"
        if self.down:
            raise httpx.ConnectTimeout("down", request=request)
        body = json.loads(request.content) if request.content else None

        if method == "POST" and path == "/customers":
            cid = next(self.ids)
            self.customers[cid] = body
            return self._created(cid)
        if m := re.fullmatch(r"/customers/(\w+)/accounts", path):
            assert method == "POST" and m.group(1) in self.customers
            assert isinstance(body["balance"], int)
            aid = next(self.ids)
            self.accounts[aid] = {"_id": aid, "customer_id": m.group(1), **body}
            self.records[aid] = []
            return self._created(aid)
        if m := re.fullmatch(r"/accounts/(\w+)", path):
            return httpx.Response(200, json=self.accounts[m.group(1)])
        if m := re.fullmatch(r"/accounts/(\w+)/(withdrawals|deposits)", path):
            aid, kind = m.groups()
            if kind in self.fail:
                return httpx.Response(500, json={"message": "boom"})
            if method == "GET":
                return httpx.Response(200, json=[r for r in self.records[aid] if r["type"] == kind])
            assert isinstance(body["amount"], int) and body["status"] == "completed"
            rid = next(self.ids)
            self.records[aid].append({"_id": rid, "type": kind, **body})
            return self._created(rid)
        return httpx.Response(404, json={"message": "not found"})

    @staticmethod
    def _created(new_id: str) -> httpx.Response:
        return httpx.Response(201, json={"code": 201, "message": "Created", "objectCreated": {"_id": new_id}})

    def balance_dollars(self, account_id: str) -> int:
        recs = self.records[account_id]
        return (
            self.accounts[account_id]["balance"]
            + sum(r["amount"] for r in recs if r["type"] == "deposits")
            - sum(r["amount"] for r in recs if r["type"] == "withdrawals")
        )


SERVER_KEY = crypto.private_key_from_scalar(0x5EED)


def make_settings(database_url: str, **overrides) -> Settings:
    values = dict(
        database_url=database_url,
        server_key=SERVER_KEY,
        nessie_api_key="test-key",
        nessie_base_url="https://nessie.test",
        background_tasks=False,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def fake_nessie() -> FakeNessie:
    return FakeNessie()


@pytest.fixture
def app_client(clean_db: str, fake_nessie: FakeNessie):
    settings = make_settings(clean_db, nessie_pool_account_id=fake_nessie.pool_id)
    app = create_app(settings, nessie_transport=fake_nessie.transport(), photon=PhotonSettings(disabled=True))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def deps(app_client):
    return app_client.app.state.deps
