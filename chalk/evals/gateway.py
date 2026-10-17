"""The eval gateway: one URL in front of the per-seed eval servers (spec §15.3).

    python chalk/evals/gateway.py --port 8800 --server 42=http://127.0.0.1:8142 --server 7=...

The Chalk task reaches it through a cloudflared quick tunnel. It does three
things the task can't do by calling the server directly:

- routes a row to the server holding its seed's town (one database per seed);
- turns a StormDesk run into a job the task polls, so a 30-90 s agent run never
  hits the tunnel's ~100 s response limit;
- answers nothing but these two routes, and only with the bearer token
  (EVAL_GATEWAY_TOKEN), so the tunnel exposes no other server endpoint.

    POST /runs {"seed": 42, "candidate_id": 3}  -> 202 {"job_id": "..."}  (409 once the breaker trips)
    GET  /runs/<job_id>                          -> {"status": "running" | "done" | "failed", "output": "..."}
    GET  /stats                                  -> the Droid audit: credits, models, breaker

Each job calls the real `POST /v1/stormdesk/run {candidate_id}` on that seed's
server. `output` is what the task returns: the Flag JSON plus a `_run` object
with the server's verdict (runner, citation check, fallback) and, for Droid,
the model and Factory credits read from the run's own Droid session files. A
run with no Flag gives a plain-text output, which no scorer can pass.

Droid guard (`--require-model`, `--max-credits`): the audit sums every Droid
session the eval servers created since the gateway started (retries included).
The breaker trips, and new rows are refused, as soon as any session used
another model (Factory switches to "Droid Core" when usage runs out), a row
fell back to the fake runner, or the credit cap is reached. A row is only
admitted if credits spent plus the running rows and itself, at the average row
cost, still fit under the cap, so the cap holds with rows in flight. Stdlib only.
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
ROW_MARGIN = 1.25  # a row may cost more than the average so far


SESSIONS_ROOT = os.path.expanduser("~/.factory/sessions")


def session_info(path_stem: str) -> dict:
    """Model(s) and Factory credits of one Droid session, from its local files (<id>.jsonl, <id>.settings.json)."""
    models: set[str] = set()
    credits = None
    try:
        with open(path_stem + ".settings.json") as f:
            settings = json.load(f)
        credits = (settings.get("tokenUsage") or {}).get("factoryCredits")
    except (OSError, ValueError):
        settings = {}
    try:
        with open(path_stem + ".jsonl") as f:
            for line in f:
                message = json.loads(line).get("message") or {}
                if message.get("modelId"):
                    models.add(message["modelId"])
    except (OSError, ValueError):
        pass
    return {"models_used": sorted(models), "factory_credits": credits, "configured_model": settings.get("model")}


def find_session(session_id: str | None, root: str = SESSIONS_ROOT) -> dict | None:
    if not session_id or not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        return None
    for folder in os.listdir(root) if os.path.isdir(root) else []:
        stem = os.path.join(root, folder, session_id)
        if os.path.exists(stem + ".jsonl"):
            return {**session_info(stem), "folder": os.path.join(root, folder)}
    return None


def audit(sessions_dir: str | None, since: float) -> dict:
    """Every Droid session in the eval servers' folder written since `since`: credits and models."""
    sessions, credits, models = 0, 0.0, set()
    if sessions_dir and os.path.isdir(sessions_dir):
        for name in os.listdir(sessions_dir):
            stem = os.path.join(sessions_dir, name[: -len(".jsonl")])
            if not name.endswith(".jsonl") or os.path.getmtime(stem + ".jsonl") < since:
                continue
            info = session_info(stem)
            sessions += 1
            credits += info["factory_credits"] or 0
            models.update(info["models_used"])
    return {"sessions": sessions, "factory_credits": credits, "models_seen": sorted(models)}


