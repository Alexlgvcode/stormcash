"""Run the StormDesk triage eval in Chalk and save the result (spec §15.3).

    cd chalk && uv run python evals/run_eval.py rules_only   # the §13 baseline, entirely in Chalk
    cd chalk && uv run python evals/run_eval.py stormdesk    # the agent, through the eval stack's tunnel
    cd chalk && uv run python evals/run_eval.py resummarize <run_id>  # rewrite a run's results file from Chalk

`stormdesk` needs the eval stack up with a tunnel (stack.py up --runner ...);
which runner answered is read back from the outputs. Both upload the dataset
once (a new revision only when dataset/stormdesk_triage.jsonl changes), create
an Evaluation in the "StormCash" suite with the five scorers, run it, read the
result dataset and write results/<timestamp>-<runner>.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import chalkcompute

import results

EVALS = Path(__file__).resolve().parent
STATE = EVALS / ".state"
DATASETS = {  # as in build_dataset.py: name -> (Chalk dataset / eval name, rows file, meta file)
    "main": ("stormdesk-triage", "stormdesk_triage.jsonl", "meta.json"),
    "heldout": ("stormdesk-triage-heldout", "stormdesk_triage_heldout.jsonl", "meta_heldout.json"),
}
RESULTS = EVALS / "results"
UPLOADS = STATE / "chalk_datasets.json"
SUITE = "StormCash"
RUN_TIMEOUT_S = 3600


def load_rows(dataset: str = "main", seeds: list[int] | None = None) -> tuple[list[dict], str]:
    """The dataset's rows (only `seeds`, if given) and the sha256 of exactly those lines."""
    lines = [line for line in (EVALS / "dataset" / DATASETS[dataset][1]).read_text().splitlines() if line.strip()]
    if seeds is not None:
        lines = [line for line in lines if json.loads(line)["seed"] in seeds]
    raw = "".join(line + "\n" for line in lines).encode()
    return [json.loads(line) for line in lines], hashlib.sha256(raw).hexdigest()


def git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=EVALS, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def upload(name: str, rows: list[dict], sha: str | None = None) -> chalkcompute.DatasetRevisionRef:
    """Upload rows as a dataset revision; with `sha`, reuse the revision already uploaded for that content."""
    cache = json.loads(UPLOADS.read_text()) if UPLOADS.exists() else {}
    key = f"{name}:{sha}" if sha else None
    if key and key in cache:
        return chalkcompute.DatasetRevisionRef(dataset_id=cache[key]["dataset_id"],
                                               revision_id=cache[key]["revision_id"])
    ref = chalkcompute.DatasetClient().upload(name, rows)
    if key:
        STATE.mkdir(exist_ok=True)
        cache[key] = {"dataset_id": ref.dataset_id, "revision_id": ref.revision_id, "uploaded_at": int(time.time())}
        UPLOADS.write_text(json.dumps(cache, indent=2))
    return ref


def suite() -> chalkcompute.EvaluationSuite:
    return next((s for s in chalkcompute.EvaluationSuite.list_all() if s.name == SUITE), None) \
        or chalkcompute.EvaluationSuite.create(SUITE)


def named_scores(rows: list[dict], evaluation) -> list[dict]:
    """A scorer that returns a list is stored as `scorer_<evaluation scorer id>` (a list of {score, metadata});
    give it its name's `_value` / `_error` columns like the others. Scorer ids follow eval_scorers.SCORERS."""
    names = dict(zip((s.id for s in evaluation.scorers), evaluation.metadata.get("scorers") or results.SCORERS,
                     strict=True))
    for row in rows:
        for scorer_id, name in names.items():
            if f"scorer_{scorer_id}" in row:
                row[f"{name}_value"] = [e["score"] for e in row.pop(f"scorer_{scorer_id}") or []]
                row[f"{name}_error"] = row.pop(f"scorer_{scorer_id}_error", None)
    return rows


