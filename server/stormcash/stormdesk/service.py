"""Run a StormDesk job and store what it produced (spec §14.1, §14.7).

Every run is a `stormdesk_runs` row with its full transcript (for replay and
audit). Each tool call is published live as a `stormdesk_step` SSE event.
Citations are checked before anything is saved; an output with a missing id
is stored as `invalid` and never shown as actionable. Triage writes one
`flags` row per candidate; an investigation writes `cases.case_file_md` only
when its citations hold.
"""

from __future__ import annotations

import asyncio
import json
import time

from psycopg.types.json import Jsonb

from ..db import one, scalar
from ..jsonutil import jsonable
from .citations import citations_valid
from .prompt import investigate_prompt, respond_prompt, triage_prompt
from .runner import FakeRunner, Job, RunOutcome, Steps, make_runner

DROID_COOLDOWN_S = 300  # after Droid couldn't run, use the fake runner this long before trying again


class StormDeskError(ValueError):
    status = 400


class NotFound(StormDeskError):
    status = 404


class Conflict(StormDeskError):
    status = 409


def _prepare(deps, job: Job) -> tuple[str, int]:
    """Check the job and return (prompt, run_id)."""
    with deps.pool.connection() as conn:
        if job.kind == "investigate":
            rule = scalar(conn, "SELECT rule FROM cases WHERE case_id = %s", (job.case_id,))
            if rule is None:
                raise NotFound(f"no case {job.case_id}")
            prompt = investigate_prompt(job.case_id, rule)
        elif job.kind == "triage":
            kind = scalar(conn, "SELECT kind FROM candidates WHERE candidate_id = %s", (job.candidate_id,))
            if kind is None:
                raise NotFound(f"no candidate {job.candidate_id}")
            decided = scalar(conn, "SELECT status FROM flags WHERE candidate_id = %s AND status IN ('approved', 'rejected')",
                             (job.candidate_id,))
            if decided:
                raise Conflict(f"candidate {job.candidate_id} was already {decided} by an operator")
            prompt = triage_prompt(job.candidate_id, kind)
        else:
            prompt = respond_prompt(job.merchant_id or "", job.message or "")
        run_id = scalar(
            conn,
            """INSERT INTO stormdesk_runs (job, case_id, candidate_id, merchant_id, runner, status)
               VALUES (%s, %s, %s, %s, %s, 'running') RETURNING run_id""",
            (job.kind, job.case_id, job.candidate_id, bytes.fromhex(job.merchant_id) if job.merchant_id else None,
             "pending"),
        )
    return prompt, run_id


def _store(deps, job: Job, run_id: int, outcome: RunOutcome, steps: Steps, fallback: str | None = None,
           fallback_usage: dict | None = None) -> dict:
    output = outcome.output
    with deps.pool.connection() as conn:
        missing: list[str] = []
        valid = False
        if output is not None:
            needs_ids = not (job.kind == "respond" or (job.kind == "triage" and output.kind == "none"))
            valid, missing = citations_valid(conn, list(output.evidence_ids), required=needs_ids)
        status = "succeeded" if output is not None and valid else "invalid" if output is not None else "failed"
        transcript = {"runner": outcome.runner, "steps": steps.transcript, "missing_citations": missing,
                      "error": outcome.error, "fallback_from_droid": fallback, "model": outcome.model,
                      "model_requested": outcome.model_requested, "usage": outcome.usage,
                      "fallback_usage": fallback_usage}
        run = one(
            conn,
            """UPDATE stormdesk_runs SET runner = %s, status = %s, output = %s, citations_valid = %s, transcript = %s,
                      session_id = %s, error = %s, finished_at = now() WHERE run_id = %s RETURNING *""",
            (outcome.runner, status, Jsonb(output.model_dump() if output else None), valid, Jsonb(transcript),
             outcome.session_id, outcome.error, run_id),
        )
        result = {"run_id": run_id, "runner": outcome.runner, "status": status, "citations_valid": valid,
                  "missing_citations": missing, "error": outcome.error, "fallback_from_droid": fallback,
                  "model": outcome.model, "model_requested": outcome.model_requested, "usage": outcome.usage,
                  "output": output.model_dump() if output else None}
        if job.kind == "triage":
            result["flag"] = _save_flag(conn, job, output, valid, outcome, run, transcript)
        elif job.kind == "investigate" and output is not None and valid:
            conn.execute("UPDATE cases SET case_file_md = %s WHERE case_id = %s", (output.summary_md, job.case_id))
            result["case_file_md"] = output.summary_md
    return result


