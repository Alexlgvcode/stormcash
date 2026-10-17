"""Compare the Scale Lab with the Python town simulator, metric by metric.

Reads python_engine.json (run_python_engine.py: one stats.json per seed) and a
stormcash-scale output for the same parameters, treats every seed / replicate
as one independent sample, and reports for each metric the mean with a 95%
confidence interval on both sides, and the difference (Scale Lab - Python)
with a Welch 95% interval. "agree" means that interval contains 0: the data
can't tell the two models apart at this sample size. It doesn't mean equal.

    python cpp/scale/validation/compare.py \\
        cpp/scale/results/validation/python_engine.json \\
        cpp/scale/results/validation/scale_lab.json \\
        --out cpp/scale/results/validation/comparison.json

Standard library only. Everything compared is simulated.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# Two-sided 97.5% Student t quantiles, df 1..30 (as cpp/scale/src/stats.cpp).
T_TABLE = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145,
           2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045,
           2.042]


def t975(df: float) -> float:
    if df < 1:
        return float("nan")
    if df <= 30:
        # Welch df is fractional: interpolate between table rows.
        lo = int(math.floor(df))
        hi = min(lo + 1, 30)
        frac = df - lo
        return T_TABLE[lo - 1] * (1 - frac) + T_TABLE[hi - 1] * frac
    z = 1.959963984540054
    return (z + (z**3 + z) / (4 * df) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)
            + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * df**3))


def describe(values: list[float]) -> dict | None:
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    half = t975(n - 1) * math.sqrt(var / n) if n > 1 else 0.0
    return {"n": n, "mean": mean, "var": var, "ci95": [mean - half, mean + half]}


def welch(a: dict, b: dict) -> dict:
    """Difference b - a with a Welch 95% interval."""
    va, vb = a["var"] / a["n"], b["var"] / b["n"]
    diff = b["mean"] - a["mean"]
    se = math.sqrt(va + vb)
    if se == 0:
        return {"diff": diff, "ci95": [diff, diff], "agree": diff == 0}
    df = (va + vb) ** 2 / ((va**2 / (a["n"] - 1) if a["n"] > 1 else 0) + (vb**2 / (b["n"] - 1) if b["n"] > 1 else 0))
    half = t975(df) * se
    return {"diff": diff, "ci95": [diff - half, diff + half], "agree": diff - half <= 0 <= diff + half}


def mean_hops(hist: dict) -> float | None:
    total = sum(hist.values())
    return sum(int(k) * v for k, v in hist.items()) / total if total else None


METRICS = {
    # name: (getter from one stats.json-shaped record, decimals to print)
    "share_refused_offline": (lambda r: r["double_spends"]["share_refused_offline"], 3),
    "share_caught_at_settlement": (lambda r: r["double_spends"]["share_caught_at_settlement"], 3),
    "mean_loss_per_cheater_cents": (lambda r: r["mean_loss_per_cheater_cents"], 0),
    "median_hours_to_settlement": (lambda r: r["median_hours_to_settlement"], 2),
    "mean_hops_to_server": (lambda r: mean_hops(r["hops_histogram"]), 2),
    "double_spend_attempts": (lambda r: r["double_spends"]["attempts"], 2),
    "payments": (lambda r: r["summary"]["payments"], 0),
    "refused_payments": (lambda r: r["summary"]["refused"] if isinstance(r["summary"]["refused"], int)
                         else sum(r["summary"]["refused"].values()), 1),
    "out_of_money": (lambda r: r["summary"]["out_of_money"], 0),
    "contacts": (lambda r: r["summary"]["contacts"], 0),
}


def values(records: list[dict], getter) -> list[float]:
    out = []
    for r in records:
        v = getter(r)
        if v is not None:
            out.append(float(v))
    return out


def pooled(records: list[dict]) -> dict:
    attempts = sum(r["double_spends"]["attempts"] for r in records)
    refused = sum(r["double_spends"]["refused_offline"] for r in records)
    caught = sum(r["double_spends"]["caught_at_settlement"] for r in records)
    hops: dict[str, int] = {}
    for r in records:
        for k, v in r["hops_histogram"].items():
            hops[k] = hops.get(k, 0) + v
    total = sum(hops.values())
    return {
        "attempts": attempts,
        "share_refused_offline": refused / attempts if attempts else None,
        "share_caught_at_settlement": caught / attempts if attempts else None,
        "hops_share": {k: hops[k] / total for k in sorted(hops, key=int)},
    }


def fmt(x: float | None, places: int) -> str:
    return "n/a" if x is None else f"{x:,.{places}f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("python_json")
    ap.add_argument("scale_json")
    ap.add_argument("--out")
    args = ap.parse_args()

    py = json.loads(Path(args.python_json).read_text())["runs"]
    sl = json.loads(Path(args.scale_json).read_text())["runs"][0]["replicates"]

    rows = {}
    print(f"Python engine: {len(py)} seeds. Scale Lab: {len(sl)} replicates. 95% CIs. SIMULATED.\n")
    print("| Metric | Python engine | Scale Lab | Scale Lab - Python | |")
    print("|---|---|---|---|---|")
    for name, (getter, places) in METRICS.items():
        a, b = describe(values(py, getter)), describe(values(sl, getter))
        d = welch(a, b)
        rows[name] = {"python": a, "scale_lab": b, "difference": d}
        cell = lambda e: f"{fmt(e['mean'], places)} [{fmt(e['ci95'][0], places)}, {fmt(e['ci95'][1], places)}]"
        print(f"| {name} | {cell(a)} | {cell(b)} | {fmt(d['diff'], places)} [{fmt(d['ci95'][0], places)}, "
              f"{fmt(d['ci95'][1], places)}] | {'agree' if d['agree'] else 'DIFFER'} |")

    pa, pb = pooled(py), pooled(sl)
    print(f"\nPooled: Python {pa['attempts']} attempts, refused {fmt(pa['share_refused_offline'], 3)}, "
          f"caught {fmt(pa['share_caught_at_settlement'], 3)}; Scale Lab {pb['attempts']} attempts, refused "
          f"{fmt(pb['share_refused_offline'], 3)}, caught {fmt(pb['share_caught_at_settlement'], 3)}")
    print("\nHops to the server (share of PAYs that reached it):")
    print("| Hops | " + " | ".join(str(k) for k in range(9)) + " | 9+ |")
    print("|---|" + "---|" * 10)
    for label, p in (("Python engine", pa), ("Scale Lab", pb)):
        shares = p["hops_share"]
        cells = [fmt(shares.get(str(k), 0.0), 3) for k in range(9)]
        cells.append(fmt(sum(v for k, v in shares.items() if int(k) >= 9), 3))
        print(f"| {label} | " + " | ".join(cells) + " |")

    if args.out:
        Path(args.out).write_text(json.dumps({"simulated": True, "metrics": rows, "pooled": {"python": pa,
                                              "scale_lab": pb}}, indent=1) + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
