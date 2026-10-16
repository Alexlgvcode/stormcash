"""WS4 #21: the town runs through the real protocol and settlement code."""

from __future__ import annotations

import pytest

from stormcash import ledger
from stormcash.db import all_rows, scalar
from stormcash_sim.engine import Params, Sim

import psycopg
from psycopg import sql

from .conftest import ADMIN_URL, SCHEMA, make_deps

START = 1792238400  # fixed T0 (08:00 in Asheville) so runs are comparable


def db_facts(deps) -> dict:
    with deps.pool.connection() as conn:
        return {
            "tags": sorted(bytes(r["tag_hash"]).hex() for r in all_rows(conn, "SELECT tag_hash FROM tags")),
            "payments": scalar(conn, "SELECT count(*) FROM payments"),
            "statuses": sorted({r["status"] for r in all_rows(conn, "SELECT status FROM payments")}),
            "contacts": scalar(conn, "SELECT count(*) FROM contacts"),
            "nessie_calls": scalar(conn, "SELECT count(*) FROM nessie_calls"),
            "nessie_moves": scalar(conn, "SELECT count(*) FROM nessie_moves"),
            "payout_statuses": sorted({r["status"] for r in all_rows(conn, "SELECT status FROM payouts")}),
            "all_simulated": scalar(conn, "SELECT bool_and(simulated) FROM residents")
            and scalar(conn, "SELECT bool_and(simulated) FROM merchants")
            and scalar(conn, "SELECT bool_and(simulated) FROM uploads"),
            "unbalanced": len(ledger.unbalanced_txns(conn)),
        }


def test_short_town_writes_ledger_only_data(sim_deps):
    summary = Sim(sim_deps, Params(seed=7, hours=8, residents=120, start=START)).run()
    facts = db_facts(sim_deps)
    assert summary["accepted"] > 50 and summary["contacts"] > 50 and summary["uploads"] > 0
    assert 0 < facts["payments"] <= summary["accepted"]
    assert facts["statuses"] == ["settled"]
    assert facts["payout_statuses"] == ["ledger_only"]
    assert facts["nessie_calls"] == facts["nessie_moves"] == 0
    assert facts["all_simulated"] is True
    assert facts["unbalanced"] == 0
    assert summary["refused"] == {}  # an honest town refuses nothing


def test_same_seed_same_town(fresh_db):
    runs = []
    for i in range(2):
        name = f"{psycopg.conninfo.conninfo_to_dict(fresh_db)['dbname']}_r{i}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA.read_text())
        deps = make_deps(url)
        try:
            summary = Sim(deps, Params(seed=11, hours=6, residents=80, start=START)).run()
            summary.pop("wall_seconds")
            runs.append((summary, db_facts(deps)))
        finally:
            deps.pool.close()
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    assert runs[0] == runs[1]


def test_a_seed_cannot_run_twice_into_one_database(sim_deps):
    Sim(sim_deps, Params(seed=3, hours=1, residents=20, start=START)).run()
    with pytest.raises(RuntimeError, match="already ran"):
        Sim(sim_deps, Params(seed=3, hours=1, residents=20, start=START)).run()


def test_refuses_to_run_with_nessie(fresh_db):
    deps = make_deps(fresh_db, nessie_enabled=True, nessie_api_key="x")
    try:
        with pytest.raises(ValueError, match="Nessie"):
            Sim(deps, Params(hours=1))
    finally:
        deps.pool.close()


def test_72h_storm_in_under_60_seconds(sim_deps):
    """Done-when for #21 (spec §16.2)."""
    summary = Sim(sim_deps, Params(seed=42, hours=72, start=START)).run()
    assert summary["wall_seconds"] < 60
    assert summary["accepted"] > 500
    assert summary["settled"] >= 0.95 * summary["accepted"]  # the last few may still be in transit
    assert db_facts(sim_deps)["unbalanced"] == 0