def _save_flag(conn, job: Job, output, valid: bool, outcome: RunOutcome, run: dict, transcript: dict) -> dict:
    cand = one(conn, "SELECT kind, subject_id FROM candidates WHERE candidate_id = %s", (job.candidate_id,))
    if output is None:
        values = dict(kind=cand["kind"], severity="info", subject_id=cand["subject_id"], evidence_ids=[],
                      exposure_cents=0, summary="StormDesk produced no valid output.", proposed_action="none")
        status = "invalid"
    else:
        values = dict(kind=output.kind, severity=output.severity, subject_id=output.subject_id,
                      evidence_ids=list(output.evidence_ids), exposure_cents=output.exposure_cents,
                      summary=output.summary, proposed_action=output.proposed_action)
        status = "invalid" if not valid else "dismissed" if output.kind == "none" else "open"
    agent = {**transcript, "run_id": run["run_id"],
             "reasoning": output.reasoning if output else None,
             "action_params": output.action_params if output else {},
             "merchant_notice": output.merchant_notice if output else None}
    existing = scalar(conn, "SELECT flag_id FROM flags WHERE candidate_id = %s", (job.candidate_id,))
    params = {**values, "citations_valid": valid, "agent_session_id": outcome.session_id,
              "agent_transcript": Jsonb(agent), "status": status, "candidate_id": job.candidate_id}
    if existing is None:
        return one(
            conn,
            """INSERT INTO flags (candidate_id, kind, severity, subject_id, evidence_ids, exposure_cents, summary,
                                  proposed_action, citations_valid, agent_session_id, agent_transcript, status)
               VALUES (%(candidate_id)s, %(kind)s, %(severity)s, %(subject_id)s, %(evidence_ids)s, %(exposure_cents)s,
                       %(summary)s, %(proposed_action)s, %(citations_valid)s, %(agent_session_id)s,
                       %(agent_transcript)s, %(status)s) RETURNING *""",
            params,
        )
    return one(
        conn,
        """UPDATE flags SET kind = %(kind)s, severity = %(severity)s, subject_id = %(subject_id)s,
                  evidence_ids = %(evidence_ids)s, exposure_cents = %(exposure_cents)s, summary = %(summary)s,
                  proposed_action = %(proposed_action)s, citations_valid = %(citations_valid)s,
                  agent_session_id = %(agent_session_id)s, agent_transcript = %(agent_transcript)s,
                  status = %(status)s, created_at = now()
           WHERE flag_id = %(flag_id)s RETURNING *""",
        {**params, "flag_id": existing},
    )


class StormDesk:
    """Runs jobs, at most `concurrency` at a time (spec §14.1: 4 Droid sessions)."""

    def __init__(self, deps, concurrency: int = 4) -> None:
        self.deps = deps
        self.slots = asyncio.Semaphore(concurrency)
        self.droid_down_until = 0.0
        self.droid_down_reason: str | None = None

    def pick_runner(self):
        runner = make_runner(self.deps)
        if runner.name == "droid" and time.monotonic() < self.droid_down_until:
            return FakeRunner(self.deps)
        return runner

    async def run(self, job: Job, runner=None) -> dict:
        runner = runner or self.pick_runner()
        prompt, run_id = await asyncio.to_thread(_prepare, self.deps, job)
        subject = f"case #{job.case_id}" if job.case_id else f"candidate #{job.candidate_id}" \
            if job.candidate_id else f"merchant {job.merchant_id}"

        def on_step(step: dict) -> None:
            self.deps.events.publish("stormdesk_step", {
                "run_id": run_id, "job": job.kind, "subject": subject, "runner": runner.name,
                "index": step["index"], "tool": step["tool"], "input_summary": step["input_summary"], "ok": step["ok"],
            })

        steps = Steps(on_step=on_step)
        fallback, fallback_usage = None, None
        async with self.slots:
            try:
                outcome = await runner.run(job, prompt, steps)
            except Exception as exc:  # e.g. Droid unreachable: a failed run, stored like any other
                outcome = RunOutcome(runner.name, None, None, f"{type(exc).__name__}: {exc}",
                                     unavailable=runner.name == "droid")
            if outcome.unavailable and runner.name == "droid":
                # Droid couldn't run at all (no credits, CLI gone): answer with the labelled fake runner
                # now, skip Droid for a while, and record why.
                fallback, fallback_usage = outcome.error, outcome.usage
                self.droid_down_until = time.monotonic() + DROID_COOLDOWN_S
                self.droid_down_reason = fallback
                runner = FakeRunner(self.deps)
                steps = Steps(on_step=on_step)
                outcome = await runner.run(job, prompt, steps)
        result = await asyncio.to_thread(_store, self.deps, job, run_id, outcome, steps, fallback, fallback_usage)
        self.deps.events.publish("stormdesk_step", {"run_id": run_id, "job": job.kind, "subject": subject,
                                                    "runner": runner.name, "done": True, "status": result["status"]})
        if result.get("flag"):
            self.deps.events.publish("flag", result["flag"])
        return json.loads(json.dumps(jsonable(result)))
