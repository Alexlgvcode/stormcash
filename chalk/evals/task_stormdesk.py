"""The StormDesk task (spec §15.3): run the real agent on one candidate and return its Flag.

Chalk's functions can't run the local `droid` CLI, so this calls the eval
gateway (gateway.py) through the cloudflared tunnel; the gateway calls
`POST /v1/stormdesk/run {candidate_id}` on the server holding that seed's town
and the task polls until the run is done. Which runner answered (droid or the
labelled fake runner) is in the output's `_run.runner`, set by the server.

EVAL_GATEWAY_URL (the tunnel) and EVAL_GATEWAY_TOKEN are read from the local
environment at deploy time; run_eval.py sets both from .state/stack.json.
Self-contained: Chalk ships this one file.
"""

import json
import os
import time
import urllib.error
import urllib.request

import chalkcompute

POLL_S = 3
MAX_WAIT_S = 1200


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        os.environ["EVAL_GATEWAY_URL"].rstrip("/") + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['EVAL_GATEWAY_TOKEN']}", "Content-Type": "application/json"},
    )
    for attempt in range(5):  # the tunnel can drop a request; the gateway's routes are safe to retry
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == 4:
                raise RuntimeError(f"gateway answered {exc.code} on {path}: {exc.read()[:200]!r}") from exc
        except (urllib.error.URLError, OSError):
            if attempt == 4:
                raise
        time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


@chalkcompute.function(
    name="sd-stormdesk-triage",
    env={"EVAL_GATEWAY_URL": os.environ.get("EVAL_GATEWAY_URL", "")},
    secrets=[chalkcompute.Secret.from_local_env("EVAL_GATEWAY_TOKEN")],
    concurrency=4,  # the server runs at most 4 StormDesk jobs at a time (§14.1)
    call_timeout=MAX_WAIT_S + 60,
)
def stormdesk_triage(seed: int, candidate_id: int) -> str:
    # One StormDesk run per (evaluation run, row), even if Chalk delivers this call twice.
    run_id = chalkcompute.get_call_context().get("x-chalk-evaluation-run-id") or "no-run"
    job = _call("POST", "/runs", {"seed": seed, "candidate_id": candidate_id,
                                  "request_id": f"{run_id}:{seed}:{candidate_id}"})
    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        time.sleep(POLL_S)
        state = _call("GET", f"/runs/{job['job_id']}")
        if state["status"] == "done":
            return state["output"]
        if state["status"] == "failed":
            raise RuntimeError(f"StormDesk run failed for seed {seed} candidate {candidate_id}: {state['error']}")
    raise TimeoutError(f"no StormDesk result for seed {seed} candidate {candidate_id} after {MAX_WAIT_S} s")
