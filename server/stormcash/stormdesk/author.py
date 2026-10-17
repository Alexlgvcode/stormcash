"""Droid proposes a new deterministic detector as a pull request (spec §14.7d).

An operator names a gap (a candidate kind StormDesk or the rules get wrong,
e.g. `region_dark`) and points at labelled dev rows. Droid, in a sandbox
(sandbox.py), writes a pure detector module and its test, runs the tests and
our evaluation script (detector_eval.py), and returns a `DetectorProposal`
quoting the script's numbers. Then our deterministic code, not Droid:

1. checks that only the two allowlisted files changed, that the detector is
   pure, and that no secret value is in either file;
2. re-runs the tests and the eval itself, after the session closed, and
   rejects the run if Droid's name, files, test result or any number differs;
3. only then, and only for a Droid run, commits the two files as the repo
   owner and opens a pull request labelled for a person. It never merges.

A proposed detector is never wired into `detectors.run_incremental`; a person
does that in a follow-up PR. No AI in the money path (§0 rule 2).

Every run is a `stormdesk_runs` row with `job = 'author'`, recorded like the
other Droid jobs (model, credits, attempts, permission denials, steps), so the
Droid tab shows it. `STORMDESK_AUTHOR=1` turns the job on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ValidationError

from ..db import one, scalar
from ..jsonutil import jsonable
from . import sandbox
from .detector_eval import KINDS, purity_problems
from .runner import Steps, add_usage, droid_available, session_model

log = logging.getLogger(__name__)

AUTHOR_PROMPT_VERSION = 1
SESSION_TIMEOUT_S = 900
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_EXAMPLES = 10
DEV_ROWS = sandbox.DATA_DIR / "stormdesk_triage.jsonl"

# What each kind's §13 detector already checks, and the keys of its frozen snapshot.
CURRENT_RULE = {
    "merchant_silence": ("silence_ratio < 0.2 and pool_funded_count >= 1 in a 6 h window (§13.1)",
                         "server/stormcash/detectors.py: merchant_silence"),
    "cap_drain": ("distinct_merchants_15m >= 3 and drain_share >= 0.8 in 15 minutes (§13.2)",
                  "server/stormcash/detectors.py: cap_drain_for_payment"),
    "region_dark": ("expiring_12h_share >= 0.3 and hours_since_last_upload >= 48 (§13.3)",
                    "server/stormcash/detectors.py: region_dark"),
}


class Counts(BaseModel):
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float | None
    recall: float | None


class SplitMetrics(BaseModel):
    proposed: Counts
    rules_only: Counts


class DetectorMetrics(BaseModel):
    dev: SplitMetrics
    heldout: SplitMetrics


class DetectorProposal(BaseModel):
    name: str = Field(description="the detector's name, also its file name")
    kind: Literal["merchant_silence", "cap_drain", "region_dark"] = Field(description="the candidate kind it judges")
    rationale: str = Field(description="why this rule closes the gap, at most 6 sentences")
    files_changed: list[str] = Field(description="the two files you wrote, relative to the repository root")
    tests_passed: bool = Field(description="true only if your last run_tests passed")
    metrics: DetectorMetrics = Field(description="the eval script's `metrics` object, copied exactly")
    caveats: list[str] = Field(description="what the labelled data can't show, at most 4")


AUTHOR_PROMPT = f"""You are StormDesk's detector author. StormCash's soft-signal detectors are deterministic code that
raises candidates for review; they never act. You write ONE new deterministic detector that judges candidates of one
kind better than the current rule, prove it on labelled data, and stop. A person reviews your pull request and
decides whether to merge it. Nothing you write runs in production unless they do.

You work in a throwaway git worktree:
- Read it with read_file, list_dir and search. Held-out data and eval results are not available to you.
- Write exactly two files, with Create: server/stormcash/detectors_proposed/<name>.py and
  server/tests/test_proposed_<name>.py, for one <name> matching [a-z][a-z0-9_]{{2,40}}. To change a file, Create it
  again with its full content.
