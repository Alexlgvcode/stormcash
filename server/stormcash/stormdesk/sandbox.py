"""Where the author job lets Droid write code, and nothing else (spec §14.7d).

Droid gets write-capable tools here, so each layer below confines it on its own:

1. A throwaway git worktree of the base ref (origin/main) in a temp directory
   outside every checkout. A fresh worktree has no `.env`; one appearing is refused.
   Droid's session runs there.
2. The permission handler (`AuthorGuard`): Create / Edit / ApplyPatch only on the
   two allowlisted files of one detector name, our MCP tools, and nothing else.
   Every refusal is recorded.
3. Droid's CLI doesn't ask before reads, and it auto-runs shell commands it rates
   read-only (`ls`, checked Oct 17 on droid 0.244.0) without asking either. So
   its built-in read tools and its shell (Execute) are off. It reads through our
   MCP tools, confined to the worktree (never held-out rows, eval results, `.git`
   or `.env` files), and the two allowlisted commands are two MCP tools,
   `run_tests` and `run_eval`, with a budget.
4. The `droid` process runs under `sandbox-exec` with a scrubbed environment:
   writes only inside the sandbox (plus `~/.factory` and temp), and no reads of
   `.env` files, credentials or held-out data.
5. Our server, outside Droid's profile, runs the tests and the eval in a second
   profile: no network (so no database either), writes only to the sandbox's
   tmp, a scrubbed environment, a time limit.
6. After the session closes (author.py): the changed files are checked against
   the allowlist, the detector's purity, a secret scan, then our own re-run.

macOS only for now (`sandbox-exec`): without it the author job refuses to run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import SERVER_DIR

log = logging.getLogger(__name__)

LAB_SERVER_NAME = "stormdesk_lab"
# The two allowlisted commands, as tools: run_tests runs pytest on the test file, run_eval our evaluation script.
RUN_TOOLS = {"run_tests": "test", "run_eval": "eval"}
LAB_TOOL_NAMES = ("read_file", "list_dir", "search", *RUN_TOOLS)
NAME_PATTERN = r"[a-z][a-z0-9_]{2,40}"
DETECTOR_PATH = re.compile(rf"server/stormcash/detectors_proposed/(?P<name>{NAME_PATTERN})\.py")
TEST_PATH = re.compile(rf"server/tests/test_proposed_(?P<name>{NAME_PATTERN})\.py")
BUDGET = {"test": 6, "eval": 3}  # lab runs per session; a held-out score can't be probed run after run
MAX_FILE_BYTES = 20_000
LAB_TIMEOUT_S = 120
OUTPUT_LIMIT = 8_000
# The built-in tools an author session keeps; each one asks the permission handler. Every other built-in is off,
# the shell (Execute) included.
WRITE_TOOLS = frozenset({"Create", "Edit", "ApplyPatch"})
# Never served to Droid: held-out rows (it gets only their aggregates), the eval results that quote rows,
# git internals, env files, keys and the eval stack's state.
HIDDEN = re.compile(r"(^|/)(\.git|\.state|node_modules)(/|$)|(^|/)\.env[^/]*$|heldout|(^|/)chalk/evals/results(/|$)"
                    r"|\.pem$")
DATA_DIR = SERVER_DIR.parent / "chalk" / "evals" / "dataset"  # the trusted copy of the labelled rows
HOME = Path.home()
SECRET_HOME_DIRS = (".ssh", ".config/gh", ".aws", ".docker", ".kube", ".gnupg", "Library/Keychains")
SECRET_HOME_FILES = (".netrc", ".git-credentials", ".pgpass")


class SandboxError(RuntimeError):
    pass


def sandbox_exec() -> str | None:
    return shutil.which("sandbox-exec") if sys.platform == "darwin" else None


def _git(cwd: Path, *args: str, timeout: float = 60) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise SandboxError(f"git {' '.join(args[:2])} failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def _sb(path: Path | str) -> str:
    return json.dumps(str(path))  # an SBPL string literal


def _secret_rules(extra: tuple[str, ...] = (), allow_keychains: bool = False) -> str:
    """Deny reading credentials. `allow_keychains`: the droid CLI's own login is in the login keychain, which the
    Security framework reads in-process, so only Droid's profile allows it (its items stay encrypted)."""
    rules = [f"(subpath {_sb(HOME / d)})" for d in SECRET_HOME_DIRS if not (allow_keychains and d == "Library/Keychains")]
    rules += [f"(literal {_sb(HOME / f)})" for f in SECRET_HOME_FILES]
    # Not *.pem: TLS needs the CA bundles. The server's signing key lives in .env.
    rules += ['(regex #"/\\.env[^/]*$")', '(regex #"/\\.state/")', *extra]
    return "(deny file-read-data\n  " + "\n  ".join(rules) + ")"  # contents; stat still works (pytest walks dirs)


