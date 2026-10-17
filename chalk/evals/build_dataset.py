"""Build the StormDesk eval dataset (spec §15.3): one row per detector candidate.

    server/.venv/bin/python chalk/evals/build_dataset.py            # reuse eval DBs that are already seeded
    server/.venv/bin/python chalk/evals/build_dataset.py --rebuild  # drop and re-seed them

Each seed runs the town simulator (§16) into its own database on a LOCAL
Postgres (default: the Docker container from chalk/evals/README.md), never the
hosted demo database: one town per database, because the detectors compare a
shop with its neighbours and towns from two seeds would overlap. The labels
come from the simulator's ground truth (labels.json, §16.4a), matched to each
candidate by subject.

Writes chalk/evals/dataset/stormdesk_triage.jsonl (the rows) and meta.json
(seeds, counts, and the labelled subjects the detectors never raised, which no
runner can see). Run it with the server's Python: it imports the server and the
simulator.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from psycopg import sql
from psycopg.rows import dict_row

EVALS = Path(__file__).resolve().parent
REPO = EVALS.parents[1]
STATE = EVALS / ".state"
DATASET = EVALS / "dataset"
KEY_FILE = STATE / "server_key.pem"

SEEDS = (42, 7, 13, 99, 2026)
START = 1791936000  # T0 for every seed (2026-10-14 00:00 UTC): fixed, so the dataset is reproducible
HOURS = 72
ADMIN_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
DB_PREFIX = "stormcash_eval_"
SOFT_KINDS = ("merchant_silence", "cap_drain", "region_dark")
COLUMNS = ("row_id", "seed", "candidate_id", "kind", "subject_id", "subject_name", "window_start", "window_end",
           "features", "label_kind", "label_action", "label_scenario", "label_note", "honest_subject")


def db_url(admin_url: str, seed: int) -> str:
    return psycopg.conninfo.make_conninfo(admin_url, dbname=f"{DB_PREFIX}{seed}")


def check_local(admin_url: str) -> None:
    """The eval towns go to a local Postgres only: never the hosted demo database."""
    host = psycopg.conninfo.conninfo_to_dict(admin_url).get("host", "localhost")
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit(f"refusing to seed eval towns on {host}: use a local Postgres (see chalk/evals/README.md)")


def server_key_pem() -> str:
    """A throwaway P-256 key for the eval towns (the demo server's key is never needed)."""
    if not KEY_FILE.exists():
        STATE.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        KEY_FILE.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        KEY_FILE.chmod(0o600)
    return KEY_FILE.read_text()


def create_db(admin_url: str, seed: int, rebuild: bool) -> bool:
    """Create the seed's database with schema.sql and the migrations. False if it is already seeded."""
    name = f"{DB_PREFIX}{seed}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if exists and not rebuild:
            with psycopg.connect(db_url(admin_url, seed)) as conn:
                if conn.execute("SELECT to_regclass('merchants') IS NOT NULL AND EXISTS (SELECT 1 FROM merchants)"
                                ).fetchone()[0]:
                    return False
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(db_url(admin_url, seed), autocommit=True) as conn:
        conn.execute((REPO / "server" / "schema.sql").read_text())
        for migration in sorted((REPO / "server" / "migrations").glob("*.sql")):
            conn.execute(migration.read_text())
    return True


def run_town(url: str, seed: int, key_pem: str) -> dict:
    """Run the simulator in-process (the same code as `python -m stormcash_sim`) and return labels.json."""
    from stormcash.app import build_deps
    from stormcash.config import Settings, load_server_key
    from stormcash_sim import outputs
    from stormcash_sim.engine import Params, Sim

    settings = Settings(database_url=url, server_key=load_server_key(key_pem), nessie_enabled=False,
                        background_tasks=False, stormdesk_auto=False)
    deps = build_deps(settings)
    try:
        sim = Sim(deps, Params(seed=seed, hours=HOURS, start=START))
        summary = sim.run()
        labels = outputs.labels(sim)
        folder = STATE / "sim" / str(seed)
        outputs.write(sim, summary, out_dir=STATE / "sim")
        print(f"seed {seed}: {summary.get('payments')} payments, wrote {folder}")
    finally:
        deps.pool.close()
    return labels


def label_row(cand: dict, label: dict | None) -> dict:
    """Ground truth for one candidate, from the simulator label of its subject (§16.4)."""
    if label is None:
        # The simulator only plants the labelled roles; every other shop, resident and region is honest.
        return dict(label_kind="none", label_action="none", label_scenario="honest",
                    label_note="not planted by the simulator: honest by construction", honest_subject=True)
    if label["expected_kind"] == "hard_case":
        # A cheater's cert raised a soft signal too: flagging it is right.
        return dict(label_kind=cand["kind"], label_action=label["expected_action"], label_scenario=label["scenario"],
                    label_note=label["note"], honest_subject=False)
    return dict(label_kind=label["expected_kind"], label_action=label["expected_action"],
                label_scenario=label["scenario"], label_note=label["note"],
                honest_subject=label["expected_kind"] == "none")


def rows_for_seed(url: str, seed: int, labels: dict) -> tuple[list[dict], list[dict]]:
    """(rows, misses): one row per candidate, and the labelled soft subjects no detector raised."""
    by_subject = {s["subject_id"]: s for s in labels["subjects"]}
    with psycopg.connect(url, row_factory=dict_row) as conn:
        cands = conn.execute(
            """SELECT k.candidate_id, k.kind, k.subject_id, k.window_start, k.window_end, k.features, COALESCE(
                      (SELECT display_name FROM merchants WHERE encode(merchant_id, 'hex') = k.subject_id),
                      (SELECT r.display_name FROM residents r JOIN certificates c USING (resident_id)
                       WHERE encode(c.cert_id, 'hex') = k.subject_id LIMIT 1),
                      (SELECT display_name FROM regions WHERE region_id = k.subject_id)) AS subject_name
               FROM candidates k ORDER BY k.candidate_id"""
        ).fetchall()
    rows = []
    for cand in cands:
        rows.append({
            "row_id": f"{seed}:{cand['candidate_id']}",
            "seed": seed,
            "candidate_id": cand["candidate_id"],
            "kind": cand["kind"],
            "subject_id": cand["subject_id"],
            "subject_name": cand["subject_name"] or by_subject.get(cand["subject_id"], {}).get("name"),
            "window_start": cand["window_start"],
            "window_end": cand["window_end"],
            "features": json.dumps(cand["features"], sort_keys=True),
            **label_row(cand, by_subject.get(cand["subject_id"])),
        })
    raised = {(c["kind"], c["subject_id"]) for c in cands}
    misses = [{"seed": seed, "subject_id": s["subject_id"], "name": s["name"], "scenario": s["scenario"],
               "expected_kind": s["expected_kind"]}
              for s in labels["subjects"]
              if s["expected_kind"] in SOFT_KINDS and (s["expected_kind"], s["subject_id"]) not in raised]
    return rows, misses


def git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    ap.add_argument("--admin-url", default=ADMIN_URL, help="a local Postgres to create the eval databases on")
    ap.add_argument("--rebuild", action="store_true", help="drop and re-seed the eval databases")
    args = ap.parse_args()
    check_local(args.admin_url)
    new_key = not KEY_FILE.exists()  # towns signed by a lost key can't be reused
    key_pem = server_key_pem()

    rows, misses, seeds = [], [], []
    for seed in args.seeds:
        url = db_url(args.admin_url, seed)
        labels_file = STATE / "sim" / str(seed) / "labels.json"
        # A town is reused only with its labels and its key; a seed can't run twice into one database.
        if create_db(args.admin_url, seed, args.rebuild or new_key or not labels_file.exists()):
            labels = run_town(url, seed, key_pem)
        else:
            labels = json.loads(labels_file.read_text())
            print(f"seed {seed}: already seeded, reusing {DB_PREFIX}{seed}")
        seed_rows, seed_misses = rows_for_seed(url, seed, labels)
        rows += seed_rows
        misses += seed_misses
        seeds.append({"seed": seed, "database": f"{DB_PREFIX}{seed}", "start": labels["start"],
                      "hours": labels["hours"], "candidates": len(seed_rows), "labelled_subjects": len(labels["subjects"])})

    DATASET.mkdir(exist_ok=True)
    with (DATASET / "stormdesk_triage.jsonl").open("w") as f:
        for row in rows:
            f.write(json.dumps({k: row[k] for k in COLUMNS}) + "\n")
    scenarios: dict[str, int] = {}
    for row in rows:
        scenarios[row["label_scenario"]] = scenarios.get(row["label_scenario"], 0) + 1
    meta = {
        "name": "stormdesk-triage",
        "note": "One row per detector candidate from simulated towns (spec §15.3). Every subject is simulated.",
        "rows": len(rows),
        "honest_rows": sum(r["honest_subject"] for r in rows),
        "seeds": seeds,
        "scenarios": dict(sorted(scenarios.items())),
        "detector_misses": misses,
        "built_from_git_sha": git_sha(),
    }
    (DATASET / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: meta[k] for k in ("rows", "honest_rows", "scenarios")}, indent=2))
    print(f"{len(misses)} labelled subjects never became candidates (see meta.json detector_misses)")


if __name__ == "__main__":
    sys.exit(main())