- Run exactly two commands, as tools: run_tests(name) (pytest on your test file) and run_eval(name) (our
  evaluation script). Budget: {sandbox.BUDGET['test']} test runs and {sandbox.BUDGET['eval']} eval runs.
A permission handler refuses everything else, records each refusal, and a refusal ends your turn. There is no
shell, network, database or git.

The detector module must be pure:
    \"\"\"One paragraph: what it raises and why.\"\"\"
    KIND = "<kind>"
    NAME = "<name>"
    def fires(features: dict) -> bool: ...
fires() receives one candidate's frozen feature snapshot (the dict the current detector stored) and returns True to
raise it. Allowed imports: math, statistics, typing, dataclasses, collections. No I/O, print, open, eval or getattr,
no attribute starting with "_", no global state. The eval refuses anything else.

The test file has plain pytest functions on literal feature dicts (no fixtures, no files):
    from stormcash.detectors_proposed.<name> import fires

Rules:
- Prefer a simple rule a person can check, over features the snapshot already has. Never hardcode row ids, subject
  ids or exact values from the examples: held-out towns differ.
- The eval prints JSON. Copy its "metrics" object into your output exactly, digit for digit. Our server re-runs the
  tests and the eval after you finish and rejects any mismatch.
- tests_passed is true only if your last run_tests passed. files_changed lists the two files.
- caveats: what the labelled data can't show (for example, a pattern the simulator plants by construction).
- Be brief. Don't read files you don't need: the prompt has the rows."""


@dataclass
class AuthorJob:
    kind: str
    gap: str
    examples: list[dict] = field(default_factory=list)  # [{row_id, note}] from the dev rows
    operator: str | None = None  # who asked (X-SC-Operator)


def dev_rows(kind: str | None = None) -> dict[str, dict]:
    """The labelled dev rows (Droid may see them), by row id. Never the held-out file."""
    rows = {}
    for line in DEV_ROWS.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if isinstance(r["features"], str):
                r["features"] = json.loads(r["features"])
            if kind is None or r["kind"] == kind:
                rows[r["row_id"]] = r
    return rows


class AuthorError(ValueError):
    status = 400


def make_job(gap: str, examples: list | None, operator: str | None = None) -> AuthorJob:
    """Check the request. `gap` is a candidate kind, or a description naming one."""
    gap = (gap or "").strip()
    kinds = [k for k in KINDS if k in gap]
    if not kinds:
        raise AuthorError(f"name the candidate kind the detector judges ({', '.join(KINDS)}) in `gap`")
    kind = kinds[0]
    rows = dev_rows()
    picked = []
    for ex in (examples or [])[:MAX_EXAMPLES]:
        row_id, note = (ex, None) if isinstance(ex, str) else (ex.get("row_id"), ex.get("note"))
        if row_id not in rows:
            raise AuthorError(f"example {row_id!r} is not a dev row (held-out rows are never shown to Droid)")
        if rows[row_id]["kind"] != kind:
            raise AuthorError(f"example {row_id} is a {rows[row_id]['kind']} candidate, not {kind}")
        picked.append({"row_id": row_id, "note": (note or "")[:200] or None})
    return AuthorJob(kind, gap if gap != kind else f"StormDesk and the rules get {kind} candidates wrong", picked,
                     operator)


def author_prompt(job: AuthorJob) -> str:
    rule, where = CURRENT_RULE[job.kind]
    rows = dev_rows(job.kind)
    keys = sorted({k for r in rows.values() for k in r["features"]})
    lines = [f"Gap: {job.gap}", f"Kind: {job.kind}",
             f"Current rule ({where}): it raises a candidate when {rule}. The rules-only baseline flags every "
             "candidate it raises with the default action, honest traps included.",
             f"Snapshot keys for {job.kind}: {', '.join(keys)}.", "",
             "Labelled dev rows of this kind (chalk/evals/dataset/stormdesk_triage.jsonl). "
             f"label_kind {job.kind} = real, none = honest trap:"]
    for r in rows.values():
        lines.append(f"- {r['row_id']} · {r['label_scenario']} · label_kind {r['label_kind']} · "
                     f"{json.dumps(r['features'], sort_keys=True)}")
    if job.examples:
        lines += ["", "Rows the operator pointed at:"]
        lines += [f"- {e['row_id']}" + (f": {e['note']}" if e["note"] else "") for e in job.examples]
    lines += ["", "Write the detector and its test with Create, call run_tests, then run_eval, fix and repeat within "
              "the budget if needed, then reply with the DetectorProposal."]
    return "\n".join(lines)


# The Droid session ---------------------------------------------------------------------------


@dataclass
class AuthorOutcome:
    runner: str
    output: DetectorProposal | None
    session_id: str | None = None
    error: str | None = None
    usage: dict | None = None
    model: str | None = None
    model_requested: str | None = None
    attempts: list[dict] = field(default_factory=list)
    permission_denials: list[dict] = field(default_factory=list)
    stopped_at_credit_cap: bool = False
    tools_enabled: list[str] | None = None


class DroidAuthor:
    name = "droid"

    def __init__(self, deps) -> None:
        self.deps = deps
        self.model = deps.settings.stormdesk_model or DEFAULT_MODEL
        self.api_key = deps.settings.factory_api_key or None
        self.max_credits = deps.settings.stormdesk_author_max_credits

    async def run(self, job: AuthorJob, prompt: str, box: sandbox.Sandbox, guard: sandbox.AuthorGuard,
                  steps: Steps, lab_runs: list) -> AuthorOutcome:
        from droid_sdk import Autonomy, InteractionHandlers, Runtime, Session, SessionConfig

        runtime = Runtime(executable=str(box.droid_executable))
        # Which built-ins this CLI has for this model (no inference, no credits): all but the write tools go off.
        async with Session(cwd=box.repo, model=self.model, runtime=runtime, api_key=self.api_key) as probe:
            builtin = {t.id for t in await probe.list_tools(model=self.model)}
        config = SessionConfig(system_prompt=AUTHOR_PROMPT, autonomy=Autonomy.OFF, disable_builtin_skills=True,
                               mcp_servers=[sandbox.lab_mcp_server(sandbox.LabFiles(box.repo), box, guard, lab_runs)],
                               # Create and Edit are off by default in SDK sessions: switched on, and gated.
                               enabled_tools=builtin & sandbox.WRITE_TOOLS, disabled_tools=builtin - sandbox.WRITE_TOOLS)
        out = AuthorOutcome(self.name, None, model_requested=self.model, permission_denials=guard.denials,
                            tools_enabled=sorted(builtin & sandbox.WRITE_TOOLS))
        handlers = InteractionHandlers(on_permission=guard.handle)
        try:
            return await self._session(prompt, box, guard, steps, lab_runs, config, handlers, runtime, out)
        finally:  # the CLI's own record of the session is the credit figure; the SDK's sum is kept beside it
            recorded = session_file_credits(out.session_id)
            if recorded is not None:
                out.usage = dict(out.usage or {})
                out.usage["factory_credits_sdk"] = out.usage.get("factory_credits")
                out.usage["factory_credits"] = recorded

    async def _session(self, prompt, box, guard, steps, lab_runs, config, handlers, runtime, out) -> AuthorOutcome:
        from droid_sdk import Session, TokenUsageUpdate, ToolCall, ToolResult

        live_credits = 0.0
        async with Session(cwd=box.repo, model=self.model, config=config, interactions=handlers, runtime=runtime,
                           api_key=self.api_key) as s:
            text, seen_denials = prompt, 0
            # A refused action ends Droid's turn ("cancelled by user"), and an output can be missing or invalid:
            # up to two follow-up turns in the same session say what happened.
            for attempt in (1, 2, 3):
                stream = s.stream(text, output=DetectorProposal, timeout=SESSION_TIMEOUT_S)
                async for event in stream:
                    if isinstance(event, ToolCall):
                        steps.call(event.name.rsplit("__", 1)[-1], dict(event.input or {}), event.tool_use_id)
                    elif isinstance(event, ToolResult):
                        steps.result(event.tool_use_id, not event.is_error)
                    elif isinstance(event, TokenUsageUpdate) and event.factory_credits is not None:
                        live_credits = max(live_credits, event.factory_credits)
                        if live_credits + (out.usage or {}).get("factory_credits", 0) >= self.max_credits:
                            out.stopped_at_credit_cap = True
                            await stream.aclose()  # interrupts the session: the cap is hard
                            break
                out.model = session_model(s) or out.model
                result = stream.result if stream.completed else None
                if result is not None:
                    out.session_id = result.session_id
                    out.usage = add_usage(out.usage, result.usage)
                if out.stopped_at_credit_cap:
                    out.usage = dict(out.usage or {})
                    out.usage["factory_credits"] = max(out.usage.get("factory_credits") or 0, live_credits)
                    out.error = f"stopped at the credit cap ({self.max_credits:,} Factory credits)"
                    out.attempts.append({"attempt": attempt, "ok": False, "error": out.error})
                    return out
                error = None
                if result is not None and result.success and result.structured_output is not None:
                    try:
                        out.output = DetectorProposal.model_validate(_thaw(result.structured_output))
                        out.attempts.append({"attempt": attempt, "ok": True, "error": None})
                        return out
                    except ValidationError as exc:
                        error = f"output did not match DetectorProposal: {exc.error_count()} errors"
                elif result is not None and result.subtype == "error_during_execution":
                    message = getattr(result.error, "message", None) or result.text or "no output"
                    out.error = f"error_during_execution: {message}"
                    out.attempts.append({"attempt": attempt, "ok": False, "error": out.error})
                    return out
                else:
                    error = f"{getattr(result, 'subtype', 'no result')}: " \
                            f"{getattr(result, 'structured_output_error', None) or 'no output'}"
                refused = guard.denials[seen_denials:]
                seen_denials = len(guard.denials)
                if refused:
                    error = f"the sandbox refused {len(refused)} action(s); {error}"
                out.error = error
                out.attempts.append({"attempt": attempt, "ok": False, "error": error})
                if refused:
                    text = ("The sandbox refused: " + "; ".join(f"{d['tool']} {d['target'] or ''}: {d['reason']}"
                                                                for d in refused[-3:])
                            + ". That ended your turn. Continue within the rules (only the two allowlisted files, "
                              "run_tests and run_eval), then reply with the DetectorProposal.")
                else:
                    text = (f"Your structured output was missing or invalid ({error}). Reply now with the "
                            "DetectorProposal only, with the metrics copied exactly from your last run_eval.")
        return out


def session_file_credits(session_id: str | None) -> float | None:
    """The credits Droid's CLI recorded for the session (~/.factory/sessions/*/<id>.settings.json, the same
    record the eval gateway audits), or None when it can't be read."""
    if not session_id:
        return None
    for path in (Path.home() / ".factory" / "sessions").glob(f"*/{session_id}.settings.json"):
        try:
            return (json.loads(path.read_text()).get("tokenUsage") or {}).get("factoryCredits")
        except (OSError, ValueError):
            return None
    return None


