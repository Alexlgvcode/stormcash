"""labels.json and stats.json (spec §16.5), written to sim/out/<seed>/."""

from __future__ import annotations

import dataclasses
import json
import statistics
from pathlib import Path

from stormcash.db import all_rows

OUT_DIR = Path(__file__).resolve().parents[1] / "out"


def stats(sim, summary: dict) -> dict:
    """The numbers the Town tab charts: double spends refused offline vs caught
    at settlement, loss per cheater, time to settlement, hops."""
    s = sim.stats
    attempts = s.attempts
    with sim.deps.pool.connection() as conn:
        in_cases = {bytes(r["h"]) for r in all_rows(
            conn, "SELECT tag_a AS h FROM cases WHERE tag_a IS NOT NULL "
                  "UNION SELECT tag_b FROM cases WHERE tag_b IS NOT NULL")}
        cheater_certs = [sim.devices[i].cert.cert_id for i in sim.plan.cheaters] if sim.plan else []
        pool_loss = all_rows(
            conn, "SELECT COALESCE(sum(funded_pool_cents), 0) AS c FROM payments WHERE cert_id = ANY(%s)",
            (cheater_certs,),
        )[0]["c"]
        hops = {str(r["hops"]): r["n"] for r in all_rows(
            conn, "SELECT hops, count(*) AS n FROM payments WHERE hops IS NOT NULL GROUP BY hops ORDER BY hops")}
        candidates = {r["kind"]: r["n"] for r in all_rows(
            conn, "SELECT kind, count(*) AS n FROM candidates GROUP BY kind ORDER BY kind")}
        cases = {r["rule"]: r["n"] for r in all_rows(
            conn, "SELECT rule, count(*) AS n FROM cases GROUP BY rule ORDER BY rule")}
    refused = [a for a in attempts if a.refused is not None]
    accepted = [a for a in attempts if a.refused is None]
    caught = [a for a in accepted if a.tag_hash in in_cases]
    n = len(attempts)
    delays_h = [(s.settle_time[k] - t) / 3600 for k, t in s.pay_time.items() if k in s.settle_time]
    return {
        "seed": sim.p.seed,
        "params": dataclasses.asdict(sim.p),
        "summary": summary,
        "double_spends": {
            "attempts": n,
            "refused_offline": len(refused),
            "accepted_offline": len(accepted),
            "caught_at_settlement": len(caught),
            "not_caught_by_end": len(accepted) - len(caught),
            "share_refused_offline": round(len(refused) / n, 4) if n else None,
            "share_caught_at_settlement": round(len(caught) / n, 4) if n else None,
            "refusals_by_check": _count(a.refused for a in refused),
            "by_mode": _count(a.mode for a in attempts),
        },
        "cheaters": len(cheater_certs),
        "mean_loss_per_cheater_cents": round(pool_loss / len(cheater_certs)) if cheater_certs else None,
        "median_hours_to_settlement": round(statistics.median(delays_h), 2) if delays_h else None,
        "hops_histogram": hops,
        "candidates": candidates,
        "cases": cases,
    }


def _count(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def labels(sim) -> dict:
    return {
        "seed": sim.p.seed,
        "start": sim.t0,
        "hours": sim.p.hours,
        "note": "Ground truth for StormDesk evals (spec §15.3, §16.4). Simulated town; every subject is simulated.",
        "subjects": [dataclasses.asdict(label) for label in sim.plan.labels] if sim.plan else [],
    }


def write(sim, summary: dict, out_dir: Path | None = None) -> Path:
    folder = (out_dir or OUT_DIR) / str(sim.p.seed)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "labels.json").write_text(json.dumps(labels(sim), indent=2) + "\n")
    (folder / "stats.json").write_text(json.dumps(stats(sim, summary), indent=2) + "\n")
    return folder
