"""GET /v1/droid/console: what Droid did in the running product, from stored runs (spec §14, §18.7).

Read-only aggregates over `stormdesk_runs` (one row per StormDesk run, with its
transcript) for the dashboard's Droid tab. Every number comes from a stored
row (§0 rule 3):

- Each run's outcome: valid, invalid citation, structured output failed after
  its retry, fake-runner fallback (Droid couldn't run), plain fake runner, failed.
- Totals per job count Droid's own runs only. Fake-runner runs, fallbacks
  included, are counted next to them and never in a success rate.
- Appeal conversations (§17.2): respond runs that are turns of one Droid
  session per appeal thread, counted by session (started, resumed, restarted).
- Guardrail events are the runs where one actually fired. A guardrail whose
  events older runs didn't record (structured-output retries that then
  succeeded, permission-handler denials) has a null count and says how many
  runs record it, never zero.
"""

from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, Query, Request

from ..db import all_rows
from ..jsonutil import jsonable
from ..stormdesk import prompt, runner, tools
from ..stormdesk.prompt import PROMPT_VERSION

router = APIRouter()

JOB_ORDER = ("investigate", "triage", "respond", "review")
# What DroidRunner stores when the structured output failed on both attempts (§14.2).
STRUCTURED_OUTPUT_ERRORS = ("error_structured_output", "output did not match")
REVIEW_VERDICT = {"agree": "agrees", "disagree": "disagrees", "insufficient_evidence": "insufficient evidence"}
UNFINISHED_AFTER_S = 15 * 60  # a 'running' row this old never finished (e.g. the server restarted mid-run)

OUTCOME_LABEL = {
    "valid": "Valid",
    "invalid_citation": "Invalid citation",
    "structured_output_failed": "Structured output failed after retry",
    "fallback": "Fake-runner fallback",
    "fake": "Fake runner",
    "failed": "Failed",
    "running": "Running",
    "unfinished": "Never finished",
}

RUNS_SQL = """
SELECT r.run_id, r.job, r.case_id, r.candidate_id, encode(r.merchant_id, 'hex') AS merchant_id, r.runner, r.status,
       r.citations_valid, r.session_id, r.error, r.output, r.started_at, r.finished_at,
       (EXTRACT(EPOCH FROM (r.finished_at - r.started_at)) * 1000)::bigint AS duration_ms,
       r.transcript - 'steps' AS meta,
       COALESCE((SELECT jsonb_agg(jsonb_build_array(s->'tool', s->'ok'))
                 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.transcript->'steps') = 'array'
                                                THEN r.transcript->'steps' ELSE '[]' END) s), '[]') AS steps,
       c.rule AS case_rule, k.kind AS candidate_kind,
       COALESCE(
         (SELECT display_name FROM merchants m WHERE encode(m.merchant_id, 'hex') = k.subject_id),
         (SELECT re.display_name FROM residents re JOIN certificates ce ON ce.resident_id = re.resident_id
          WHERE encode(ce.cert_id, 'hex') = k.subject_id LIMIT 1),
         (SELECT display_name FROM regions g WHERE g.region_id = k.subject_id),
         (SELECT display_name FROM merchants m WHERE m.merchant_id = r.merchant_id)) AS subject_name
FROM stormdesk_runs r
LEFT JOIN cases c ON c.case_id = r.case_id
LEFT JOIN candidates k ON k.candidate_id = r.candidate_id
ORDER BY r.run_id DESC
"""


def outcome(row: dict, now: float) -> str:
    meta = row.get("meta") or {}
    if row["status"] == "running":
        started = row["started_at"]
        age = now - (started.timestamp() if hasattr(started, "timestamp") else started)
        return "unfinished" if age > UNFINISHED_AFTER_S else "running"
    if meta.get("fallback_from_droid"):
        return "fallback"
    if row["runner"] == "fake":
        return "fake"
    if row["status"] == "succeeded":
        return "valid"
    if row["status"] == "invalid":
        return "invalid_citation"
    if (row.get("error") or "").startswith(STRUCTURED_OUTPUT_ERRORS):
        return "structured_output_failed"
    return "failed"


def _credits(usage) -> float | None:
    return usage.get("factory_credits") if isinstance(usage, dict) else None


