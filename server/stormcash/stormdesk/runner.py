"""Who answers a StormDesk job (spec §14.2).

- DroidRunner: the real agent, Factory's Droid SDK. Our 11 read-only tools are
  an in-process MCP server; a permission handler refuses everything that isn't
  one of them; the result is structured output, retried once on failure.
- FakeRunner: deterministic, for tests and for running without Factory access.
  It calls the same tools and applies the rules-only baseline (flag every
  candidate with its default action, §13). Its output always says "fake
  runner" and its session id starts with "fake-", so it is never presented as
  an agent's judgement (§0 rule 3). As the reviewer (§14.7b) it compares the
  proposal with that baseline and says "Fake reviewer".

STORMDESK_RUNNER=droid|fake|auto picks one; auto uses Droid only when the SDK,
the `droid` CLI and FACTORY_API_KEY are all present (`droid` also works with a
logged-in CLI and no key). When Droid can't run at all (e.g. no credits),
service.py answers with the fake runner, skips Droid for a cool-down, and records why.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from . import tools
from .citations import normalize
from .prompt import REVIEW_PROMPT, STORMDESK_PROMPT
from .schemas import AppealReply, CaseFile, Flag, Review

log = logging.getLogger(__name__)

MCP_SERVER_NAME = "stormdesk"
RUN_TIMEOUT_S = 180
# Every built-in Droid tool, switched off: StormDesk may only use its own read-only tools.
# Verified on Oct 16 with Session.list_tools() against droid CLI 0.244.0 (§14.2);
# the permission handler refuses them regardless.
BUILTIN_TOOLS = frozenset({
    "ApplyPatch", "AskUser", "ConnectApp", "CreateAutomation", "DeleteAutomation", "DismissHandoffItems",
    "EditAutomation", "EndFeatureRun", "Execute", "ExitSpecMode", "FetchUrl", "GenerateDroid", "GenerateImage",
    "Glob", "Grep", "LS", "ListAutomationTemplates", "ListAutomations", "Loop", "ProposeMission", "Read",
    "ReadAutomation", "RunAutomation", "Script", "Skill", "StageSettingsChanges", "StartMissionRun", "Task",
    "TaskOutput", "TaskStop", "TodoWrite", "ToolSearch", "WaitForScript", "WebSearch",
})
DEFAULT_ACTIONS = {"merchant_silence": "hold_pool_payout", "cap_drain": "freeze_cert", "region_dark": "dispatch_relay"}
# What the fake runner reads back from query_features for each candidate kind: (entity, Chalk features to quote).
FEATURE_CHECK = {
    "merchant_silence": ("merchant", ("silence_ratio_6h", "pool_funded_cents_6h")),
    "cap_drain": ("cert", ("drain_share_15m", "distinct_merchants_15m")),
    "region_dark": ("region", ("hours_since_last_upload", "expiring_12h_share")),
}


@dataclass
class Job:
    kind: Literal["investigate", "triage", "respond", "review"]
    case_id: int | None = None
    candidate_id: int | None = None
    merchant_id: str | None = None
    message: str | None = None
    # review (§14.7b): StormDesk's Flag output under review, and where it came from.
    proposal: dict | None = None
    flag_id: int | None = None  # the stored flag the review is for (None: a proposal passed in, e.g. by an eval)
    reviewed_run_id: int | None = None
    # respond (§17.2): the appeal thread. {"mode": "session" | "per_message", "flag_id", "in_message_id"}; in
    # session mode service.py adds the Droid session to resume ("resume_session_id", "turn") and the prompt
    # seeded with the stored thread ("restart_prompt", "seeded_messages") for when it can't be resumed.
    appeal: dict | None = None

    @property
    def output_model(self) -> type[BaseModel]:
        return {"investigate": CaseFile, "triage": Flag, "respond": AppealReply, "review": Review}[self.kind]

    @property
    def system_prompt(self) -> str:
        return REVIEW_PROMPT if self.kind == "review" else STORMDESK_PROMPT


@dataclass
class RunOutcome:
    runner: str
    output: BaseModel | None
    session_id: str | None = None
    error: str | None = None
    unavailable: bool = False  # the runner couldn't run at all (no credits, no CLI): try another
    usage: dict | None = None  # Droid only: tokens and Factory credits, summed over attempts
    model: str | None = None  # the model the session actually ran on (Factory can switch it, e.g. to Droid Core)
    model_requested: str | None = None
    attempts: list[dict] | None = None  # Droid only: one {attempt, ok, error} per session (structured-output retry)
    permission_denials: list[dict] | None = None  # Droid only: what the permission handler refused ([] when nothing)
    appeal: dict | None = None  # an appeal turn in session mode: how its Droid session was opened, and its turn


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens", "thinking_tokens",
                "factory_credits")


def add_usage(total: dict | None, usage) -> dict | None:
    """Sum a droid_sdk Usage into a plain dict (what the run cost, kept with its transcript)."""
    if usage is None:
        return total
    total = dict(total or {})
    for name in USAGE_FIELDS:
        value = getattr(usage, name, None)
        if value is not None:
            total[name] = (total.get(name) or 0) + value
    return total


@dataclass
class Steps:
    """Collects tool calls into the transcript and reports each one live."""

    on_step: Callable[[dict], None] = lambda step: None
    transcript: list[dict] = field(default_factory=list)

    def call(self, tool: str, args: dict, call_id: str | None = None) -> dict:
        step = {"index": len(self.transcript), "tool": tool, "input": args, "call_id": call_id,
                "input_summary": json.dumps(args, separators=(",", ":"))[:200], "ok": None}
        self.transcript.append(step)
        self.on_step(step)
        return step

    def result(self, call_id: str | None, ok: bool, step: dict | None = None) -> None:
        step = step or next((s for s in reversed(self.transcript) if s["call_id"] == call_id), None)
        if step is not None:
            step["ok"] = ok
            self.on_step(step)


# Fake runner --------------------------------------------------------------------------------


class FakeRunner:
    name = "fake"

    def __init__(self, deps) -> None:
        self.deps = deps

    async def _tool(self, steps: Steps, name: str, **args) -> dict:
        step = steps.call(name, args)
        try:
            out = await asyncio.to_thread(tools.call, self.deps, name, args)
        except tools.ToolError as exc:
            steps.result(None, False, step)
            return {"error": str(exc)}
        steps.result(None, True, step)
        return out

    async def run(self, job: Job, prompt: str, steps: Steps) -> RunOutcome:
        session = f"fake-{uuid.uuid4().hex[:12]}"
        if job.kind == "investigate":
            return RunOutcome(self.name, await self._investigate(job, steps), session)
        if job.kind == "triage":
            return RunOutcome(self.name, await self._triage(job, steps), session)
        if job.kind == "review":
            return RunOutcome(self.name, await self._review(job, steps), session)
        return RunOutcome(self.name, AppealReply(
            reply="Fake runner: your message was received; a person will review it.",
            claim_consistent_with_logs=False, evidence_ids=[], escalate=True), session)

    async def _investigate(self, job: Job, steps: Steps) -> CaseFile:
        case = await self._tool(steps, "get_case", case_id=job.case_id)
        rule = case["rule"]
        hashes = [h for h in (case.get("tag_a"), case.get("tag_b")) if h]
        evidence = list(hashes)
        broken: set[str] = set()
        sigs_ok = True
        if hashes:
            check = await self._tool(steps, "verify_tags", tag_hashes=hashes)
            sigs_ok = all(t.get("signature_valid") for t in check["tags"])
            broken = {r for p in check["pairs"] for r in p["rules_broken"]}
        who_paid, chain = [], {}
        if case.get("cert_id"):
            chain = await self._tool(steps, "get_cert_chain", cert_id=case["cert_id"])
            for t in chain.get("tags", []):
                if t["tag_hash"] in hashes and t["payment_status"]:
                    who_paid += [{"merchant": t["merchant"], "amount_cents": c, "source": src}
                                 for src, c in (("escrow", t["funded_escrow_cents"]), ("pool", t["funded_pool_cents"]))
                                 if c]
        log_ok = True
        if rule in ("MERCHANT_KNEW", "LOG_TAMPER") and case.get("device_pub"):
            logs = await self._tool(steps, "get_device_log", device_id=case["device_pub"])
            log_ok = logs.get("chain") == "intact"
            if rule == "MERCHANT_KNEW":
                evidence += [e["entry_hash"] for e in logs.get("entries", [])
                             if e["kind"] == "ACCEPT" and e["tag_hash"] == case.get("tag_b")
                             and case.get("tag_a") in e.get("held_ids", [])]
            else:
                evidence += list(case["evidence"].get("entries", []))
        verified = {
            "MERCHANT_KNEW": sigs_ok and bool(broken) and len(evidence) > len(hashes),
            "LOG_TAMPER": not log_ok,
            "OVER_CAP": sigs_ok and any(t["tag_hash"] in hashes and t["cum_cents"] > chain.get("max_cap_cents", 0)
                                        for t in chain.get("tags", [])),
        }.get(rule, sigs_ok and rule in broken)
        plan = {
            "MERCHANT_KNEW": ["Keep the shop's pool payouts suspended", "Ask the shop to explain its ACCEPT entry"],
            "LOG_TAMPER": ["Keep the device's pool payouts suspended pending review"],
        }.get(rule, ["Certificate is frozen by the hard rule", "Book the pool payout as owed by the cheater"])
        lines = [f"**Fake runner (no Droid): rules-only case file for #{case['case_id']}.**", "",
                 f"- Rule: {rule} (re-verified: {'yes' if verified else 'no'})",
                 f"- Exposure: ${case['exposure_cents'] / 100:.2f}"]
        lines += [f"- Paid {w['merchant']} ${w['amount_cents'] / 100:.2f} from {w['source']}" for w in who_paid]
        return CaseFile(rule=rule, verified_independently=verified, who_paid=who_paid,
                        exposure_cents=case["exposure_cents"], recovery_plan=plan, evidence_ids=evidence,
                        summary_md="\n".join(lines))

    async def _triage(self, job: Job, steps: Steps) -> Flag:
        cand = await self._tool(steps, "get_candidate", candidate_id=job.candidate_id)
        kind, subject, f = cand["kind"], cand["subject_id"], cand["features"]
        entity, quoted = FEATURE_CHECK[kind]
        # The same window the detector used, recomputed now (Chalk) or read back from the candidate (fallback).
        current = await self._tool(steps, "query_features", entity=entity, id=subject, as_of=cand["window_end"])
        evidence: list[str] = []
        exposure = 0
        if kind == "merchant_silence":
            pays = await self._tool(steps, "get_merchant_payments", merchant_id=subject,
                                    since=cand["window_start"], until=cand["window_end"])
            pool = [p for p in pays.get("payments", []) if p["funded_pool_cents"] > 0]
            evidence, exposure = [p["tag_hash"] for p in pool], sum(p["funded_pool_cents"] for p in pool)
            summary = (f"Fake runner: {cand.get('subject_name') or 'shop'} logged {f['contacts_per_hour']} contacts/h "
                       f"vs {f['neighbor_median_contacts_per_hour']} nearby while taking "
                       f"${f['pool_funded_cents'] / 100:.2f} of pool money.")
        elif kind == "cap_drain":
            chain = await self._tool(steps, "get_cert_chain", cert_id=subject)
            window = [t for t in chain.get("tags", [])
                      if t["device_ts"] and cand["window_start"] <= t["device_ts"] <= cand["window_end"]]
            evidence, exposure = [t["tag_hash"] for t in window], f["spent_15m_cents"]
            summary = (f"Fake runner: {f['distinct_merchants_15m']} shops took {round(f['drain_share'] * 100)}% of "
                       f"the cap in 15 minutes.")
        else:
            region = await self._tool(steps, "get_region_status", region_id=subject)
            evidence = [a["alert_id"] for a in region.get("alerts", [])] or region.get("sample_cert_ids", [])
            summary = (f"Fake runner: no uploads from {subject} for {f['hours_since_last_upload']} h with "
                       f"{round(f['expiring_12h_share'] * 100)}% of certificates expiring.")
        reasoning = ["- Rules-only baseline: every candidate gets its default action.",
                     "- No agent judgement was made (fake runner).", _features_line(current, quoted)]
        return Flag(kind=kind, severity="review", subject_id=subject, evidence_ids=evidence, exposure_cents=exposure,
                    summary=summary, reasoning="\n".join(reasoning),
                    proposed_action=DEFAULT_ACTIONS[kind], action_params={}, merchant_notice=None)

    async def _review(self, job: Job, steps: Steps) -> Review:
        """Re-read the candidate and its records, then compare the proposal with the rules-only baseline.
        No judgement: agree when they match, otherwise say a person should look."""
        proposal = Flag.model_validate(job.proposal)
        cand = await self._tool(steps, "get_candidate", candidate_id=job.candidate_id)
        kind, subject = cand["kind"], cand["subject_id"]
        if kind == "merchant_silence":
            read = await self._tool(steps, "get_merchant_payments", merchant_id=subject,
                                    since=cand["window_start"], until=cand["window_end"])
        elif kind == "cap_drain":
            read = await self._tool(steps, "get_cert_chain", cert_id=subject)
        else:
            read = await self._tool(steps, "get_region_status", region_id=subject)
        seen = _ids_in(read)
        cited = [normalize(e).lower() for e in proposal.evidence_ids]
        confirmed = [e for e in cited if e in seen]
        baseline = DEFAULT_ACTIONS[kind]
        where = {"merchant_silence": "payments", "cap_drain": "cert chain"}.get(kind, "region")
        reasons = [f"Fake reviewer: the rules-only baseline for {kind} is {baseline}; no agent judgement was made.",
                   f"Fake reviewer: re-read {len(confirmed)} of the {len(cited)} cited records in the {where}."]
        if proposal.kind == kind and proposal.proposed_action == baseline:
            return Review(verdict="agree", reasons=reasons, evidence_ids=confirmed)
        if proposal.kind == "none":
            reasons.append("Fake reviewer: the proposal dismisses a candidate the baseline flags; a person decides.")
            return Review(verdict="disagree", reasons=reasons, evidence_ids=confirmed, suggested_kind=kind,
                          suggested_severity="review", suggested_action=baseline)
        reasons.append("Fake reviewer: the proposal differs from the baseline; a person decides.")
        return Review(verdict="insufficient_evidence", reasons=reasons, evidence_ids=confirmed)


def _ids_in(value: Any) -> set[str]:
    """Every hex id a tool returned (tag hashes, payment and cert ids, alert ids), lowercased."""
    found: set[str] = set()
    if isinstance(value, dict):
        for v in value.values():
            found |= _ids_in(v)
    elif isinstance(value, list):
        for v in value:
            found |= _ids_in(v)
    elif isinstance(value, str):
        found.add(value.lower())
    return found


def _features_line(current: dict, quoted: tuple[str, ...]) -> str:
    """Say where the features came from; the fake runner reports them but doesn't weigh them."""
    if current.get("source") == "chalk":
        values = ", ".join(f"{n} {current['features'].get(n)}" for n in quoted)
        return f"- Chalk at the window end: {values} ({current.get('latency_ms')} ms)."
    if current.get("source") == "postgres_fallback":
        return f"- Features from the Postgres fallback (the detector's frozen values): {current.get('chalk_error')}."
    return f"- Features unavailable: {current.get('error', 'no answer')}."


