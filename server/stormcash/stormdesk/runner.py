"""Who answers a StormDesk job (spec §14.2).

- DroidRunner: the real agent, Factory's Droid SDK. Our 11 read-only tools are
  an in-process MCP server; a permission handler refuses everything that isn't
  one of them; the result is structured output, retried once on failure.
- FakeRunner: deterministic, for tests and for running without Factory access.
  It calls the same tools and applies the rules-only baseline (flag every
  candidate with its default action, §13). Its output always says "fake
  runner" and its session id starts with "fake-", so it is never presented as
  an agent's judgement (§0 rule 3).

STORMDESK_RUNNER=droid|fake|auto picks one; auto uses Droid only when the SDK,
the `droid` CLI and FACTORY_API_KEY are all present.
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
from .prompt import STORMDESK_PROMPT
from .schemas import AppealReply, CaseFile, Flag

log = logging.getLogger(__name__)

MCP_SERVER_NAME = "stormdesk"
RUN_TIMEOUT_S = 180
# Droid's built-in tools to switch off. VERIFY with session.list_tools(include_schemas=True)
# once Factory access works (§14.2); the permission handler refuses them regardless.
BUILTIN_TOOLS = frozenset({
    "Execute", "Edit", "Create", "ApplyPatch", "MultiEdit", "Read", "LS", "Grep", "Glob", "FetchUrl",
    "WebSearch", "TodoWrite", "Task", "AskUser", "ExitSpecMode",
})
DEFAULT_ACTIONS = {"merchant_silence": "hold_pool_payout", "cap_drain": "freeze_cert", "region_dark": "dispatch_relay"}


@dataclass
class Job:
    kind: Literal["investigate", "triage", "respond"]
    case_id: int | None = None
    candidate_id: int | None = None
    merchant_id: str | None = None
    message: str | None = None

    @property
    def output_model(self) -> type[BaseModel]:
        return {"investigate": CaseFile, "triage": Flag, "respond": AppealReply}[self.kind]


@dataclass
class RunOutcome:
    runner: str
    output: BaseModel | None
    session_id: str | None = None
    error: str | None = None


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
        return Flag(kind=kind, severity="review", subject_id=subject, evidence_ids=evidence, exposure_cents=exposure,
                    summary=summary, reasoning="- Rules-only baseline: every candidate gets its default action.\n"
                                               "- No agent judgement was made (fake runner).",
                    proposed_action=DEFAULT_ACTIONS[kind], action_params={}, merchant_notice=None)


# Droid runner --------------------------------------------------------------------------------


def permission_handler(request) -> Any:
    """Allow only our own read-only MCP tools; refuse everything else (§14.2, §14.7)."""
    from droid_sdk import PermissionResponse, ToolConfirmationOutcome
    from droid_sdk.permissions import McpToolAction

    def ours(action) -> bool:
        if not isinstance(action, McpToolAction) or action.server_name != MCP_SERVER_NAME:
            return False
        name = action.actual_tool_name or action.tool_name.rsplit("__", 1)[-1]
        return name in tools.TOOL_NAMES

    allowed = bool(request.actions) and all(ours(a) for a in request.actions)
    return PermissionResponse(
        selected_option=ToolConfirmationOutcome.PROCEED_ONCE if allowed else ToolConfirmationOutcome.CANCEL,
        comment=None if allowed else "StormDesk may only use its read-only tools",
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


def session_config(deps):
    from droid_sdk import SessionConfig
    from droid_sdk.mcp import create_sdk_mcp_server

    server = create_sdk_mcp_server(name=MCP_SERVER_NAME, tools=[droid_tool(deps, t) for t in tools.TOOLS])
    return SessionConfig(system_prompt=STORMDESK_PROMPT, mcp_servers=[server], disabled_tools=BUILTIN_TOOLS,
                         disable_builtin_skills=True)


class DroidRunner:
    name = "droid"

    def __init__(self, deps) -> None:
        self.deps = deps
        self.model = deps.settings.stormdesk_model or None  # None: Droid picks ("auto", Factory Router)
        self.api_key = deps.settings.factory_api_key or None

    async def run(self, job: Job, prompt: str, steps: Steps) -> RunOutcome:
        from droid_sdk import InteractionHandlers, Session, ToolCall, ToolResult

        config = session_config(self.deps)
        handlers = InteractionHandlers(on_permission=permission_handler)
        error, session_id = None, None
        for attempt in (1, 2):  # a structured-output failure is a value: retry once (§14.2)
            async with Session(model=self.model, config=config, interactions=handlers, api_key=self.api_key) as s:
                stream = s.stream(prompt, output=job.output_model, timeout=RUN_TIMEOUT_S)
                async for event in stream:
                    if isinstance(event, ToolCall):
                        steps.call(event.name.rsplit("__", 1)[-1], dict(event.input or {}), event.tool_use_id)
                    elif isinstance(event, ToolResult):
                        steps.result(event.tool_use_id, not event.is_error)
                result = stream.result
            session_id = result.session_id
            if result.success and result.structured_output is not None:
                try:
                    return RunOutcome(self.name, job.output_model.model_validate(_thaw(result.structured_output)),
                                      session_id)
                except ValidationError as exc:
                    error = f"output did not match {job.output_model.__name__}: {exc.error_count()} errors"
            else:
                error = f"{result.subtype}: {result.structured_output_error or result.error or 'no output'}"
            log.warning("StormDesk attempt %s failed: %s", attempt, error)
        return RunOutcome(self.name, None, session_id, error)


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