def _thaw(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


# After the session: our own checks and re-run ------------------------------------------------


def _diff(claimed, actual, path: str = "") -> list[str]:
    if isinstance(actual, dict) and isinstance(claimed, dict):
        return [d for k in sorted(set(actual) | set(claimed))
                for d in _diff(claimed.get(k), actual.get(k), f"{path}.{k}" if path else k)]
    return [] if claimed == actual else [f"{path}: Droid said {claimed!r}, the re-run says {actual!r}"]


async def verify(deps, job: AuthorJob, box: sandbox.Sandbox, guard: sandbox.AuthorGuard,
                 proposal: DetectorProposal | None) -> dict:
    """Deterministic checks after Droid's session closed. `ok` only when every one passes."""
    checks: list[dict] = []

    def check(key: str, ok: bool, detail: str) -> bool:
        checks.append({"check": key, "ok": bool(ok), "detail": detail})
        return bool(ok)

    name = guard.name
    expected = sorted(str(p.relative_to(box.repo)) for p in (box.detector_file(name), box.test_file(name))) \
        if name else []
    changed = box.changed_files()
    files: dict[str, str] = {}
    if not check("files", bool(name) and changed == expected and all((box.repo / p).is_file() for p in expected),
                 f"changed: {changed or 'nothing'}" + ("" if changed == expected else f"; allowed: {expected}")):
        return {"ok": False, "checks": checks, "files": files, "name": name}
    files = {p: (box.repo / p).read_text() for p in expected}
    source = files[str(box.detector_file(name).relative_to(box.repo))]
    problems = purity_problems(source, name)
    check("pure_detector", not problems, "; ".join(problems) or "no I/O, imports or dunder access")
    hits = sandbox.secret_hits(list(files.values()), sandbox.secret_values(deps.settings))
    check("no_secrets", not hits, f"found the value of {', '.join(hits)}" if hits else "no secret values")
    tests = await box.run_lab("test", name)
    tests_ok = tests["exit_code"] == 0
    check("tests_rerun", tests_ok, f"pytest exit {tests['exit_code']}: {tests['output'].strip()[-160:]}")
    evaluated = await box.run_lab("eval", name)
    report = None
    try:
        report = json.loads(evaluated["output"])
    except json.JSONDecodeError:
        pass
    if not check("eval_rerun", evaluated["exit_code"] == 0 and report and "metrics" in report,
                 (report or {}).get("error") or f"eval exit {evaluated['exit_code']}"):
        report = None
    if proposal is None:
        check("claims_match", False, "Droid returned no DetectorProposal")
    else:
        diffs = [] if proposal.name == name else [f"name: Droid said {proposal.name!r}, the files say {name!r}"]
        if proposal.kind != job.kind:
            diffs.append(f"kind: Droid said {proposal.kind}, the gap is {job.kind}")
        if report and report["detector"]["kind"] != job.kind:
            diffs.append(f"KIND: the module says {report['detector']['kind']}, the gap is {job.kind}")
        if sorted(proposal.files_changed) != expected:
            diffs.append(f"files_changed: Droid said {sorted(proposal.files_changed)}, git says {expected}")
        if proposal.tests_passed != tests_ok:
            diffs.append(f"tests_passed: Droid said {proposal.tests_passed}, the re-run says {tests_ok}")
        if report:
            diffs += _diff(proposal.metrics.model_dump(), report["metrics"], "metrics")
        check("claims_match", not diffs, "; ".join(diffs[:6]) or "name, files, test result and every number match")
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "files": files, "name": name,
            "tests": {"exit_code": tests["exit_code"], "output_tail": tests["output"][-1500:]},
            "eval": report}


