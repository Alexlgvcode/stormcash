"""Run the Python town simulator (sim/) on several seeds, for the Scale Lab validation.

This is the real engine, unmodified: real P-256 keys and signatures, the real
C1-C6 merchant checks (rules.merchant_check) and the real server ingest
(settlement.ingest_items) into Postgres. The town runs at its defaults (§16.3:
38 simulated shops, 400 residents, 60% adoption, p_link 0.6, p_uplink 0.03/h,
shelter 0.5/h, 72 h) with the §16.4 *organic* double spenders only, planted
exactly as sim/stormcash_sim/scenarios.py plants them. The scripted scenarios
(colluders, stolen phones, the dark region, traps) are left out: they are
hand-placed events for the evals, not town dynamics, and Swannanoa's 60-hour
blackout alone would move every settlement number.

Each seed gets a fresh database. The output has one stats.json-shaped entry
per seed (sim/stormcash_sim/outputs.py: stats), plus the wall time.

    python cpp/scale/validation/run_python_engine.py --seeds 1-30 \\
        --admin-url postgresql://postgres:postgres@localhost:5432/postgres \\
        --out cpp/scale/results/validation/python_engine.json

Needs `pip install -e "./server[dev]" -e ./sim`. Everything it reports is simulated.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import platform
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql

from stormcash.app import build_deps
from stormcash.config import Settings
from stormcash.protocol import crypto
from stormcash_sim import outputs
from stormcash_sim.engine import Params, Sim
from stormcash_sim.scenarios import Plan

REPO = Path(__file__).resolve().parents[3]
SCHEMA = REPO / "server" / "schema.sql"
# T0 at local midnight (EDT), so the run's time of day is fixed rather than
# taken from the wall clock (engine.py defaults to "72 h ending now").
START = int(datetime(2026, 10, 15, 4, 0, tzinfo=timezone.utc).timestamp())
SERVER_KEY = crypto.private_key_from_scalar(0x5CA1E)  # a test key for these throwaway databases


class OrganicCheatersSim(Sim):
    """The engine with only the organic double spenders planted.

    The four lines in plant_organic() are scenarios.plant()'s double_spender
    block, with the same seeded stream and the same count, so these cheaters
    are the ones a default run would pick.
    """

    cheaters = 6

    def setup(self) -> None:
        super().setup()  # scenarios=False: the honest town, its storm event and trips
        self.plan = Plan()
        self.plant_organic()

    def plant_organic(self) -> None:
        rng = random.Random(self.p.seed * 7919 + 1)  # scenarios.plant's stream
        end = self.p.hours * 60
        pool = list(self.residents)
        rng.shuffle(pool)
        for r in pool[: self.cheaters]:
            r.storm, r.role, r.gossips_own_tags, r.cheats_left = True, "double_spender", False, 2
            r.gossip_off.append((0, end))  # a cheating phone doesn't relay anything
            self.plan.cheaters.append(r.idx)


def fresh_database(admin_url: str, name: str) -> str:
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(admin_url, dbname=name)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(SCHEMA.read_text())
    return url


def drop_database(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def run_seed(admin_url: str, seed: int, cheaters: int) -> dict:
    name = f"scale_validation_{seed}"
    url = fresh_database(admin_url, name)
    settings = Settings(database_url=url, server_key=SERVER_KEY, nessie_enabled=False, background_tasks=False)
    deps = build_deps(settings)
    try:
        params = Params(seed=seed, hours=72, start=START, scenarios=False)
        sim = OrganicCheatersSim(deps, params)
        sim.cheaters = cheaters
        started = time.monotonic()
        summary = sim.run()
        stats = outputs.stats(sim, summary)  # the same function that writes sim/out/<seed>/stats.json
        stats["wall_seconds"] = round(time.monotonic() - started, 2)
        stats["attempt_detail"] = [
            {"mode": a.mode, "refused": a.refused} for a in sim.stats.attempts
        ]
        return stats
    finally:
        deps.pool.close()
        drop_database(admin_url, name)


def seed_list(text: str) -> list[int]:
    if "-" in text:
        lo, hi = text.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in text.split(",")]


def cpu() -> str:
    try:
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return platform.processor() or "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", default="1-30")
    ap.add_argument("--cheaters", type=int, default=6)
    ap.add_argument("--admin-url", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    runs = []
    started = time.monotonic()
    for seed in seed_list(args.seeds):
        stats = run_seed(args.admin_url, seed, args.cheaters)
        ds = stats["double_spends"]
        print(f"seed {seed}: {stats['summary']['payments']} payments, {ds['attempts']} double spends, "
              f"{ds['refused_offline']} refused, {ds['caught_at_settlement']} caught, "
              f"median {stats['median_hours_to_settlement']} h, {stats['wall_seconds']} s", flush=True)
        runs.append(stats)
    out = {
        "simulated": True,
        "source": "sim/ (Python engine): real P-256 signatures, rules.merchant_check, settlement.ingest_items on "
                  "Postgres; organic double spenders only (scenarios.plant's double_spender block), no scripted "
                  "scenarios",
        # Shared by every run; each run's own seed is in its record.
        "params": {k: v for k, v in dataclasses.asdict(Params(hours=72, start=START, scenarios=False)).items()
                   if k != "seed"} | {"organic_cheaters": args.cheaters},
        "seeds": [r["seed"] for r in runs],
        "machine": {"cpu": cpu(), "os": f"{platform.system()} {platform.release()} {platform.machine()}",
                    "python": platform.python_version()},
        "wall_seconds": round(time.monotonic() - started, 1),
        "runs": runs,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