def to_output(result: dict, model: str | None = None, session: dict | None = None) -> str:
    """The task's output for one server run: the Flag JSON with the server's verdict under `_run`."""
    droid = result.get("runner") == "droid"
    run = {
        "run_id": result.get("run_id"),
        "runner": result.get("runner"),
        "model": model if droid else None,
        "session_id": ((result.get("flag") or {}).get("agent_session_id")) if droid else None,
        "models_used": (session or {}).get("models_used") if droid else None,
        "factory_credits": (session or {}).get("factory_credits") if droid else None,
        # From the server itself once it reports them (#81): the session's actual model and summed usage.
        "server_model": result.get("model") if droid else None,
        "server_usage": result.get("usage") if droid else None,
        "prompt_version": result.get("prompt_version") if droid else None,
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


class Refused(Exception):
    pass


class Jobs:
    def __init__(self, servers: dict[int, str], model: str | None, *, require_model: str | None = None,
                 max_credits: float | None = None, sessions_dir: str | None = None,
                 sessions_root: str = SESSIONS_ROOT, row_estimate: float = 0.0,
                 require_prompt_version: int | None = None) -> None:
        self.servers, self.model = servers, model
        self.require_model, self.max_credits, self.sessions_dir = require_model, max_credits, sessions_dir
        self.sessions_root = sessions_root
        self.row_estimate = row_estimate
        self.require_prompt_version = require_prompt_version
        self.started = time.time()
        self.tripped: str | None = None
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def stats(self) -> dict:
        with self.lock:
            done = [j for j in self.jobs.values() if j["status"] != "running"]
            return {"tripped": self.tripped, "require_model": self.require_model, "max_credits": self.max_credits,
                    "require_prompt_version": self.require_prompt_version,
                    "jobs_done": len(done), "jobs_running": len(self.jobs) - len(done),
                    "audit": audit(self.sessions_dir, self.started)}

    def _check(self, result: dict | None, session: dict | None) -> None:
        """Trip the breaker on a model change, a fallback to the fake runner, or the credit cap."""
        if not self.require_model:
            return
        reason = None
        if result is not None and result.get("runner") != "droid":
            reason = f"a row was answered by {result.get('runner')} ({result.get('fallback_from_droid')})"
        elif result is not None and (session is None or not session["models_used"]):
            reason = "a Droid row has no session files to read its model from"
        elif session is not None and session["models_used"] != [self.require_model]:
            reason = f"a session used {session['models_used']}, not {self.require_model}"
        elif result is not None and result.get("model") not in (None, self.require_model):
            reason = f"the server says the run used {result.get('model')}, not {self.require_model}"
        elif result is not None and self.require_prompt_version is not None and \
                result.get("prompt_version") != self.require_prompt_version:
            reason = f"a row ran prompt_version {result.get('prompt_version')}, not {self.require_prompt_version}"
        totals = audit(self.sessions_dir, self.started)
        if reason is None and any(m != self.require_model for m in totals["models_seen"]):
            reason = f"the eval sessions used {totals['models_seen']}, not only {self.require_model}"
        if reason is None and self.max_credits and totals["factory_credits"] >= self.max_credits:
            reason = f"credit cap reached: {totals['factory_credits']:.0f} >= {self.max_credits:.0f}"
        if reason:
            with self.lock:
                self.tripped = self.tripped or reason
            print(f"gateway: BREAKER TRIPPED: {reason}", flush=True)

    def projected_credits(self, extra: int = 0) -> float:
        """Credits spent so far plus the rows still running and `extra` new ones, each at 1.25 x the average
        done row (row_estimate until a row is done). In-flight sessions are counted in both: deliberately cautious."""
        with self.lock:
            done = [j["credits"] for j in self.jobs.values() if j.get("credits") is not None]
            running = sum(1 for j in self.jobs.values() if j["status"] == "running")
        per_row = ROW_MARGIN * sum(done) / len(done) if done else self.row_estimate
        return audit(self.sessions_dir, self.started)["factory_credits"] + (running + extra) * per_row

    def start(self, seed: int, candidate_id: int) -> str:
        if seed not in self.servers:
            raise KeyError(f"no eval server for seed {seed}")
        if self.tripped:
            raise Refused(f"refusing new rows: {self.tripped}")
        if self.max_credits and (projected := self.projected_credits(extra=1)) > self.max_credits:
            # Admit a row only if it should still fit under the cap, so the cap holds with rows in flight.
            reason = f"credit cap: one more row projects {projected:.0f} > {self.max_credits:.0f}"
            with self.lock:
                self.tripped = self.tripped or reason
            print(f"gateway: BREAKER TRIPPED: {reason}", flush=True)
            raise Refused(f"refusing new rows: {reason}")
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
        result = session = None
        try:
            with urllib.request.urlopen(req, timeout=RUN_TIMEOUT_S) as resp:
                result = json.loads(resp.read())
            if result.get("runner") == "droid":
                session = find_session((result.get("flag") or {}).get("agent_session_id"), self.sessions_root)
                if session and session["folder"] != self.sessions_dir:
                    # The audit follows the folder Droid actually wrote the eval servers' sessions to.
                    print(f"gateway: auditing Droid sessions in {session['folder']}", flush=True)
                    self.sessions_dir = session["folder"]
            update = {"status": "done", "output": to_output(result, self.model, session),
                      "credits": (session or {}).get("factory_credits")}
        except urllib.error.HTTPError as exc:
            update = {"status": "failed", "error": f"server answered {exc.code}: {exc.read()[:300].decode(errors='replace')}"}
        except Exception as exc:  # the server is down or timed out: the task reports it as a row error
            update = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        with self.lock:
            self.jobs[job_id].update(update, finished=time.time())
        self._check(result, session)

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
            except Refused as exc:
                return self._send(409, {"error": str(exc)})
            except (ValueError, KeyError, TypeError) as exc:
                return self._send(400, {"error": str(exc)})
            self._send(202, {"job_id": job_id})

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/stats":
                return self._send(200, jobs.stats()) if self._authorized() else None
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
    ap.add_argument("--require-model", default=None, help="trip the breaker if any Droid session uses another model")
    ap.add_argument("--max-credits", type=float, default=None,
                    help="a hard cap: admit a row only while spent + running + this row (at the average row cost) fits")
    ap.add_argument("--require-prompt-version", type=int, default=None,
                    help="trip the breaker if any Droid row reports another StormDesk prompt_version")
    ap.add_argument("--row-estimate", type=float, default=65000.0,
                    help="credits per row assumed until rows are done (a triage took 16k-65k on claude-sonnet-5-5)")
    ap.add_argument("--sessions-dir", default=None,
                    help="the eval servers' Droid session folder (a hint: the first row's session sets it)")
    args = ap.parse_args()
    token = os.environ.get("EVAL_GATEWAY_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("set EVAL_GATEWAY_TOKEN (24+ characters)")
    jobs = Jobs(parse_servers(args.server), args.model, require_model=args.require_model,
                max_credits=args.max_credits, sessions_dir=args.sessions_dir, row_estimate=args.row_estimate,
                require_prompt_version=args.require_prompt_version)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(jobs, token))
    print(f"gateway: listening on 127.0.0.1:{args.port} for seeds {sorted(jobs.servers)}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