# The hand-off: our code commits and opens the PR --------------------------------------------


def _run(cwd: Path, *argv: str, timeout: float = 90) -> str:
    out = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"{argv[0]} {argv[1]} failed: {(out.stderr or out.stdout).strip()[:300]}")
    return out.stdout.strip()


PR_LABEL = "droid-proposal"


def pr_body(job: AuthorJob, proposal: DetectorProposal, run: dict, verified: dict) -> str:
    report = verified["eval"]
    m, data = report["metrics"], report["data"]

    def cell(c: dict) -> str:
        p = "n/a" if c["precision"] is None else f"{c['precision']:.2f}"
        r = "n/a" if c["recall"] is None else f"{c['recall']:.2f}"
        return f"{p} | {r} | {c['tp']} / {c['fp']} / {c['fn']} / {c['tn']}"

    usage = run.get("usage") or {}
    credits = usage.get("factory_credits")
    lines = [
        "Droid wrote this detector in a sandbox for the gap below. Our server re-ran the tests and the evaluation "
        "after Droid finished, and every number matched. **A person decides whether to merge it.** It adds a "
        "module and its test only: nothing calls it until a follow-up PR wires it into `detectors.run_incremental`.",
        "", f"**Gap:** {job.gap}", f"**Kind:** `{job.kind}` (the current rule is spec §13)", "",
        "## Why (Droid's rationale)", "", proposal.rationale, "",
        "## Measured on labelled simulator data (our re-run)", "",
        "Rows are the Chalk eval datasets' candidates of this kind (spec §15.3). Droid saw the dev rows; it never "
        "saw a held-out row, only the eval's aggregate counts.", "",
        "| Split | Detector | Precision | Recall | TP / FP / FN / TN |", "|---|---|---|---|---|"]
    for split, label in (("dev", "Dev"), ("heldout", "Held-out")):
        d = data[split]
        where = f"{label}: seeds {', '.join(map(str, d['seeds']))}, {d['rows']} rows ({d['positives']} real)"
        lines.append(f"| {where} | `{proposal.name}` | {cell(m[split]['proposed'])} |")
        lines.append(f"| | rules only (§13 detector alone) | {cell(m[split]['rules_only'])} |")
    lines += ["", f"Evaluator `{report['evaluator']}`, detector sha256 `{report['detector']['sha256'][:12]}`, dev data "
              f"sha256 `{data['dev']['sha256'][:12]}`, held-out data sha256 `{data['heldout']['sha256'][:12]}`.", "",
              "## Caveats (Droid's)", ""] + [f"- {c}" for c in proposal.caveats or ["none given"]] + [
        "", "## How it was made", "",
        f"- StormDesk author run #{run['run_id']} (Droid tab), session `{run.get('session_id')}`, model "
        f"`{run.get('model')}` (asked for `{run.get('model_requested')}`), "
        + (f"{round(credits):,} Factory credits" if credits is not None else "credits not recorded")
        + f", {run.get('tool_calls', 0)} tool calls, {len(run.get('permission_denials') or [])} permission denials.",
        f"- Sandbox: a throwaway worktree of `{run['sandbox']['base_ref']}` at `{run['sandbox']['base_sha'][:12]}`, "
        "with no `.env`. Droid could write only these two files, run only the tests and the eval (its shell was "
        "off), and read only the worktree (no held-out data). Its CLI ran under a macOS sandbox profile; the tests "
        "and eval ran in a second one with no network.",
        "- Our checks: " + "; ".join(f"{c['check']} ✓" for c in verified["checks"]) + ".",
        "- Committed and opened by StormCash's hand-off code as the repo owner. Droid has no git access.", "",
        "## Before merging", "",
        "- [ ] Is the rule sensible outside the simulator?",
        "- [ ] Wiring it into `detectors.run_incremental` is a separate PR."]
    return "\n".join(lines)