def _droid_key(row: dict, key: str) -> str | None:
    """Where a run stores what its Droid session recorded: under `fallback_<key>` when the fake runner answered."""
    if row["runner"] == "droid":
        return key
    return f"fallback_{key}" if (row.get("meta") or {}).get("fallback_from_droid") else None


def structured_output_retries(row: dict, result: str) -> int | None:
    """How many times the structured output was retried; None when the run didn't record it."""
    key = _droid_key(row, "attempts")
    if key is None:
        return None
    attempts = (row.get("meta") or {}).get(key)
    if isinstance(attempts, list):
        return max(len(attempts) - 1, 0)
    if result == "structured_output_failed":
        return 1  # stored only after the one retry also failed (§14.2)
    return None


def permission_denials(row: dict) -> list | None:
    key = _droid_key(row, "permission_denials")
    denials = (row.get("meta") or {}).get(key) if key else None
    return denials if isinstance(denials, list) else None


def verdict(row: dict) -> str | None:
    """What the run concluded, in a few words (from its structured output)."""
    out = row.get("output")
    if not isinstance(out, dict):
        return None
    if row["job"] == "triage":
        kind = out.get("kind")
        return "dismissed" if kind == "none" else f"{kind} → {out.get('proposed_action')}"
    if row["job"] == "investigate":
        return "rule re-verified" if out.get("verified_independently") else "rule not re-verified"
    if row["job"] == "respond":
        return "escalated to a person" if out.get("escalate") else "answered"
    if row["job"] == "review":  # the second-opinion Droid's Review (§14.7b)
        return REVIEW_VERDICT.get(out.get("verdict"), out.get("verdict"))
    return None


def subject(row: dict) -> str:
    if row.get("case_id") is not None:
        return f"case #{row['case_id']}" + (f" · {row['case_rule']}" if row.get("case_rule") else "")
    if row.get("candidate_id") is not None:
        parts = [f"candidate #{row['candidate_id']}", row.get("candidate_kind"), row.get("subject_name")]
        return " · ".join(p for p in parts if p)
    if row.get("merchant_id"):
        name = row.get("subject_name") or f"merchant {row['merchant_id'][:8]}"
        turn = appeal_turn(row)
        return f"{name} · appeal turn {turn['turn']}" if turn else name
    reviewed = reviewed_run_id(row)
    return f"run #{reviewed}" if reviewed is not None else "—"


def appeal_turn(row: dict) -> dict | None:
    """A respond run that is a turn of its appeal thread's Droid session (§17.2): {session, turn, session_id}."""
    appeal = (row.get("meta") or {}).get("appeal")
    if row["job"] != "respond" or row["runner"] != "droid" or not isinstance(appeal, dict) \
            or appeal.get("mode") != "session" or not appeal.get("turn"):
        return None
    return {"session": appeal.get("session"), "turn": appeal["turn"], "session_id": row.get("session_id"),
            "resume_error": appeal.get("resume_error")}


def appeal_sessions(runs: list[dict]) -> dict:
    """Droid's appeal conversations: how many sessions, how many turns, how many turns resumed a session and how
    many started over from the stored thread because the session couldn't be resumed."""
    turns = [r["appeal"] for r in runs if r.get("appeal")]
    per_session = Counter(t["session_id"] for t in turns)
    return {
        "sessions": len(per_session),
        "turns": len(turns),
        "resumed": sum(1 for t in turns if t["session"] == "resumed"),
        "restarted": sum(1 for t in turns if t["session"] == "restarted"),
        "longest": max(per_session.values(), default=0),
    }


def reviewed_run_id(row: dict) -> int | None:
    """The StormDesk run a review checked (the reviewer stores it as transcript.reviewed.run_id)."""
    meta = row.get("meta") or {}
    reviewed = meta.get("reviewed")
    return reviewed.get("run_id") if isinstance(reviewed, dict) else meta.get("reviewed_run_id")