# Droid runner --------------------------------------------------------------------------------


DENIED = "StormDesk may only use its read-only tools"


def permission_handler(request, denials: list[dict] | None = None) -> Any:
    """Allow only our own read-only MCP tools; refuse everything else (§14.2, §14.7). Each refused action is
    appended to `denials` ({tool, server, reason}) so the run's transcript shows it."""
    from droid_sdk import PermissionResponse, ToolConfirmationOutcome
    from droid_sdk.permissions import McpToolAction

    def ours(action) -> bool:
        if not isinstance(action, McpToolAction) or action.server_name != MCP_SERVER_NAME:
            return False
        name = action.actual_tool_name or action.tool_name.rsplit("__", 1)[-1]
        return name in tools.TOOL_NAMES

    allowed = bool(request.actions) and all(ours(a) for a in request.actions)
    if not allowed and denials is not None:
        refused = [a for a in request.actions if not ours(a)] or [None]  # None: a request naming no action
        denials += [{"tool": getattr(a, "tool_name", None) or getattr(getattr(a, "tool_use", None), "name", None)
                     or (type(a).__name__ if a is not None else None),
                     "server": getattr(a, "server_name", None), "reason": DENIED} for a in refused]
    return PermissionResponse(
        selected_option=ToolConfirmationOutcome.PROCEED_ONCE if allowed else ToolConfirmationOutcome.CANCEL,
        comment=None if allowed else DENIED,
    )


