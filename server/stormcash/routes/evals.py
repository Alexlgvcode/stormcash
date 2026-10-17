"""GET /v1/evals: the saved Chalk eval runs, for the Evals tab (spec §18.5, §15.3).

The results files (chalk/evals/results/*.json, format in chalk/evals/README.md)
are read on every request, so a new run shows up without a restart. The
comparison table gets the newest file for each column. The server re-checks
each file's claim before it fills a column (§0 rule 3):

- rules_only: runner "rules_only".
- stormdesk: runner "droid", an agent result, every row answered by Droid,
  no fallback to the fake runner, a complete run (no task errors, the eval's
  Droid guard never stopped it) and one named model on every row.

Either column also needs as many result rows as the dataset has.

Anything else (fake or mixed runners) is listed as a pipeline check, with its
run id and time but none of its numbers.

Held-out runs (eval "stormdesk-triage-heldout": seeds chosen before the run
and never used to write a prompt) are a section of their own under
`heldout`, never mixed into the main columns. In each section the rules-only
column is the newest rules-only run on the StormDesk column's dataset revision
(the same rows), or the newest one when there is no StormDesk run.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter()

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "chalk" / "evals" / "results"
EVAL_NAME = "stormdesk-triage"
HELDOUT_EVAL_NAME = "stormdesk-triage-heldout"


def results_dir(settings) -> Path:
    return Path(settings.evals_results_dir) if settings.evals_results_dir else DEFAULT_DIR


def column(run: dict) -> tuple[str | None, str | None]:
    """The comparison column a results file may fill, or None and why not."""
    claimed, runner = run.get("table_column"), run.get("runner")
    rows = (run.get("dataset") or {}).get("rows")
    if claimed in ("rules_only", "stormdesk") and rows != len(run.get("rows") or []):
        return None, "its rows don't match the dataset's row count"
    if claimed == "rules_only" and runner == "rules_only":
        return "rules_only", None
    if claimed == "stormdesk":
        fallbacks = (run.get("metrics") or {}).get("fallback_from_droid")
        models = run.get("models_seen")
        if runner != "droid" or run.get("is_agent_result") is not True:
            return None, f"runner is {runner!r}, not Droid"
        if run.get("runners_seen") != {"droid": rows} or fallbacks != 0:
            return None, "some rows weren't answered by Droid"
        if run.get("complete") is not True:
            return None, "an incomplete run (task errors, or the Droid guard stopped it)"
        if not models or len(models) != 1 or models[0] != run.get("model"):
            return None, f"not one named model on every row ({models})"
        return "stormdesk", None
    if claimed is None:
        return None, f"{run.get('runner_label') or runner}: a pipeline check, not a score"
    return None, f"unknown table_column {claimed!r}"


def load_runs(directory: Path) -> tuple[list[dict], list[dict]]:
    runs, errors = [], []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            run = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            errors.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not isinstance(run, dict) or run.get("schema_version") != 1 or \
                run.get("eval") not in (EVAL_NAME, HELDOUT_EVAL_NAME):
            errors.append({"file": path.name, "error": "not a stormdesk-triage results file (schema_version 1)"})
            continue
        runs.append({**run, "file": path.name})
    runs.sort(key=lambda r: r.get("timestamp") or 0)
    return runs, errors


def summary(run: dict, reason: str | None) -> dict:
    chalk = run.get("chalk") or {}
    return {"file": run["file"], "runner": run.get("runner"), "runner_label": run.get("runner_label"),
            "mode": run.get("mode"), "model": run.get("model"), "timestamp": run.get("timestamp"),
            "chalk_run_id": chalk.get("run_id"), "evaluation_name": chalk.get("evaluation_name"),
            "dataset_rows": (run.get("dataset") or {}).get("rows"), "reason": reason}


def section(runs: list[dict]) -> dict:
    """The newest run per column (full file), and every other run as a summary."""
    columns: dict[str, dict | None] = {"rules_only": None, "stormdesk": None}
    rules_runs, others = [], []
    for run in runs:  # oldest first, so the newest run per column wins
        col, reason = column(run)
        if col is None:
            others.append(summary(run, reason))
        elif col == "rules_only":
            rules_runs.append(run)
        else:
            if columns["stormdesk"] is not None:
                others.append(summary(columns["stormdesk"], "an older run for this column"))
            columns["stormdesk"] = run
    desk = columns["stormdesk"]
    same_rows = [r for r in rules_runs if desk is not None
                 and (r.get("dataset") or {}).get("sha256") == (desk.get("dataset") or {}).get("sha256")]
    columns["rules_only"] = (same_rows or rules_runs or [None])[-1]
    others += [summary(r, "an older run for this column" if desk is None or r in same_rows
                       else "a rules-only run on other rows than the StormDesk column")
               for r in rules_runs if r is not columns["rules_only"]]
    others.sort(key=lambda o: o.get("timestamp") or 0)
    return {"columns": columns, "other_runs": others[::-1]}


@router.get("/v1/evals")
def evals(request: Request) -> dict:
    """The main section (columns, other runs) and the held-out section."""
    directory = results_dir(request.app.state.deps.settings)
    runs, errors = load_runs(directory)
    main = section([r for r in runs if r.get("eval") == EVAL_NAME])
    heldout = section([r for r in runs if r.get("eval") == HELDOUT_EVAL_NAME])
    return {**main, "heldout": heldout, "errors": errors, "runs_found": len(runs)}
