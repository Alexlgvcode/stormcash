"""Markdown tables for cpp/scale/README.md from the result files (all SIMULATED).

    python cpp/scale/report.py cpp/scale/results/sweep_residents.json [...]

Prints, per parameter point: the swept value, adopters and shops per
replicate, double-spend attempts, the share refused offline and caught at
settlement (pooled, with the 95% interval of the replicate mean), mean loss
per cheater, median hours to settlement, and the wall time. Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def ci(e: dict | None, places: int, pct: bool = False) -> str:
    if e is None:
        return "n/a"
    f = 100 if pct else 1
    lo, hi = e["ci95"]
    return f"{e['mean'] * f:.{places}f} [{lo * f:.{places}f}, {hi * f:.{places}f}]"


def table(path: Path) -> str:
    doc = json.loads(path.read_text())
    axis = doc.get("axis") or "point"
    lines = [
        f"**{doc['label']}** (`{path.name}`): {doc['runs'][0]['summary']['replicates']} replicates per point, "
        f"{doc['threads']} threads, {doc['wall_seconds']} s in total on {doc['machine']['cpu']}.",
        "",
        f"| {axis} | adopters | shops | double spends | refused offline % | caught at settlement % | "
        "loss per cheater ¢ | median h to settle | s per replicate |",
        "|---|---:|---:|---:|---|---|---|---|---:|",
    ]
    for run in doc["runs"]:
        p, s, reps = run["params"], run["summary"], run["replicates"]
        value = p["residents"] if axis in ("point", "residents") else p[axis]
        adopters = sum(r["summary"]["residents"] for r in reps) / len(reps)
        shops = reps[0]["summary"]["shops"]
        refused = s["share_refused_offline"]
        caught = s["share_caught_at_settlement"]
        loss = s["mean_loss_per_cheater_cents"]
        shown = f"{value:,}" if isinstance(value, int) else str(value)
        lines.append(
            f"| {shown} | {adopters:,.0f} | {shops:,} | {s['totals']['double_spend_attempts']:,} | "
            f"{refused['pooled'] * 100:.1f} ({ci(refused['replicate_mean'], 1, True)}) | "
            f"{caught['pooled'] * 100:.1f} ({ci(caught['replicate_mean'], 1, True)}) | "
            f"{loss['pooled']} ({ci(loss['replicate_mean'], 0)}) | "
            f"{ci(s['median_hours_to_settlement']['replicate_mean'], 2)} | "
            f"{s['wall_seconds_per_replicate']['mean']:.3f} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print("\n\n".join(table(Path(p)) for p in sys.argv[1:]))