def droid_tool(deps, spec: tools.ToolSpec):
    """Wrap one of our tools as a Droid MCP tool with the same named, annotated arguments."""
    from droid_sdk.mcp import tool

    sig = inspect.signature(spec.function)
    params = [p for n, p in sig.parameters.items() if n not in ("conn", "deps")]

    async def handler(**kwargs: Any) -> dict:
        try:
            return await asyncio.to_thread(tools.call, deps, spec.name, kwargs)
        except tools.ToolError as exc:
            return {"error": str(exc)}

    handler.__signature__ = sig.replace(parameters=params, return_annotation=dict)  # type: ignore[attr-defined]
    handler.__annotations__ = {p.name: spec.function.__annotations__[p.name] for p in params} | {"return": dict}
    handler.__name__ = spec.name
    return tool(spec.name, spec.description)(handler)


def session_config(deps, system_prompt: str = STORMDESK_PROMPT):
    """The same tools, built-ins off and skills off for every job; only the system prompt differs (the reviewer's)."""
    from droid_sdk import SessionConfig
    from droid_sdk.mcp import create_sdk_mcp_server

    server = create_sdk_mcp_server(name=MCP_SERVER_NAME, tools=[droid_tool(deps, t) for t in tools.TOOLS])
    return SessionConfig(system_prompt=system_prompt, mcp_servers=[server], disabled_tools=BUILTIN_TOOLS,
                         disable_builtin_skills=True)


