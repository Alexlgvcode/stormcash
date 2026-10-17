"""Fallback (spec §15.3, §22.4): run StormDesk locally over the dataset, then score the outputs in Chalk.

    server/.venv/bin/python chalk/evals/stack.py up --runner fake --no-tunnel
    cd chalk && uv run python evals/run_local.py

For when the Chalk task can't reach the tunnel. Every row goes through the
same local gateway and `POST /v1/stormdesk/run` as the Chalk task (at most 4 at
a time), so the outputs are identical in shape. The rows are then uploaded
with their output in `agent_output` as a dataset of their own, and a Chalk
Evaluation whose task just replays that column (task_replay.py) scores them
with the same five scorers. Results are saved as
results/<timestamp>-<runner>-local.json with `mode: "run_local"`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from run_eval import STATE, load_rows, run_and_save, upload

CONCURRENCY = 4  # the server runs at most 4 StormDesk jobs at a time (§14.1)
MAX_WAIT_S = 1200


def call(base: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def run_row(base: str, token: str, row: dict) -> str:
    job = call(base, token, "POST", "/runs", {"seed": row["seed"], "candidate_id": row["candidate_id"]})
    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        time.sleep(2)
        state = call(base, token, "GET", f"/runs/{job['job_id']}")
        if state["status"] == "done":
            return state["output"]
        if state["status"] == "failed":
            return f"StormDesk run failed: {state['error']}"
    return f"StormDesk run timed out after {MAX_WAIT_S} s"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.parse_args()
    stack_file = STATE / "stack.json"
    if not stack_file.exists():
        raise SystemExit("the eval stack is down: server/.venv/bin/python chalk/evals/stack.py up --runner ...")
    stack = json.loads(stack_file.read_text())
    token = (STATE / "gateway_token").read_text().strip()
    rows, sha = load_rows()

    started = time.time()
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        outputs = list(pool.map(lambda row: run_row(stack["gateway_local"], token, row), rows))
    print(f"ran StormDesk on {len(rows)} rows locally in {time.time() - started:.0f} s", flush=True)

    import eval_scorers
    import task_replay

    local_rows = [{**row, "agent_output": out} for row, out in zip(rows, outputs, strict=True)]
    ref = upload("stormdesk-triage-run-local", local_rows)
    configured = stack["runner"]
    run_and_save(
        name=f"StormDesk triage (run_local): server ({'Droid' if configured == 'droid' else 'fake runner, not an agent'})",
        dataset_ref=ref, task=task_replay.replay_output, scorers=eval_scorers.SCORERS, mode="run_local",
        dataset_sha=sha, metadata={"configured_runner": configured, "configured_model": stack.get("model")},
    )


if __name__ == "__main__":
    sys.exit(main())
