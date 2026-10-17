"""Freeze a finished StormDesk run's outputs as a dataset for the second-opinion reviewer.

    cd chalk && uv run python evals/build_review_dataset.py 51b74f56-d8d8-466b-a07c-3ddf8baa8064 --name heldout-v2

Reads the run's Chalk result dataset (exactly the outputs that run was scored
on) and writes dataset/stormdesk_review_<name>.jsonl: every dataset column, plus
`v2_output` (the task output as scored), `v2_server_run_id` (the stormdesk_runs
row in that seed's eval database, the stored proposal the reviewer reads) and
`v2_session_id`. Reviewing these costs only the reviewer's credits: StormDesk
isn't run again. meta_review_<name>.json records the source run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import chalkcompute

EVALS = Path(__file__).resolve().parent
COLUMNS = ("row_id", "seed", "candidate_id", "kind", "subject_id", "subject_name", "window_start", "window_end",
           "features", "label_kind", "label_action", "label_scenario", "label_note", "honest_subject")


def review_rows(result_rows: list[dict]) -> list[dict]:
    """The scored outputs of a finished run, one row per dataset row, in dataset order."""
    rows = []
    for r in sorted(result_rows, key=lambda r: (r["seed"], r["candidate_id"])):
        if r.get("output_error"):
            raise SystemExit(f"row {r['row_id']} has no output ({r['output_error']}): only complete runs can be reviewed")
        run = json.loads(r["output"]).get("_run") or {}
        if run.get("runner") != "droid":
            raise SystemExit(f"row {r['row_id']} was answered by {run.get('runner')!r}, not Droid")
        rows.append({**{k: r[k] for k in COLUMNS}, "v2_output": r["output"],
                     "v2_server_run_id": run.get("run_id"), "v2_session_id": run.get("session_id")})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_id", help="a succeeded, complete Droid run (Chalk evaluation run id)")
    ap.add_argument("--name", required=True, help="dataset name suffix, e.g. heldout-v2")
    args = ap.parse_args()
    run = chalkcompute.EvaluationRun.from_id(args.run_id)
    if run.status != chalkcompute.EvaluationRunStatus.SUCCEEDED or run.result_dataset is None:
        raise SystemExit(f"run {run.id} is {run.status.name}")
    evaluation = chalkcompute.Evaluation.from_id(run.evaluation_id)
    rows = review_rows(chalkcompute.DatasetClient().read(run.result_dataset).to_pylist())
    slug = args.name.replace("-", "_")
    out = EVALS / "dataset" / f"stormdesk_review_{slug}.jsonl"
    raw = "".join(json.dumps(r) + "\n" for r in rows)
    out.write_text(raw)
    meta = {
        "name": f"stormdesk-review-{args.name}",
        "note": "A finished StormDesk run's outputs, frozen for the second-opinion reviewer. Every subject is simulated.",
        "source_run_id": run.id, "source_evaluation": evaluation.name,
        "source_dataset_revision_id": evaluation.dataset_revision_id,
        "prompt_versions": sorted({json.loads(r["v2_output"])["_run"].get("prompt_version") for r in rows}),
        "models": sorted({m for r in rows for m in json.loads(r["v2_output"])["_run"].get("models_used") or []}),
        "rows": len(rows), "honest_rows": sum(r["honest_subject"] for r in rows),
        "seeds": sorted({r["seed"] for r in rows}), "sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }
    (EVALS / "dataset" / f"meta_review_{slug}.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