class DroidRunner:
    name = "droid"

    def __init__(self, deps) -> None:
        self.deps = deps
        self.model = deps.settings.stormdesk_model or None  # None: Droid picks ("auto", Factory Router)
        self.api_key = deps.settings.factory_api_key or None

    async def run(self, job: Job, prompt: str, steps: Steps) -> RunOutcome:
        from droid_sdk import InteractionHandlers, Session, ToolCall, ToolResult

        if job.kind == "respond" and (job.appeal or {}).get("mode") == "session":
            return await self._appeal_turn(job, prompt, steps)
        config = session_config(self.deps, job.system_prompt)
        denials: list[dict] = []
        handlers = InteractionHandlers(on_permission=lambda request: permission_handler(request, denials))
        error, session_id, usage = None, None, None
        requested = self.model or "auto"
        model = None
        attempts: list[dict] = []
        for attempt in (1, 2):  # a structured-output failure is a value: retry once (§14.2)
            async with Session(model=self.model, config=config, interactions=handlers, api_key=self.api_key) as s:
                stream = s.stream(prompt, output=job.output_model, timeout=RUN_TIMEOUT_S)
                async for event in stream:
                    if isinstance(event, ToolCall):
                        steps.call(event.name.rsplit("__", 1)[-1], dict(event.input or {}), event.tool_use_id)
                    elif isinstance(event, ToolResult):
                        steps.result(event.tool_use_id, not event.is_error)
                result = stream.result
                model = session_model(s) or model
            session_id = result.session_id
            usage = add_usage(usage, result.usage)
            log.info("StormDesk %s attempt %s on %s (asked for %s): %s", job.kind, attempt, model, requested, usage)
            used = {"usage": usage, "model": model, "model_requested": requested, "attempts": attempts,
                    "permission_denials": denials}
            if result.success and result.structured_output is not None:
                try:
                    output = job.output_model.model_validate(_thaw(result.structured_output))
                    attempts.append({"attempt": attempt, "ok": True, "error": None})
                    return RunOutcome(self.name, output, session_id, **used)
                except ValidationError as exc:
                    error = f"output did not match {job.output_model.__name__}: {exc.error_count()} errors"
            elif result.subtype == "error_during_execution":
                # The agent couldn't run (e.g. "model_usage_exhausted"): retrying won't help.
                message = getattr(result.error, "message", None) or result.text or "no output"
                error = f"error_during_execution: {message}"
                attempts.append({"attempt": attempt, "ok": False, "error": error})
                return RunOutcome(self.name, None, session_id, error, unavailable=True, **used)
            else:
                error = f"{result.subtype}: {result.structured_output_error or 'no output'}"
            attempts.append({"attempt": attempt, "ok": False, "error": error})
            log.warning("StormDesk attempt %s failed: %s", attempt, error)
        return RunOutcome(self.name, None, session_id, error, usage=usage, model=model, model_requested=requested,
                          attempts=attempts, permission_denials=denials)


    async def _appeal_turn(self, job: Job, prompt: str, steps: Steps) -> RunOutcome:
        """One turn of a shop's appeal in the thread's own Droid session (§17.2). Resumes the session the thread
        already has, or starts one. The same tools, built-ins off, permission handler and AppealReply output as
        every run; a failed structured output is asked again once, in the same session. If the session can't be
        reopened (expired, saved on another machine), a new one starts from the thread stored in `messages`."""
        from droid_sdk import InteractionHandlers, Session

        appeal = job.appeal or {}
        denials: list[dict] = []
        handlers = InteractionHandlers(on_permission=lambda request: permission_handler(request, denials))
        requested = self.model or "auto"
        resume_id = appeal.get("resume_session_id")
        opened = {"session": "started", "turn": 1}
        session = None
        if resume_id:
            config = session_config(self.deps, job.system_prompt)
            candidate = Session.resume(resume_id, interactions=handlers, mcp_servers=config.mcp_servers,
                                       api_key=self.api_key, disabled_tools=BUILTIN_TOOLS, disable_builtin_skills=True)
            try:
                await candidate.open()
                session = candidate
                opened = {"session": "resumed", "turn": appeal.get("turn") or 2}
            except Exception as exc:  # e.g. SessionNotFoundError: start over, seeded with the stored thread
                await _close_quietly(candidate)
                log.warning("Appeal session %s couldn't be resumed: %s", resume_id, exc)
                opened = {"session": "restarted", "turn": 1, "resume_error": f"{type(exc).__name__}: {exc}",
                          "resumed_from": resume_id, "seeded_messages": appeal.get("seeded_messages", 0)}
                prompt = appeal.get("restart_prompt") or prompt
        if session is None:
            session = Session(model=self.model, config=session_config(self.deps, job.system_prompt),
                              interactions=handlers, api_key=self.api_key)
            try:
                await session.open()
            except Exception as exc:  # Droid can't run at all: the service answers with the fake runner
                await _close_quietly(session)
                return RunOutcome(self.name, None, None, f"{type(exc).__name__}: {exc}", unavailable=True,
                                  model_requested=requested, attempts=[], permission_denials=denials, appeal=opened)
        usage, model, error, session_id = None, None, None, None
        attempts: list[dict] = []
        try:
            for attempt in (1, 2):  # a structured-output failure is a value: ask again once, same session (§14.2)
                ask = prompt if attempt == 1 else (
                    f"Your last answer wasn't a valid AppealReply ({error}). Answer the shop's message again as an "
                    "AppealReply.")
                result = await _stream_turn(session, job, ask, steps)
                model = session_model(session) or model
                session_id = result.session_id or _session_id(session) or session_id
                usage = add_usage(usage, result.usage)
                log.info("StormDesk appeal turn %s (%s) attempt %s on %s: %s", opened["turn"], opened["session"],
                         attempt, model, usage)
                output, error, unavailable = _judge(job, result)
                attempts.append({"attempt": attempt, "ok": output is not None, "error": error})
                used = {"usage": usage, "model": model, "model_requested": requested, "attempts": attempts,
                        "permission_denials": denials, "appeal": opened}
                if output is not None:
                    return RunOutcome(self.name, output, session_id, **used)
                if unavailable:
                    return RunOutcome(self.name, None, session_id, error, unavailable=True, **used)
                log.warning("StormDesk appeal attempt %s failed: %s", attempt, error)
        finally:
            await _close_quietly(session)
        return RunOutcome(self.name, None, session_id, error, usage=usage, model=model, model_requested=requested,
                          attempts=attempts, permission_denials=denials, appeal=opened)