def open_pr(box: sandbox.Sandbox, job: AuthorJob, proposal: DetectorProposal, run: dict, verified: dict) -> dict:
    """Commit the two files as the repo owner, push a branch, open a PR labelled for a person. Never merges."""
    name = verified["name"]
    branch = f"droid/detector-{name.replace('_', '-')}-run{run['run_id']}"
    owner = _run(box.repo_root, "git", "config", "user.name")
    email = _run(box.repo_root, "git", "config", "user.email")
    title = f"Detector proposed by Droid: {name}"
    files = sorted(verified["files"])
    # Committed on the worktree's detached HEAD and pushed by ref, so no local branch is left in the checkout.
    _run(box.repo, "git", "add", "--", *files)
    _run(box.repo, "git", "-c", f"user.name={owner}", "-c", f"user.email={email}", "commit", "-q", "-m", title,
         "-m", f"Written by Droid in StormDesk author run #{run['run_id']} (spec §14.7d); tests and evaluation "
               "re-run by the server. Not wired into detectors.run_incremental.")
    commit = _run(box.repo, "git", "rev-parse", "HEAD")
    _run(box.repo, "git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}", timeout=120)
    try:  # the label may exist already
        _run(box.repo, "gh", "label", "create", PR_LABEL, "--color", "7c3aed",
             "--description", "Written by Droid in a sandbox: a person reviews it and decides")
    except RuntimeError:
        pass
    base = box.base_ref.split("/", 1)[1] if box.base_ref.startswith("origin/") else box.base_ref
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(pr_body(job, proposal, run, verified))
    url = _run(box.repo, "gh", "pr", "create", "--base", base, "--head", branch, "--title", title,
               "--body-file", f.name, "--label", PR_LABEL, timeout=120).splitlines()[-1]
    Path(f.name).unlink(missing_ok=True)
    return {"url": url, "number": int(url.rstrip("/").rsplit("/", 1)[-1]) if url.rstrip("/")[-1:].isdigit() else None,
            "branch": branch, "commit": commit, "base": base, "title": title, "label": PR_LABEL}