def run_view(row: dict, now: float) -> dict:
    meta = row.get("meta") or {}
    result = outcome(row, now)
    steps = row.get("steps") or []
    ours = [s for s in steps if s[0] in tools.TOOL_NAMES]
    other = Counter(s[0] for s in steps if s[0] not in tools.TOOL_NAMES)
    usage = meta.get("usage") if row["runner"] == "droid" else meta.get("fallback_usage")
    denials = permission_denials(row)
    return {
        "run_id": row["run_id"],
        "job": row["job"],
        "subject": subject(row),
        "case_id": row.get("case_id"),
        "candidate_id": row.get("candidate_id"),
        "runner": row["runner"],
        "status": row["status"],
        "outcome": result,
        "outcome_label": OUTCOME_LABEL[result],
        "verdict": verdict(row),
        "model": meta.get("model"),
        "model_requested": meta.get("model_requested"),
        "prompt_version": meta.get("prompt_version"),
        "duration_ms": row.get("duration_ms"),
        "factory_credits": _credits(usage),
        "usage": usage if isinstance(usage, dict) else None,
        "tool_calls": len(ours),
        "tool_errors": sum(1 for s in ours if s[1] is False),
        "other_calls": dict(other),  # e.g. Droid's ToolSearch loading our tool schemas (§14.2)
        "citations_valid": row.get("citations_valid"),
        "missing_citations": len(meta.get("missing_citations") or []),
        "structured_output_retries": structured_output_retries(row, result),
        "permission_denials": len(denials) if denials is not None else None,
        "fallback_reason": meta.get("fallback_from_droid"),
        "reviewed_run_id": reviewed_run_id(row),
        "appeal": appeal_turn(row),
        "session_id": row.get("session_id"),
        "error": row.get("error"),
        "started_at": row["started_at"],
        "finished_at": row.get("finished_at"),
    }


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def totals(runs: list[dict]) -> dict:
    """Droid's own finished runs: count, valid share, mean credits and duration. Fake runs counted beside them."""
    droid = [r for r in runs if r["runner"] == "droid" and r["outcome"] not in ("running", "unfinished")]
    valid = sum(1 for r in droid if r["outcome"] == "valid")
    credits = [r["factory_credits"] for r in droid if r["factory_credits"] is not None]
    return {
        "droid_runs": len(droid),
        "valid": valid,
        "success_rate": valid / len(droid) if droid else None,
        "credits_total": sum(credits) if credits else None,
        "credits_runs": len(credits),  # how many Droid runs recorded their credits
        "mean_credits": _mean(credits),
        "mean_duration_ms": _mean([r["duration_ms"] for r in droid]),
        "tool_calls": sum(r["tool_calls"] for r in droid),
        "fake_runs": sum(1 for r in runs if r["outcome"] == "fake"),
        "fallback_runs": sum(1 for r in runs if r["outcome"] == "fallback"),
        "running": sum(1 for r in runs if r["outcome"] == "running"),
        "unfinished": sum(1 for r in runs if r["outcome"] == "unfinished"),
        "outcomes": dict(Counter(r["outcome"] for r in droid)),
    }


def _event(run: dict, detail: str | None = None) -> dict:
    return {"run_id": run["run_id"], "runner": run["runner"], "job": run["job"], "detail": detail}