async def _stream_turn(session, job: Job, prompt: str, steps: Steps):
    """Send one turn on an open session and record its tool calls as steps; returns the turn's result."""
    from droid_sdk import ToolCall, ToolResult

    stream = session.stream(prompt, output=job.output_model, timeout=RUN_TIMEOUT_S)
    async for event in stream:
        if isinstance(event, ToolCall):
            steps.call(event.name.rsplit("__", 1)[-1], dict(event.input or {}), event.tool_use_id)
        elif isinstance(event, ToolResult):
            steps.result(event.tool_use_id, not event.is_error)
    return stream.result


def _judge(job: Job, result) -> tuple[BaseModel | None, str | None, bool]:
    """(output, error, unavailable) for one turn's result, by the same rules as DroidRunner.run (§14.2)."""
    if result.success and result.structured_output is not None:
        try:
            return job.output_model.model_validate(_thaw(result.structured_output)), None, False
        except ValidationError as exc:
            return None, f"output did not match {job.output_model.__name__}: {exc.error_count()} errors", False
    if result.subtype == "error_during_execution":  # the agent couldn't run (e.g. "model_usage_exhausted")
        message = getattr(result.error, "message", None) or result.text or "no output"
        return None, f"error_during_execution: {message}", True
    return None, f"{result.subtype}: {result.structured_output_error or 'no output'}", False


def _session_id(session) -> str | None:
    try:
        return session.id
    except Exception:  # never opened
        return None


async def _close_quietly(session) -> None:
    try:
        await session.close()
    except Exception as exc:  # closing a session that failed to open: nothing left to clean up
        log.debug("closing a Droid session failed: %s", exc)


def session_model(session) -> str | None:
    """The model the open session is on now. Factory announces switches (SettingsUpdated), which update it."""
    try:
        return session.settings.model or None
    except Exception:  # not open, or an SDK without settings: we only know what we asked for
        return None


def _thaw(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def droid_available(deps) -> bool:
    try:
        import droid_sdk  # noqa: F401
    except ImportError:
        return False
    return bool(deps.settings.factory_api_key) and shutil.which("droid") is not None


def make_runner(deps):
    choice = deps.settings.stormdesk_runner
    if choice == "droid" or (choice == "auto" and droid_available(deps)):
        return DroidRunner(deps)
    return FakeRunner(deps)
