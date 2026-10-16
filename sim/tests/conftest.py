"""A throwaway Postgres database per test for the simulator (same rules as
server/tests: TEST_DATABASE_URL, never DATABASE_URL; skipped locally without
Postgres, required in CI)."""

from __future__ import annotations

import dataclasses
import itertools
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from stormcash.app import build_deps
from stormcash.config import Settings
from stormcash.protocol import crypto

SCHEMA = Path(__file__).resolve().parents[2] / "server" / "schema.sql"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
_counter = itertools.count()


@pytest.fixture
def fresh_db():
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"no test Postgres at TEST_DATABASE_URL ({exc.__class__.__name__})")
    name = f"stormcash_sim_test_{os.getpid()}_{next(_counter)}"
    with admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(SCHEMA.read_text())
    yield url
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def make_deps(url: str, **overrides):
    settings = Settings(database_url=url, server_key=crypto.private_key_from_scalar(0x5EED),
                        nessie_enabled=False, background_tasks=False)
    return build_deps(dataclasses.replace(settings, **overrides))


@pytest.fixture
def sim_deps(fresh_db):
    deps = make_deps(fresh_db)
    yield deps
    deps.pool.close()