def guardrails(runs: list[dict]) -> list[dict]:
    droid = [r for r in runs if r["runner"] == "droid"]
    sessions = [r for r in runs if r["runner"] == "droid" or r["outcome"] == "fallback"]  # every Droid session
    recorded_retries = [r for r in sessions if r["structured_output_retries"] is not None
                        and r["outcome"] != "structured_output_failed"]
    recorded_denials = [r for r in sessions if r["permission_denials"] is not None]

    def counted(events: list[dict], recorded: int | None = None) -> dict:
        return {"count": len(events), "events": events, "recorded_runs": recorded}

    invalid = [_event(r, f"{r['missing_citations']} cited id(s) not in the database")
               for r in runs if r["outcome"] == "invalid_citation"]
    failed_retry = [_event(r, r["error"]) for r in runs if r["outcome"] == "structured_output_failed"]
    retried = [_event(r, f"retried {r['structured_output_retries']}×, then: {r['outcome_label'].lower()}")
               for r in recorded_retries if r["structured_output_retries"]]
    fallbacks = [_event(r, r["fallback_reason"]) for r in runs if r["outcome"] == "fallback"]
    denials = [_event(r, f"{r['permission_denials']} tool request(s) refused")
               for r in recorded_denials if r["permission_denials"]]
    return [
        {"key": "invalid_citation", "label": "Invalid citations rejected",
         "about": "An id Droid cited isn't in the database: the result is stored invalid, never actionable.",
         **counted(invalid, len(runs))},
        {"key": "structured_output_retry", "label": "Structured output retried",
         "about": "A missing or malformed structured output is retried once; these runs got an output on the retry.",
         **(counted(retried, len(recorded_retries)) if recorded_retries
            else {"count": None, "events": [], "recorded_runs": 0})},
        {"key": "structured_output_failed", "label": "Structured output failed after the retry",
         "about": "Both attempts failed: stored as failed, nothing saved.", **counted(failed_retry, len(droid))},
        {"key": "fallback", "label": "Fake-runner fallbacks",
         "about": "Droid couldn't run (e.g. out of credits): the labelled fake runner answered instead.",
         **counted(fallbacks, len(runs))},
        {"key": "permission_denial", "label": "Permission-handler denials",
         "about": "A tool request outside StormDesk's 11 read-only tools, refused by the permission handler.",
         **(counted(denials, len(recorded_denials)) if recorded_denials
            else {"count": None, "events": [], "recorded_runs": 0})},
    ]


def console(rows: list[dict], now: float, limit: int) -> dict:
    runs = [run_view(r, now) for r in rows]
    jobs = list(JOB_ORDER[:3]) + sorted({r["job"] for r in runs} - set(JOB_ORDER[:3]),
                                         key=lambda j: (JOB_ORDER.index(j) if j in JOB_ORDER else len(JOB_ORDER), j))
    builtin_seen = Counter()
    for r in runs:
        if r["runner"] == "droid":
            builtin_seen.update({name: 1 for name in r["other_calls"]})
    # The reviewer Droid's verdicts on StormDesk's proposals: valid Droid reviews only (a fake review is rules only).
    verdicts = Counter((r["output"] or {}).get("verdict") for r in rows
                       if r["job"] == "review" and r["runner"] == "droid" and r["status"] == "succeeded")
    return {
        "as_of": int(now),
        "run_count": len(runs),
        "review_verdicts": {k: verdicts[k] for k in REVIEW_VERDICT if verdicts[k]},
        "appeal_sessions": appeal_sessions(runs),
        "totals": totals(runs),
        "by_job": [{"job": job, **totals([r for r in runs if r["job"] == job])} for job in jobs],
        "guardrails": guardrails(runs),
        "builtin_calls_seen": dict(builtin_seen),  # Droid runs where a built-in tool still ran, by tool
        "runs": runs[:limit],
    }


def harness(request: Request) -> dict:
    """How Droid is set up right now (from the code and the running server, not from runs)."""
    deps = request.app.state.deps
    desk = getattr(request.app.state, "stormdesk", None)
    cooldown_s = max(0, int(desk.droid_down_until - time.monotonic())) if desk else 0
    return {
        "mcp_server": runner.MCP_SERVER_NAME,
        "read_only_tools": list(tools.TOOL_NAMES),
        "builtin_tools_disabled": len(runner.BUILTIN_TOOLS),
        "prompt_version": PROMPT_VERSION,
        "review_prompt_version": getattr(prompt, "REVIEW_PROMPT_VERSION", None),  # once the reviewer Droid exists
        "runner_setting": deps.settings.stormdesk_runner,
        "droid_available": runner.droid_available(deps),
        "model_setting": deps.settings.stormdesk_model or "auto",
        "worker_on": bool(deps.settings.stormdesk_auto and deps.settings.background_tasks),
        "cooldown_s": cooldown_s,
        "cooldown_reason": desk.droid_down_reason if desk and cooldown_s else None,
    }


@router.get("/v1/droid/console")
def droid_console(request: Request, limit: int = Query(200, ge=1, le=1000)) -> dict:
    with request.app.state.deps.pool.connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")  # this view never writes
        rows = all_rows(conn, RUNS_SQL)
    return jsonable({**console(rows, time.time(), limit), "harness": harness(request)})
