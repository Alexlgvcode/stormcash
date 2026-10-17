"""The eval gateway: one URL in front of the per-seed eval servers (spec §15.3).

    python chalk/evals/gateway.py --port 8800 --server 42=http://127.0.0.1:8142 --server 7=...

The Chalk task reaches it through a cloudflared quick tunnel. It does three
things the task can't do by calling the server directly:

- routes a row to the server holding its seed's town (one database per seed);
- turns a StormDesk run into a job the task polls, so a 30-90 s agent run never
  hits the tunnel's ~100 s response limit;
- answers nothing but these two routes, and only with the bearer token
  (EVAL_GATEWAY_TOKEN), so the tunnel exposes no other server endpoint.

    POST /runs {"seed": 42, "candidate_id": 3}  -> 202 {"job_id": "..."}
    GET  /runs/<job_id>                          -> {"status": "running" | "done" | "failed", "output": "..."}

Each job calls the real `POST /v1/stormdesk/run {candidate_id}` on that seed's
server. `output` is what the task returns: the Flag JSON plus a `_run` object
with the server's verdict (runner, citation check, fallback). A run with no
Flag gives a plain-text output, which no scorer can pass. Stdlib only.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPERATOR = "chalk-eval"  # X-SC-Operator on every run (§14.6 operator header)
RUN_TIMEOUT_S = 900
JOB_TTL_S = 6 * 3600


def to_output(result: dict, model: str | None = None) -> str:
    """The task's output for one server run: the Flag JSON with the server's verdict under `_run`."""
    run = {
        "run_id": result.get("run_id"),
        "runner": result.get("runner"),
        "model": model if result.get("runner") == "droid" else None,
        "status": result.get("status"),
        "citations_valid": result.get("citations_valid"),
        "missing_citations": result.get("missing_citations") or [],
        "fallback_from_droid": result.get("fallback_from_droid"),
        "error": result.get("error"),
    }
    flag = result.get("output")
    if not isinstance(flag, dict):
        return f"StormDesk produced no Flag (runner {run['runner']}, status {run['status']}): {run['error']}"
    return json.dumps({**flag, "_run": run}, sort_keys=True)


class Jobs:
    def __init__(self, servers: dict[int, str], model: str | None) -> None:
        self.servers, self.model = servers, model
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, seed: int, candidate_id: int) -> str:
        if seed not in self.servers:
            raise KeyError(f"no eval server for seed {seed}")
        job_id = uuid.uuid4().hex
        with self.lock:
            now = time.time()
            self.jobs = {k: v for k, v in self.jobs.items() if now - v["started"] < JOB_TTL_S}
            self.jobs[job_id] = {"status": "running", "seed": seed, "candidate_id": candidate_id, "started": now}
        threading.Thread(target=self._run, args=(job_id, seed, candidate_id), daemon=True).start()
        return job_id

    def _run(self, job_id: str, seed: int, candidate_id: int) -> None:
        req = urllib.request.Request(
            f"{self.servers[seed]}/v1/stormdesk/run", method="POST",
            data=json.dumps({"candidate_id": candidate_id}).encode(),
            headers={"Content-Type": "application/json", "X-SC-Operator": OPERATOR},
        )
        try:
            with urllib.request.urlopen(req, timeout=RUN_TIMEOUT_S) as resp:
                update = {"status": "done", "output": to_output(json.loads(resp.read()), self.model)}
        except urllib.error.HTTPError as exc:
            update = {"status": "failed", "error": f"server answered {exc.code}: {exc.read()[:300].decode(errors='replace')}"}
        except Exception as exc:  # the server is down or timed out: the task reports it as a row error
            update = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        with self.lock:
            self.jobs[job_id].update(update, finished=time.time())

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None


def make_handler(jobs: Jobs, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            given = self.headers.get("Authorization", "")
            if hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
                return True
            self._send(401, {"error": "unauthorized"})
            return False

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/runs":
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                job_id = jobs.start(int(body["seed"]), int(body["candidate_id"]))
            except (ValueError, KeyError, TypeError) as exc:
                return self._send(400, {"error": str(exc)})
            self._send(202, {"job_id": job_id})

        def do_GET(self) -> None:  # noqa: N802
            match = re.fullmatch(r"/runs/([0-9a-f]{32})", self.path)
            if not match:
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return
            job = jobs.get(match.group(1))
            self._send(200, job) if job else self._send(404, {"error": "no such job"})

        def log_message(self, fmt: str, *args) -> None:
            print(f"gateway: {self.address_string()} {fmt % args}", flush=True)

    return Handler


def parse_servers(specs: list[str]) -> dict[int, str]:
    servers = {}
    for spec in specs:
        seed, _, url = spec.partition("=")
        servers[int(seed)] = url.rstrip("/")
    return servers


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--server", action="append", default=[], help="SEED=URL of that seed's eval server")
    ap.add_argument("--model", default=None, help="the model the eval servers ask Droid for (recorded in _run)")
    args = ap.parse_args()
    token = os.environ.get("EVAL_GATEWAY_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("set EVAL_GATEWAY_TOKEN (24+ characters)")
    jobs = Jobs(parse_servers(args.server), args.model)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(jobs, token))
    print(f"gateway: listening on 127.0.0.1:{args.port} for seeds {sorted(jobs.servers)}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
