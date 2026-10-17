"""Run a StormDesk job and store what it produced (spec §14.1, §14.7).

Every run is a `stormdesk_runs` row with its full transcript (for replay and
audit). Each tool call is published live as a `stormdesk_step` SSE event.
Citations are checked before anything is saved; an output with a missing id
is stored as `invalid` and never shown as actionable. Triage writes one
`flags` row per candidate; an investigation writes `cases.case_file_md` only
when its citations hold.

A review (§14.7b) is a second Droid session that tries to refute a triage
Flag with the same read-only tools. It is stored on the flag. Only a valid
review by an agent counts, and all it can do is put the flag in front of a
person ("agents disagree"); Approve and Reject stay with that person.
"""

from __future__ import annotations

import asyncio
import json
import time

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from ..db import one, scalar
from ..jsonutil import jsonable
from .citations import citations_valid
from .prompt import (PROMPT_VERSION, REVIEW_PROMPT_VERSION, investigate_prompt, respond_prompt, review_prompt,
                     triage_prompt)
from .runner import FakeRunner, Job, RunOutcome, Steps, make_runner
from .schemas import Flag

DROID_COOLDOWN_S = 300  # after Droid couldn't run, use the fake runner this long before trying again
REVIEWABLE = ("open", "dismissed")  # a valid proposal a person may see; invalid ones never reach anyone


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
        elif job.kind == "review":
            kind = scalar(conn, "SELECT kind FROM candidates WHERE candidate_id = %s", (job.candidate_id,))
            prompt = review_prompt(job.candidate_id, kind, job.proposal or {})
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


def review_job(deps, flag_id: int | None = None, candidate_id: int | None = None,
               proposal: dict | None = None) -> Job:
    """The review of a stored flag (by flag or candidate id), or of a proposal passed in with its candidate
    (an eval reviewing stored outputs: nothing is written to `flags` then)."""
    with deps.pool.connection() as conn:
        if proposal is None:
            flag = one(conn, "SELECT * FROM flags WHERE flag_id = %s", (flag_id,)) if flag_id is not None else \
                one(conn, "SELECT * FROM flags WHERE candidate_id = %s", (candidate_id,))
            if flag is None:
                raise NotFound(f"no flag for {'flag' if flag_id is not None else 'candidate'} "
                               f"{flag_id if flag_id is not None else candidate_id}")
            if flag["status"] not in REVIEWABLE:
                raise Conflict(f"flag {flag['flag_id']} is {flag['status']}: only open or dismissed flags are reviewed")
            run_id = (flag["agent_transcript"] or {}).get("run_id")
            output = scalar(conn, "SELECT output FROM stormdesk_runs WHERE run_id = %s", (run_id,)) if run_id else None
            if output is None:
                raise Conflict(f"flag {flag['flag_id']} has no stored StormDesk output to review")
            return Job("review", candidate_id=flag["candidate_id"], proposal=Flag.model_validate(output).model_dump(),
                       flag_id=flag["flag_id"], reviewed_run_id=run_id)
        if candidate_id is None or scalar(conn, "SELECT 1 FROM candidates WHERE candidate_id = %s",
                                          (candidate_id,)) is None:
            raise NotFound(f"no candidate {candidate_id}")
        try:
            flag = Flag.model_validate(proposal)
        except ValidationError as exc:
            raise StormDeskError(f"proposal is not a Flag: {exc.error_count()} errors") from exc
        valid, missing = citations_valid(conn, list(flag.evidence_ids), required=flag.kind != "none")
        if not valid:
            raise Conflict(f"the proposal's citations don't hold (missing {missing}): it never reaches a person")
        return Job("review", candidate_id=candidate_id, proposal=flag.model_dump())