# The service ---------------------------------------------------------------------------------


def status(deps) -> dict:
    """Whether the job can run here, and why not."""
    s = deps.settings
    reasons = []
    if not s.stormdesk_author:
        reasons.append("STORMDESK_AUTHOR is off")
    # As make_runner: STORMDESK_RUNNER=droid uses the droid CLI's own login; auto needs FACTORY_API_KEY too.
    if s.stormdesk_runner == "fake":
        reasons.append("STORMDESK_RUNNER=fake: the author job needs Droid")
    elif not (droid_available(deps) or (s.stormdesk_runner == "droid" and shutil.which("droid"))):
        reasons.append("Droid isn't available (droid-sdk, the droid CLI, and FACTORY_API_KEY or STORMDESK_RUNNER=droid)")
    if sandbox.sandbox_exec() is None:
        reasons.append("no OS sandbox on this machine (macOS sandbox-exec)")
    return {"enabled": not reasons, "reasons": reasons, "max_credits": s.stormdesk_author_max_credits,
            "base_ref": s.stormdesk_author_base, "model": s.stormdesk_model or DEFAULT_MODEL,
            "prompt_version": AUTHOR_PROMPT_VERSION, "budget": sandbox.BUDGET}


class Author:
    """One author run at a time. `runner`, `make_sandbox` and `open_pr` are swappable for tests."""

    def __init__(self, deps, runner=None, make_sandbox=None, pr=open_pr) -> None:
        self.deps = deps
        self.runner = runner
        self.make_sandbox = make_sandbox or (lambda: sandbox.create(deps.settings.stormdesk_author_base))
        self.open_pr = pr
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    def start(self, job: AuthorJob, check_enabled: bool = True) -> dict:
        """Store the run and start it in the background; returns {run_id, subject}."""
        if check_enabled:
            state = status(self.deps)
            if not state["enabled"]:
                raise AuthorError("the author job can't run here: " + "; ".join(state["reasons"]))
        if self.lock.locked():
            raise AuthorError("an author run is already in progress")
        with self.deps.pool.connection() as conn:
            run_id = scalar(conn, """INSERT INTO stormdesk_runs (job, runner, status, transcript)
                                     VALUES ('author', %s, 'running', %s) RETURNING run_id""",
                            (getattr(self.runner, "name", "droid"),
                             Jsonb({"gap": job.gap, "kind": job.kind, "examples": job.examples,
                                    "operator": job.operator})))
        task = asyncio.get_running_loop().create_task(self.run(job, run_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {"run_id": run_id, "subject": subject(run_id), "status": "running", "kind": job.kind}

    def _event(self, run_id: int, phase: str, **extra) -> None:
        self.deps.events.publish("author", {"run_id": run_id, "phase": phase, **extra})

    async def run(self, job: AuthorJob, run_id: int) -> dict:
        async with self.lock:
            return await self._run(job, run_id)

    async def _run(self, job: AuthorJob, run_id: int) -> dict:
        runner = self.runner or DroidAuthor(self.deps)
        name = subject(run_id)

        def on_step(step: dict) -> None:
            self.deps.events.publish("stormdesk_step", {
                "run_id": run_id, "job": "author", "subject": name, "runner": runner.name, "index": step["index"],
                "tool": step["tool"], "input_summary": step["input_summary"], "ok": step["ok"]})

        steps = Steps(on_step=on_step)
        started = time.monotonic()
        outcome, verified, pr, box, guard = None, None, None, None, None
        transcript = {"runner": runner.name, "gap": job.gap, "kind": job.kind, "examples": job.examples,
                      "operator": job.operator,
                      "prompt_version": AUTHOR_PROMPT_VERSION if runner.name == "droid" else None,
                      "credit_cap": getattr(runner, "max_credits", None)}
        try:
            self._event(run_id, "sandbox")
            box = await asyncio.to_thread(self.make_sandbox)
            transcript["sandbox"] = {"base_ref": box.base_ref, "base_sha": box.base_sha,
                                     "os_sandbox": box.os_sandbox}
            guard = sandbox.AuthorGuard(box.repo)
            self._event(run_id, "droid")
            transcript["lab_runs"] = lab_runs = []
            try:
                outcome = await runner.run(job, author_prompt(job), box, guard, steps, lab_runs)
            except Exception as exc:  # Droid unreachable, CLI failed: a failed run, stored like any other
                log.exception("author run %s failed", run_id)
                outcome = AuthorOutcome(runner.name, None, error=f"{type(exc).__name__}: {exc}",
                                        permission_denials=guard.denials)
            self._event(run_id, "verify")
            verified = await verify(self.deps, job, box, guard, outcome.output)
            if verified["ok"] and runner.name == "droid":
                self._event(run_id, "pull_request")
                info = self._summary(run_id, outcome, steps, transcript)
                try:
                    pr = await asyncio.to_thread(self.open_pr, box, job, outcome.output, info, verified)
                except Exception as exc:
                    pr = {"error": f"{type(exc).__name__}: {exc}"[:400]}
            elif verified["ok"]:
                pr = {"skipped": f"{runner.name} runner: a pull request is only opened for a Droid run"}
        except Exception as exc:
            log.exception("author run %s failed before Droid finished", run_id)
            outcome = outcome or AuthorOutcome(runner.name, None, error=f"{type(exc).__name__}: {exc}",
                                               permission_denials=guard.denials if guard else [])
        finally:
            if box is not None:
                await asyncio.to_thread(box.remove)
        result = await asyncio.to_thread(self._store, run_id, outcome, steps, transcript, verified, pr,
                                         round(time.monotonic() - started, 1))
        self.deps.events.publish("stormdesk_step", {"run_id": run_id, "job": "author", "subject": name,
                                                    "runner": runner.name, "done": True, "status": result["status"]})
        self._event(run_id, "done", status=result["status"], pr=pr)
        return result

    def _summary(self, run_id: int, outcome: AuthorOutcome, steps: Steps, transcript: dict) -> dict:
        return {"run_id": run_id, "session_id": outcome.session_id, "model": outcome.model,
                "model_requested": outcome.model_requested, "usage": outcome.usage,
                "tool_calls": len(steps.transcript), "permission_denials": outcome.permission_denials,
                "sandbox": transcript["sandbox"]}

    def _store(self, run_id: int, outcome: AuthorOutcome, steps: Steps, transcript: dict, verified: dict | None,
               pr: dict | None, duration_s: float) -> dict:
        output = outcome.output if outcome else None
        ok = bool(verified and verified["ok"])
        status_ = "succeeded" if output is not None and ok else "invalid" if output is not None else "failed"
        transcript |= {"steps": steps.transcript, "error": outcome.error if outcome else None, "duration_s": duration_s,
                       "model": outcome.model, "model_requested": outcome.model_requested, "usage": outcome.usage,
                       "missing_citations": [], "fallback_from_droid": None,
                       "stopped_at_credit_cap": outcome.stopped_at_credit_cap, "tools_enabled": outcome.tools_enabled,
                       "verified": verified, "pull_request": pr}
        if outcome.runner == "droid":
            transcript["attempts"] = outcome.attempts
            transcript["permission_denials"] = outcome.permission_denials
        error = outcome.error if output is None else None if ok else \
            "re-run rejected the proposal: " + "; ".join(c["detail"] for c in verified["checks"] if not c["ok"])[:300] \
            if verified else "not verified"
        with self.deps.pool.connection() as conn:
            row = one(conn, """UPDATE stormdesk_runs SET runner = %s, status = %s, output = %s, transcript = %s,
                                      session_id = %s, error = %s, finished_at = now() WHERE run_id = %s RETURNING *""",
                      (outcome.runner, status_, Jsonb(output.model_dump() if output else None), Jsonb(jsonable(transcript)),
                       outcome.session_id, error, run_id))
        return jsonable(row)


def subject(run_id: int) -> str:
    return f"author run #{run_id}"