def run_and_save(*, name: str, dataset_ref, task, scorers: dict, mode: str, dataset_sha: str, metadata: dict) -> Path:
    """Create the Evaluation, run it to the end, and write its results file."""
    the_suite = suite()
    evaluation = chalkcompute.Evaluation.create(
        name, dataset=dataset_ref, task=task, scorers=list(scorers.values()), suite_id=the_suite.id,
        metadata={"spec": "§15.3", "mode": mode, "dataset_sha256": dataset_sha, "scorers": list(scorers), **metadata},
    )
    print(f"evaluation {evaluation.id} ({name}); running...", flush=True)
    run = evaluation.run(metadata={"git_sha": git_sha() or "", "mode": mode})
    print(f"run {run.id} queued", flush=True)
    run = run.wait(timeout=RUN_TIMEOUT_S, raise_on_failure=False)
    print(f"run {run.id}: {run.status.name}", flush=True)
    return save_results(evaluation, run, droid_audit=gateway_stats())


def gateway_stats() -> dict | None:
    """The local gateway's Droid audit (credits and models over every eval session), if a Droid stack is up."""
    stack_file = STATE / "stack.json"
    if not stack_file.exists() or json.loads(stack_file.read_text()).get("runner") != "droid":
        return None
    stack = json.loads(stack_file.read_text())
    req = urllib.request.Request(stack["gateway_local"] + "/stats", headers={
        "Authorization": f"Bearer {(STATE / 'gateway_token').read_text().strip()}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def save_results(evaluation, run, droid_audit: dict | None = None) -> Path:
    """Read a succeeded run's result dataset and write its results file (named by when the run completed)."""
    label, label_note = evaluation.metadata.get("label"), evaluation.metadata.get("label_note")
    dataset = evaluation.metadata.get("dataset") or "main"
    eval_name, _, meta_file = DATASETS[dataset]
    if run.status != chalkcompute.EvaluationRunStatus.SUCCEEDED or run.result_dataset is None:
        raise SystemExit(f"run {run.id} ended {run.status.name}: {run.error_message} (no results saved)")
    rows = named_scores(chalkcompute.DatasetClient().read(run.result_dataset).to_pylist(), evaluation)
    rows.sort(key=lambda r: (r["seed"], r["candidate_id"]))
    meta = json.loads((EVALS / "dataset" / meta_file).read_text())
    seeds = [int(x) for x in evaluation.metadata.get("seeds") or [m["seed"] for m in meta["seeds"]]]  # JSON floats
    scenarios: dict[str, int] = {}
    for r in rows:
        scenarios[r["label_scenario"]] = scenarios.get(r["label_scenario"], 0) + 1
    mode, dataset_sha = evaluation.metadata.get("mode"), evaluation.metadata.get("dataset_sha256")
    now = int(run.completed_at.timestamp()) if run.completed_at else int(time.time())
    summary = results.summarize(
        rows, scorers=evaluation.metadata.get("scorers") or list(results.SCORERS),
        chalk={
            "environment_id": evaluation.environment_id, "suite": SUITE, "suite_id": evaluation.suite_id,
            "evaluation_id": evaluation.id, "evaluation_name": evaluation.name, "run_id": run.id,
            "status": run.status.name,
            "task_function_version_id": evaluation.task_function_version_id,
            "dataset_id": evaluation.dataset_id, "dataset_revision_id": evaluation.dataset_revision_id,
            "result_dataset_id": run.result_dataset_id, "result_dataset_revision_id": run.result_dataset_revision_id,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        dataset={"name": meta["name"], "rows": len(rows), "honest_rows": sum(r["honest_subject"] for r in rows),
                 "seeds": seeds, "scenarios": dict(sorted(scenarios.items())),
                 "detector_misses": [m for m in meta["detector_misses"] if m["seed"] in seeds], "sha256": dataset_sha},
        eval_name=eval_name,
        mode=mode, git_sha=(run.metadata or {}).get("git_sha") or None, now=now, droid_audit=droid_audit,
        label=label, label_note=label_note, expect_prompt_version=evaluation.metadata.get("expect_prompt_version"),
    )
    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") if label else ""
    heldout = f"-heldout-seeds-{'-'.join(map(str, seeds))}" if dataset == "heldout" else ""
    path = RESULTS / (f"{stamp}-{summary['runner']}{'-local' if mode == 'run_local' else ''}{heldout}"
                      f"{'-' + slug if slug else ''}{'' if summary['complete'] else '-incomplete'}.json")
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print_summary(summary, path)
    return path


def print_summary(summary: dict, path: Path) -> None:
    m = summary["metrics"]
    print(f"\n{summary['runner_label']} — {summary['dataset']['rows']} rows, Chalk run {summary['chalk']['run_id']}")
    for name, s in summary["scorers"].items():
        print(f"  {name:16} mean {s['mean']}  ({s['scored_rows']} rows scored, {s['errors']} errors)")
    print(f"  real cases caught  {m['real_caught']['caught']}/{m['real_caught']['total']}"
          f"   colluders caught {m['colluders_caught']['caught']}/{m['colluders_caught']['total']}"
          f"   honest flagged {m['honest_flagged']['flagged']}/{m['honest_flagged']['total']}")
    print(f"  rows without a Flag {m['rows_without_flag']}, task errors {m['task_errors']}, "
          f"Droid fallbacks {m['fallback_from_droid']}, models {summary['models_seen']}, "
          f"credits (rows) {m['factory_credits']['rows_total']}")
    if summary.get("droid_audit"):
        print(f"  Droid audit: {json.dumps(summary['droid_audit'])}")
    print(f"wrote {path.relative_to(EVALS.parent)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("task", choices=("rules_only", "stormdesk", "resummarize"))
    ap.add_argument("run_id", nargs="?", help="resummarize: rewrite this run's results file from its result dataset")
    ap.add_argument("--dataset", choices=DATASETS, default="main",
                    help="heldout: the held-out seeds (README), a separate dataset and results section")
    ap.add_argument("--seeds", type=int, nargs="+", help="only these seeds' rows (a separate dataset revision)")
    ap.add_argument("--audit-from", type=Path,
                    help="resummarize: keep the Droid audit the gateway recorded at run time, from that run's file")
    ap.add_argument("--label", help='a name for this version of the agent, e.g. "prompt v2" (kept in the results)')
    ap.add_argument("--label-note", help="what a reader must know about this version, saved next to the label")
    ap.add_argument("--expect-prompt-version", type=int,
                    help="stormdesk: every row must report this prompt_version, or the result isn't StormDesk's")
    args = ap.parse_args()
    if args.task == "resummarize":
        run = chalkcompute.EvaluationRun.from_id(args.run_id)
        audit = json.loads(args.audit_from.read_text()).get("droid_audit") if args.audit_from else None
        save_results(chalkcompute.Evaluation.from_id(run.evaluation_id), run, droid_audit=audit)
        return
    rows, sha = load_rows(args.dataset, args.seeds)
    chalk_dataset = DATASETS[args.dataset][0]
    print(f"{chalk_dataset}: {len(rows)} rows from seeds {sorted({r['seed'] for r in rows})}", flush=True)

    if args.task == "stormdesk":
        stack_file = STATE / "stack.json"
        if not stack_file.exists():
            raise SystemExit("the eval stack is down: server/.venv/bin/python chalk/evals/stack.py up --runner ...")
        stack = json.loads(stack_file.read_text())
        if not stack.get("public_url"):
            raise SystemExit("the eval stack has no tunnel (it was started with --no-tunnel); use run_local.py")
        os.environ["EVAL_GATEWAY_URL"] = stack["public_url"]  # read by task_stormdesk at deploy time
        os.environ["EVAL_GATEWAY_TOKEN"] = (STATE / "gateway_token").read_text().strip()
        import task_stormdesk as task_module
        task = task_module.stormdesk_triage
        configured = stack["runner"]
        name = f"StormDesk triage: server ({'Droid' if configured == 'droid' else 'fake runner, not an agent'})"
        name += f" · {args.label}" if args.label else ""
        metadata = {"configured_runner": configured, "configured_model": stack.get("model"),
                    "label": args.label, "label_note": args.label_note,
                    "expect_prompt_version": args.expect_prompt_version}
    else:
        import task_rules_only as task_module
        task = task_module.rules_only
        name = "StormDesk triage: rules-only baseline"
        metadata = {"configured_runner": "rules_only"}
    if args.dataset == "heldout":
        name += f" · held-out seeds {', '.join(map(str, args.seeds or sorted({r['seed'] for r in rows})))}"
    metadata |= {"dataset": args.dataset, "seeds": args.seeds or sorted({r["seed"] for r in rows})}

    import eval_scorers

    scorers = eval_scorers.RULES_ONLY_SCORERS if args.task == "rules_only" else eval_scorers.SCORERS

    ref = upload(chalk_dataset, rows, sha)
    run_and_save(name=name, dataset_ref=ref, task=task, scorers=scorers, mode="chalk_task",
                 dataset_sha=sha, metadata=metadata)


if __name__ == "__main__":
    sys.exit(main())