@dataclass
class Sandbox:
    root: Path
    repo: Path
    repo_root: Path  # the checkout the worktree belongs to
    base_ref: str
    base_sha: str
    os_sandbox: bool = True

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def droid_executable(self) -> Path:
        return self.bin / "droid-sandboxed"

    def detector_file(self, name: str) -> Path:
        return self.repo / "server" / "stormcash" / "detectors_proposed" / f"{name}.py"

    def test_file(self, name: str) -> Path:
        return self.repo / "server" / "tests" / f"test_proposed_{name}.py"

    def hidden_rules(self) -> str:
        return ('(regex #"heldout")', f"(subpath {_sb(self.repo / 'chalk' / 'evals' / 'results')})",
                f"(subpath {_sb(DATA_DIR.parent / 'results')})")

    def droid_profile(self) -> str:
        """The droid CLI and whatever its Execute runs: writes inside the sandbox (plus Droid's own
        ~/.factory and temp) only; no secrets, no held-out data. Network stays: Droid talks to Factory
        and to our MCP server on loopback."""
        writes = [self.root, HOME / ".factory", Path("/private/tmp"), Path("/private/var/folders"), Path("/dev")]
        return "\n".join([
            "(version 1)", "(allow default)", "(deny file-write*)",
            "(allow file-write* " + " ".join(f"(subpath {_sb(p)})" for p in writes) + ")",
            _secret_rules(self.hidden_rules(), allow_keychains=True),
        ])

    def lab_profile(self, show_heldout: bool) -> str:
        """Tests and the eval: no network, writes only to the sandbox's tmp. The tests (Droid's code) can't
        read held-out data either; the eval (our code, a purity-checked detector) reads it."""
        writes = " ".join(f"(subpath {_sb(p)})" for p in (self.tmp, self.root / "home"))
        hidden = self.hidden_rules() if not show_heldout else self.hidden_rules()[1:]
        return "\n".join([
            "(version 1)", "(allow default)", "(deny network*)", "(deny file-write*)",
            f'(allow file-write* {writes} (literal "/dev/null") (literal "/dev/zero") (regex #"^/dev/(tty|fd/)"))',
            _secret_rules((f"(subpath {_sb(HOME / '.factory')})", *hidden)),
        ])

    def lab_command(self, cmd: str, name: str) -> tuple[list[str], Path, dict]:
        """(argv, cwd, env) for one lab run: pytest on the test file, or our eval on the detector."""
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.root / "home"), "TMPDIR": str(self.tmp),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "LANG": "C.UTF-8"}
        if cmd == "test":
            env["PYTHONPATH"] = str(self.repo / "server")  # the worktree's stormcash, not the server's
            argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"tests/test_proposed_{name}.py"]
            return argv, self.repo / "server", env
        env["PYTHONPATH"] = str(SERVER_DIR)  # our evaluator, from the running server's code
        argv = [sys.executable, "-m", "stormcash.stormdesk.detector_eval", "--detector",
                str(self.detector_file(name)), "--data", str(DATA_DIR)]
        return argv, self.tmp, env

    async def run_lab(self, cmd: str, name: str) -> dict:
        """Run `test` or `eval` in the lab profile. Returns {cmd, name, exit_code, output, duration_s}."""
        argv, cwd, env = self.lab_command(cmd, name)
        if self.os_sandbox:
            profile = self.root / f"lab-{cmd}.sb"
            profile.write_text(self.lab_profile(show_heldout=cmd == "eval"))
            argv = [sandbox_exec() or "/usr/bin/sandbox-exec", "-f", str(profile), *argv]
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), LAB_TIMEOUT_S)
            code = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            out, code = f"stopped after {LAB_TIMEOUT_S} s".encode(), 124
        text = out.decode(errors="replace")
        if len(text) > OUTPUT_LIMIT:
            text = "…" + text[-OUTPUT_LIMIT:]
        return {"cmd": cmd, "name": name, "exit_code": code, "output": text,
                "duration_s": round(time.monotonic() - started, 1)}

    def changed_files(self) -> list[str]:
        """Every path git sees as changed or new in the worktree, relative to it."""
        out = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"], cwd=self.repo,
                             capture_output=True, text=True, timeout=30).stdout
        paths, parts = [], out.split("\0")
        i = 0
        while i < len(parts):
            entry = parts[i]
            if len(entry) > 3:
                paths.append(entry[3:])
                if entry[0] in "RC":  # a rename lists its source next
                    i += 1
                    paths.append(parts[i])
            i += 1
        return sorted(set(paths))

    def remove(self) -> None:
        try:
            _git(self.repo_root, "worktree", "remove", "--force", str(self.repo))
        except (SandboxError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        shutil.rmtree(self.root, ignore_errors=True)
        try:
            _git(self.repo_root, "worktree", "prune")
        except (SandboxError, subprocess.TimeoutExpired):
            pass


def create(base_ref: str, repo_root: Path | None = None, os_sandbox: bool = True) -> Sandbox:
    """A fresh worktree of `base_ref` in a new temp directory, plus the droid wrapper.
    `os_sandbox=False` is for tests on machines without sandbox-exec; the author job never passes it."""
    if os_sandbox and sandbox_exec() is None:
        raise SandboxError("no OS sandbox on this machine (the author job needs macOS sandbox-exec)")
    repo_root = Path(repo_root or _git(SERVER_DIR, "rev-parse", "--show-toplevel")).resolve()
    root = Path(tempfile.mkdtemp(prefix="stormdesk-author-")).resolve()
    if root.is_relative_to(repo_root):
        shutil.rmtree(root, ignore_errors=True)
        raise SandboxError("the sandbox must be outside the checkout")
    for sub in ("bin", "tmp", "home"):
        (root / sub).mkdir()
    if base_ref.startswith("origin/"):  # best effort: the newest main, but a stale one still works
        try:
            _git(repo_root, "fetch", "-q", "origin", base_ref.split("/", 1)[1], timeout=30)
        except (SandboxError, subprocess.TimeoutExpired):
            log.warning("git fetch failed; the sandbox uses the local %s", base_ref)
    try:
        _git(repo_root, "worktree", "add", "--detach", str(root / "repo"), base_ref, timeout=120)
        box = Sandbox(root, root / "repo", repo_root, base_ref, _git(root / "repo", "rev-parse", "HEAD"),
                      os_sandbox)
        leaked = [str(p.relative_to(box.repo)) for p in box.repo.rglob(".env*") if p.name != ".env.example"]
        if leaked:
            raise SandboxError(f"the worktree has env files: {leaked}")
        _write_scripts(box)
    except BaseException:
        Sandbox(root, root / "repo", repo_root, base_ref, "").remove()
        raise
    return box


def _write_scripts(box: Sandbox) -> None:
    droid = shutil.which("droid") or "droid"
    profile = box.root / "droid.sb"
    profile.write_text(box.droid_profile())
    path = ":".join(["/usr/bin", "/bin", str(Path(droid).parent)])
    # Only what's set: an empty FACTORY_API_KEY would hide the CLI's own login.
    keep = " ".join(f'${{{k}:+"{k}=${k}"}}' for k in ("FACTORY_API_KEY", "FACTORY_UPSTREAM_CLIENT_TYPE",
                                                     "FACTORY_UPSTREAM_SDK"))
    run = f'"{sandbox_exec()}" -f "{profile}" "{droid}"' if box.os_sandbox else f'"{droid}"'
    box.droid_executable.write_text(
        "#!/bin/sh\n# The droid CLI with a scrubbed environment, inside the sandbox profile.\n"
        f'exec /usr/bin/env -i PATH="{path}" HOME="{HOME}" TMPDIR="{box.tmp}" {keep} {run} "$@"\n')
    box.droid_executable.chmod(0o755)


# Droid's read tools ---------------------------------------------------------------------------


class LabFiles:
    """Read-only views of the worktree for Droid: no path outside it, nothing in HIDDEN."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo.resolve()

    def _path(self, path: str) -> tuple[Path, str]:
        p = (self.repo / path.lstrip("/")) if not Path(path).is_absolute() else Path(path)
        resolved = p.resolve()
        if not resolved.is_relative_to(self.repo):
            raise ValueError("outside the sandbox repository")
        rel = resolved.relative_to(self.repo).as_posix()
        if rel != "." and HIDDEN.search(rel):
            raise ValueError(f"{rel} is not available here")
        return resolved, rel

    def read(self, path: str, offset: int = 1, limit: int = 300) -> dict:
        try:
            p, rel = self._path(path)
            lines = p.read_text(errors="replace").splitlines()
        except (ValueError, OSError) as exc:
            return {"error": str(exc)}
        start = max(offset, 1) - 1
        chunk = lines[start:start + max(1, min(limit, 600))]
        return {"path": rel, "lines": len(lines), "from": start + 1, "text": "\n".join(chunk)}

    def list(self, path: str = ".") -> dict:
        try:
            p, rel = self._path(path)
            entries = sorted(p.iterdir())
        except (ValueError, OSError) as exc:
            return {"error": str(exc)}
        out = []
        for e in entries:
            r = e.relative_to(self.repo).as_posix()
            if not HIDDEN.search(r) and not e.is_symlink():
                out.append(r + ("/" if e.is_dir() else ""))
        return {"path": rel, "entries": out[:300]}

    def search(self, pattern: str, path: str = ".") -> dict:
        try:
            base, rel = self._path(path)
            rx = re.compile(pattern)
        except (ValueError, re.error) as exc:
            return {"error": str(exc)}
        matches = []
        files = [base] if base.is_file() else sorted(base.rglob("*"))
        for f in files:
            r = f.relative_to(self.repo).as_posix()
            if HIDDEN.search(r) or f.is_symlink() or not f.is_file() or f.stat().st_size > 1_000_000:
                continue
            try:
                for n, line in enumerate(f.read_text().splitlines(), 1):
                    if rx.search(line):
                        matches.append(f"{r}:{n}: {line.strip()[:200]}")
                        if len(matches) >= 50:
                            return {"matches": matches, "truncated": True}
            except (UnicodeDecodeError, OSError):
                continue
        return {"matches": matches, "truncated": False}


def lab_mcp_server(files: LabFiles, box: Sandbox | None = None, guard: AuthorGuard | None = None,
                   runs: list | None = None):
    """Droid's read tools, and (with a box and a guard) the two allowlisted commands as tools."""
    from droid_sdk.mcp import create_sdk_mcp_server, tool

    async def run(cmd: str, name: str) -> dict:
        reason = guard.allow_lab(cmd, name) if guard else "no lab in this session"
        if reason:
            return {"error": reason}
        result = await box.run_lab(cmd, name)
        if runs is not None:
            runs.append({k: v for k, v in result.items() if k != "output"} | {"output_tail": result["output"][-600:]})
        return {"exit_code": result["exit_code"], "output": result["output"]}

    async def run_tests(name: str) -> dict:
        return await run("test", name)

    async def run_eval(name: str) -> dict:
        return await run("eval", name)

    async def read_file(path: str, offset: int = 1, limit: int = 300) -> dict:
        return await asyncio.to_thread(files.read, path, offset, limit)

    async def list_dir(path: str = ".") -> dict:
        return await asyncio.to_thread(files.list, path)

    async def search(pattern: str, path: str = ".") -> dict:
        return await asyncio.to_thread(files.search, pattern, path)

    return create_sdk_mcp_server(name=LAB_SERVER_NAME, tools=[
        tool("read_file", "Read a text file of the sandbox repository (path relative to its root), from line "
                          "`offset`, at most `limit` lines.")(read_file),
        tool("list_dir", "List a directory of the sandbox repository (path relative to its root).")(list_dir),
        tool("search", "Search the sandbox repository's text files for a Python regex (at most 50 matches).")(search),
        tool("run_tests", "Run pytest on server/tests/test_proposed_<name>.py (no network, no database). Returns "
                          "exit_code and output.")(run_tests),
        tool("run_eval", "Run our evaluation script on server/stormcash/detectors_proposed/<name>.py: precision and "
                         "recall against the labels, next to the rules-only baseline, on dev and held-out rows. "
                         "Returns exit_code and output (JSON).")(run_eval),
    ])


# The permission handler ------------------------------------------------------------------------


@dataclass
class AuthorGuard:
    """Decides every permission request of an author session, and records each refusal."""

    repo: Path
    name: str | None = None  # the detector's name, fixed by the first allowed edit
    denials: list[dict] = field(default_factory=list)
    used: Counter = field(default_factory=Counter)  # lab runs allowed so far, by cmd

    def _target(self, path: str) -> tuple[str | None, str | None]:
        """(name, None) for an allowlisted file, else (None, reason)."""
        p = Path(path) if Path(path).is_absolute() else self.repo / path
        try:
            rel = p.resolve().relative_to(self.repo.resolve()).as_posix()
        except (ValueError, OSError):
            return None, "outside the sandbox"
        match = DETECTOR_PATH.fullmatch(rel) or TEST_PATH.fullmatch(rel)
        if not match:
            return None, f"{rel} is not on the allowlist"
        return match["name"], None

    def _check(self, action) -> tuple[str, str | None, str | None]:
        """(target, name, reason) for one action; reason None means allowed."""
        from droid_sdk.permissions import ApplyPatchAction, CreateFile, EditAction, ExecuteAction, McpToolAction

        if isinstance(action, McpToolAction):
            tool = action.actual_tool_name or action.tool_name.rsplit("__", 1)[-1]
            if action.server_name == LAB_SERVER_NAME and tool in LAB_TOOL_NAMES:
                return tool, None, None
            return action.tool_name, None, "only the sandbox's read tools"
        if isinstance(action, (CreateFile, EditAction, ApplyPatchAction)):
            paths = [action.file_path]
            if isinstance(action, ApplyPatchAction):
                if any(f.operation == "delete" or f.move_to for f in action.files or ()):
                    return action.file_path, None, "a patch may not delete or move files"
                paths += [f.file_path for f in action.files or ()]
            content = getattr(action, "content", None) or getattr(action, "new_content", None) or ""
            if len(content.encode()) > MAX_FILE_BYTES:
                return action.file_path, None, f"files are limited to {MAX_FILE_BYTES} bytes"
            names = set()
            for p in paths:
                name, reason = self._target(p)
                if reason:
                    return p, None, reason
                names.add(name)
            if len(names) != 1 or (self.name and names != {self.name}):
                return action.file_path, None, f"this run's detector is {self.name or sorted(names)[0]}"
            return action.file_path, names.pop(), None
        if isinstance(action, ExecuteAction):  # the shell is off; this is a second line behind disabled_tools
            return (action.full_command or action.command or "")[:200], None, "no shell in the sandbox: use the " \
                "run_tests and run_eval tools"
        return type(action).__name__, None, "not allowed in the sandbox"

    def allow_lab(self, cmd: str, name: str) -> str | None:
        """None when this lab run may go ahead (and counts it), else why not (recorded as a denial)."""
        reason = None
        if self.name is None or name != self.name:
            reason = "write the detector and its test first, then name it"
        elif self.used[cmd] >= BUDGET[cmd]:
            reason = f"the {cmd} budget ({BUDGET[cmd]} runs) is used up"
        if reason:
            tool = next(t for t, c in RUN_TOOLS.items() if c == cmd)
            self.denials.append({"tool": tool, "server": LAB_SERVER_NAME, "target": name[:200], "reason": reason})
        else:
            self.used[cmd] += 1
        return reason

    def decide(self, request) -> tuple[bool, list[str]]:
        checks = [(a, *self._check(a)) for a in request.actions]
        names = {n for _, _, n, r in checks if n and r is None}
        reasons = [r for _, _, _, r in checks if r]
        if len(names) > 1:
            reasons.append("one detector per run")
        allowed = bool(checks) and not reasons
        if allowed:
            if names:
                self.name = self.name or names.pop()
        else:
            for a, target, _, reason in checks or [(None, None, None, "a request naming no action")]:
                tool_use = getattr(a, "tool_use", None)
                self.denials.append({"tool": getattr(tool_use, "name", None) or getattr(a, "tool_name", None)
                                     or (type(a).__name__ if a is not None else None),
                                     "server": getattr(a, "server_name", None),
                                     "target": (target or "")[:200] or None,
                                     "reason": reason or "refused with the rest of its request"})
        return allowed, reasons

    def handle(self, request) -> Any:
        from droid_sdk import PermissionResponse, ToolConfirmationOutcome

        allowed, reasons = self.decide(request)
        return PermissionResponse(
            selected_option=ToolConfirmationOutcome.PROCEED_ONCE if allowed else ToolConfirmationOutcome.CANCEL,
            comment=None if allowed else "Refused by the StormDesk sandbox: " + "; ".join(reasons))


# Before anything leaves the sandbox -------------------------------------------------------------


def secret_values(settings) -> dict[str, str]:
    """Values that must never appear in a proposed file, by name (the values are never stored or shown)."""
    named = {"FACTORY_API_KEY": settings.factory_api_key, "NESSIE_API_KEY": settings.nessie_api_key,
             "CHALK_CLIENT_SECRET": settings.chalk_client_secret, "DATABASE_URL": settings.database_url}
    url = settings.database_url or ""
    if "@" in url and ":" in url.split("@")[0]:
        named["DATABASE_URL password"] = url.split("@")[0].rsplit(":", 1)[-1]
    for key, value in os.environ.items():
        if re.search(r"KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL", key):
            named.setdefault(key, value)
    return {k: v for k, v in named.items() if v and len(v) >= 8}


def secret_hits(texts: list[str], secrets: dict[str, str]) -> list[str]:
    return sorted({name for name, value in secrets.items() for t in texts if value in t})
