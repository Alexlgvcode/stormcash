"""Start or stop the eval stack: one server per seed town, the gateway, the tunnel.

    server/.venv/bin/python chalk/evals/stack.py up --runner fake
    server/.venv/bin/python chalk/evals/stack.py up --runner droid --model claude-sonnet-5-5 --max-credits 2500000
    server/.venv/bin/python chalk/evals/stack.py status
    server/.venv/bin/python chalk/evals/stack.py down

Each server runs against its seed's LOCAL eval database (build_dataset.py made
them) with Nessie, Photon, Chalk, the background loops and the StormDesk worker
switched off: the only StormDesk runs are the ones the eval asks for. The
gateway (gateway.py) sits in front of them and a cloudflared quick tunnel gives
it a public URL for the Chalk task. Everything is written to
chalk/evals/.state/stack.json (URLs, runner, pids); logs go to .state/logs/.

`--runner droid` reads FACTORY_API_KEY from --factory-env (the main checkout's
server/.env by default) and passes it to the servers only; without one, Droid
uses the `droid` CLI's login. `--no-tunnel` skips
cloudflared (enough for run_local.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from build_dataset import ADMIN_URL, KEY_FILE, SEEDS, STATE, check_local, db_url

EVALS = Path(__file__).resolve().parent
STACK = STATE / "stack.json"
TOKEN_FILE = STATE / "gateway_token"
LOGS = STATE / "logs"
GATEWAY_PORT = 8800
BASE_PORT = 8100
DEFAULT_FACTORY_ENV = Path.home() / "BatmanCave" / "stormcash" / "server" / ".env"
SESSIONS_ROOT = Path.home() / ".factory" / "sessions"


def gateway_token() -> str:
    if not TOKEN_FILE.exists():
        STATE.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
        TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text().strip()


def spawn(name: str, cmd: list[str], env: dict[str, str]) -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = (LOGS / f"{name}.log").open("ab")
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                            cwd=EVALS)
    return proc.pid


def wait_http(url: str, headers: dict[str, str] | None = None, timeout_s: float = 60.0) -> int:
    """Poll until the URL answers anything at all; returns the status code."""
    deadline = time.time() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (urllib.error.URLError, OSError):
            if time.time() > deadline:
                raise SystemExit(f"{url} never answered (see {LOGS})")
            time.sleep(1)


def tunnel_url(log_file: Path, timeout_s: float = 60.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        found = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", log_file.read_text(errors="replace")
                          if log_file.exists() else "")
        if found:
            return found.group(0)
        time.sleep(1)
    raise SystemExit(f"cloudflared gave no URL (see {log_file})")


def factory_key(path: Path) -> str:
    """FACTORY_API_KEY from the main checkout's .env or the environment; empty means the droid CLI's own login."""
    from dotenv import dotenv_values

    key = (dotenv_values(path) if path.exists() else {}).get("FACTORY_API_KEY") or os.environ.get("FACTORY_API_KEY")
    if not key:
        print(f"no FACTORY_API_KEY in {path} or the environment: Droid uses the droid CLI's login", flush=True)
    return key or ""


def up(args) -> None:
    if args.runner == "droid" and not (args.model and args.max_credits):
        raise SystemExit("--runner droid needs --model (every row must use it) and --max-credits (a hard cap)")
    if STACK.exists():
        raise SystemExit("the stack is already up (stack.py down first)")
    check_local(args.admin_url)
    if not KEY_FILE.exists():
        raise SystemExit("no eval towns yet: run build_dataset.py first")
    token = gateway_token()
    base_env = {k: v for k, v in os.environ.items() if not k.startswith(("CHALK_", "NESSIE_", "PHOTON_"))}
    server_env = {
        **base_env,
        "SERVER_SIGNING_KEY_PEM": KEY_FILE.read_text(),
        "NESSIE_DISABLED": "1", "PHOTON_DISABLED": "1", "CHALK_DISABLED": "1",
        "BACKGROUND_TASKS": "0", "STORMDESK_AUTO": "0", "DEMO_MODE": "1",
        "STORMDESK_RUNNER": args.runner, "STORMDESK_MODEL": args.model or "",
        "FACTORY_API_KEY": factory_key(args.factory_env) if args.runner == "droid" else "",
    }
    pids, servers = {}, {}
    for i, seed in enumerate(args.seeds):
        port = BASE_PORT + i
        servers[seed] = f"http://127.0.0.1:{port}"
        pids[f"server-{seed}"] = spawn(
            f"server-{seed}",
            [sys.executable, "-m", "uvicorn", "--factory", "stormcash.app:create_app", "--host", "127.0.0.1",
             "--port", str(port)],
            {**server_env, "DATABASE_URL": db_url(args.admin_url, seed)},
        )
    gateway_cmd = [sys.executable, str(EVALS / "gateway.py"), "--port", str(GATEWAY_PORT)]
    gateway_cmd += [f"--server={seed}={url}" for seed, url in servers.items()]
    if args.model:
        gateway_cmd += ["--model", args.model]
    if args.runner == "droid":
        # Droid keeps a session per run under ~/.factory/sessions/<server cwd, punctuation as ->/; the gateway
        # audits them (one model only, no fallback, a hard credit cap) and takes the exact folder from the
        # first row's session.
        gateway_cmd += ["--require-model", args.model, "--max-credits", str(args.max_credits),
                        "--sessions-dir", str(SESSIONS_ROOT / re.sub(r"[^A-Za-z0-9_-]", "-", str(EVALS)))]
    pids["gateway"] = spawn("gateway", gateway_cmd, {**base_env, "EVAL_GATEWAY_TOKEN": token})
    state = {"runner": args.runner, "model": args.model, "max_credits": args.max_credits, "servers": {str(k): v for k, v in servers.items()},
             "gateway_local": f"http://127.0.0.1:{GATEWAY_PORT}", "public_url": None, "pids": pids,
             "started_at": int(time.time())}
    STACK.write_text(json.dumps(state, indent=2))

    for seed, url in servers.items():
        wait_http(f"{url}/v1/health")
    auth = {"Authorization": f"Bearer {token}"}
    wait_http(f"{state['gateway_local']}/runs/{'0' * 32}", auth)
    if not args.no_tunnel:
        log_file = LOGS / "cloudflared.log"
        log_file.unlink(missing_ok=True)
        pids["cloudflared"] = spawn("cloudflared", ["cloudflared", "tunnel", "--no-autoupdate", "--url",
                                                    state["gateway_local"]], base_env)
        state["public_url"] = tunnel_url(log_file)
        STACK.write_text(json.dumps(state, indent=2))
        code = wait_http(f"{state['public_url']}/runs/{'0' * 32}", auth, timeout_s=90)
        if code != 404:
            raise SystemExit(f"the tunnel answered {code}, expected the gateway's 404")
    STACK.write_text(json.dumps(state, indent=2))
    print(json.dumps({k: state[k] for k in ("runner", "model", "servers", "gateway_local", "public_url")}, indent=2))


def down(_args) -> None:
    if not STACK.exists():
        print("the stack is not up")
        return
    state = json.loads(STACK.read_text())
    for name, pid in state["pids"].items():
        try:
            os.killpg(pid, signal.SIGTERM)
            print(f"stopped {name} ({pid})")
        except ProcessLookupError:
            print(f"{name} ({pid}) was not running")
    STACK.unlink()


def status(_args) -> None:
    if not STACK.exists():
        print("the stack is not up")
        return
    state = json.loads(STACK.read_text())
    for name, pid in state["pids"].items():
        try:
            os.kill(pid, 0)
            alive = "running"
        except ProcessLookupError:
            alive = "NOT running"
        print(f"{name:14} {pid:>7} {alive}")
    print(json.dumps({k: state.get(k) for k in ("runner", "model", "max_credits", "gateway_local", "public_url")},
                     indent=2))
    try:  # the gateway's live Droid audit: credits so far, models seen, breaker
        req = urllib.request.Request(state["gateway_local"] + "/stats",
                                     headers={"Authorization": f"Bearer {gateway_token()}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(json.dumps(json.loads(resp.read()), indent=2))
    except (urllib.error.URLError, OSError) as exc:
        print(f"gateway /stats unavailable: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p_up = sub.add_parser("up")
    p_up.add_argument("--runner", choices=("fake", "droid"), required=True)
    p_up.add_argument("--model", default=None, help="STORMDESK_MODEL for Droid, e.g. claude-sonnet-5-5")
    p_up.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    p_up.add_argument("--admin-url", default=ADMIN_URL)
    p_up.add_argument("--factory-env", type=Path, default=DEFAULT_FACTORY_ENV)
    p_up.add_argument("--max-credits", type=float, default=None,
                      help="droid: the gateway refuses new rows once the eval's Droid sessions used this many credits")
    p_up.add_argument("--no-tunnel", action="store_true")
    sub.add_parser("down")
    sub.add_parser("status")
    args = ap.parse_args()
    {"up": up, "down": down, "status": status}[args.command](args)


if __name__ == "__main__":
    main()