def after_review(proposal: dict, status: str, review: dict | None) -> tuple[str, bool]:
    """(status, agents_disagree) for a flag once it has been reviewed (§14.7b). Deterministic. Only a valid
    review by an agent counts (the fake reviewer's rules-only comparison doesn't); agreeing keeps the flag
    as StormDesk proposed it, and anything else keeps it open for a person. A decided flag stays decided."""
    if status not in REVIEWABLE:
        return status, False
    status = "dismissed" if proposal.get("kind") == "none" else "open"  # what StormDesk's proposal alone gives
    if review is None or review.get("status") != "succeeded" or review.get("runner") == "fake" \
            or review.get("verdict") == "agree":
        return status, False
    return "open", True


def _store(deps, job: Job, run_id: int, outcome: RunOutcome, steps: Steps, fallback: RunOutcome | None = None,
           duration_s: float | None = None) -> dict:
    output = outcome.output
    with deps.pool.connection() as conn:
        missing: list[str] = []
        valid = False
        if output is not None:
            needs_ids = not (job.kind in ("respond", "review") or (job.kind == "triage" and output.kind == "none"))
            valid, missing = citations_valid(conn, list(output.evidence_ids), required=needs_ids)
        status = "succeeded" if output is not None and valid else "invalid" if output is not None else "failed"
        version = REVIEW_PROMPT_VERSION if job.kind == "review" else PROMPT_VERSION
        transcript = {"runner": outcome.runner, "steps": steps.transcript, "missing_citations": missing,
                      "error": outcome.error, "fallback_from_droid": fallback.error if fallback else None,
                      "model": outcome.model, "model_requested": outcome.model_requested, "usage": outcome.usage,
                      "fallback_usage": fallback.usage if fallback else None, "duration_s": duration_s,
                      "prompt_version": version if outcome.runner == "droid" else None}
        # Droid only (absent = not recorded): each structured-output attempt, and what the permission handler refused.
        for key, value in (("attempts", outcome.attempts), ("permission_denials", outcome.permission_denials),
                           ("fallback_attempts", fallback.attempts if fallback else None),
                           ("fallback_permission_denials", fallback.permission_denials if fallback else None)):
            if value is not None:
                transcript[key] = value
        if job.kind == "review":
            transcript["reviewed"] = {"flag_id": job.flag_id, "run_id": job.reviewed_run_id, "proposal": job.proposal}
        run = one(
            conn,
            """UPDATE stormdesk_runs SET runner = %s, status = %s, output = %s, citations_valid = %s, transcript = %s,
                      session_id = %s, error = %s, finished_at = now() WHERE run_id = %s RETURNING *""",
            (outcome.runner, status, Jsonb(output.model_dump() if output else None), valid, Jsonb(transcript),
             outcome.session_id, outcome.error, run_id),
        )
        result = {"run_id": run_id, "runner": outcome.runner, "status": status, "citations_valid": valid,
                  "missing_citations": missing, "error": outcome.error,
                  "fallback_from_droid": transcript["fallback_from_droid"],
                  "model": outcome.model, "model_requested": outcome.model_requested, "usage": outcome.usage,
                  "prompt_version": transcript["prompt_version"], "duration_s": duration_s,
                  "session_id": outcome.session_id, "job": job.kind,
                  "output": output.model_dump() if output else None}
        if job.kind == "triage":
            result["flag"] = _save_flag(conn, job, output, valid, outcome, run, transcript)
        elif job.kind == "review":
            review = {k: result[k] for k in ("run_id", "runner", "status", "citations_valid", "missing_citations",
                                             "error", "fallback_from_droid", "model", "model_requested", "usage",
                                             "prompt_version", "duration_s")}
            review |= {"reviewed_run_id": job.reviewed_run_id, **(output.model_dump() if output else {"verdict": None})}
            proposal = job.proposal or {}
            status_after, disagree = after_review(proposal, "open", review)  # "open": not decided yet
            result["after_review"] = {"status": status_after, "agents_disagree": disagree,
                                      "kind": proposal.get("kind"), "proposed_action": proposal.get("proposed_action")}
            if job.flag_id is not None:
                result["flag"] = _save_review(conn, job, review)
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
                  status = %(status)s, created_at = now(), review = NULL, agents_disagree = FALSE
           WHERE flag_id = %(flag_id)s RETURNING *""",
        {**params, "flag_id": existing},
    )


def _save_review(conn, job: Job, review: dict) -> dict | None:
    """Store the review on its flag. Skipped if StormDesk re-triaged the flag meanwhile (the review is of
    an older proposal; its run is still stored)."""
    flag = one(conn, "SELECT * FROM flags WHERE flag_id = %s FOR UPDATE", (job.flag_id,))
    if flag is None or (flag["agent_transcript"] or {}).get("run_id") != job.reviewed_run_id:
        return None
    status, disagree = after_review(job.proposal or {}, flag["status"], review)
    return one(conn, "UPDATE flags SET review = %s, agents_disagree = %s, status = %s WHERE flag_id = %s RETURNING *",
               (Jsonb(review), disagree, status, job.flag_id))


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

    async def review(self, flag_id: int | None = None, candidate_id: int | None = None,
                     proposal: dict | None = None, runner=None) -> dict:
        """Run the reviewer on a stored flag, or on a proposal passed in with its candidate (§14.7b)."""
        job = await asyncio.to_thread(review_job, self.deps, flag_id, candidate_id, proposal)
        return await self.run(job, runner)

    async def run(self, job: Job, runner=None) -> dict:
        runner = runner or self.pick_runner()
        prompt, run_id = await asyncio.to_thread(_prepare, self.deps, job)
        subject = f"case #{job.case_id}" if job.case_id else f"candidate #{job.candidate_id}" \
            if job.candidate_id else f"merchant {job.merchant_id}"
        if job.kind == "review":
            subject = f"review of {subject}"  # its own live step list, next to the triage's

        def on_step(step: dict) -> None:
            self.deps.events.publish("stormdesk_step", {
                "run_id": run_id, "job": job.kind, "subject": subject, "runner": runner.name,
                "index": step["index"], "tool": step["tool"], "input_summary": step["input_summary"], "ok": step["ok"],
            })

        steps = Steps(on_step=on_step)
        fallback = None
        started = time.monotonic()
        async with self.slots:
            try:
                outcome = await runner.run(job, prompt, steps)
            except Exception as exc:  # e.g. Droid unreachable: a failed run, stored like any other
                outcome = RunOutcome(runner.name, None, None, f"{type(exc).__name__}: {exc}",
                                     unavailable=runner.name == "droid")
            if outcome.unavailable and runner.name == "droid":
                # Droid couldn't run at all (no credits, CLI gone): answer with the labelled fake runner
                # now, skip Droid for a while, and record why.
                fallback = outcome
                self.droid_down_until = time.monotonic() + DROID_COOLDOWN_S
                self.droid_down_reason = outcome.error
                runner = FakeRunner(self.deps)
                steps = Steps(on_step=on_step)
                outcome = await runner.run(job, prompt, steps)
        duration = round(time.monotonic() - started, 1)
        result = await asyncio.to_thread(_store, self.deps, job, run_id, outcome, steps, fallback, duration)
        self.deps.events.publish("stormdesk_step", {"run_id": run_id, "job": job.kind, "subject": subject,
                                                    "runner": runner.name, "done": True, "status": result["status"]})
        if result.get("flag"):
            self.deps.events.publish("flag", result["flag"])
        if job.kind == "triage" and self.deps.settings.stormdesk_review and result["flag"]["status"] in REVIEWABLE:
            # The second opinion (§14.7b), by the same kind of runner the desk would pick now.
            try:
                review = await self.review(flag_id=result["flag"]["flag_id"])
            except StormDeskError as exc:  # e.g. an operator decided the flag first
                review = {"status": "skipped", "error": str(exc)}
            result["review"] = review
            result["flag"] = review.get("flag") or result["flag"]
        return json.loads(json.dumps(jsonable(result)))
