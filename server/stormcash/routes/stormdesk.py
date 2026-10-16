"""StormDesk API (spec §12.1, WS5): run a job, read flags and stored runs."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from ..db import all_rows, one
from ..jsonutil import jsonable
from ..stormdesk.runner import Job
from .demo import require_operator

router = APIRouter()


class RunIn(BaseModel):
    candidate_id: int | None = None
    case_id: int | None = None


@router.post("/v1/stormdesk/run")
async def stormdesk_run(body: RunIn, request: Request, x_sc_operator: str | None = Header(None)) -> dict:
    """Run StormDesk now on one case or candidate and wait for it (used by evals and the dashboard)."""
    require_operator(x_sc_operator)
    if (body.candidate_id is None) == (body.case_id is None):
        raise HTTPException(400, "give exactly one of candidate_id or case_id")
    job = Job("triage", candidate_id=body.candidate_id) if body.candidate_id is not None \
        else Job("investigate", case_id=body.case_id)
    return await request.app.state.stormdesk.run(job)


def _flag_row(row: dict) -> dict:
    agent = row.get("agent_transcript") or {}
    return {**{k: v for k, v in row.items() if k != "agent_transcript"}, "runner": agent.get("runner"),
            "run_id": agent.get("run_id")}


@router.get("/v1/flags")
def list_flags(request: Request, status: str | None = None, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(
            conn,
            """SELECT f.*, k.kind AS candidate_kind, k.window_start, k.window_end FROM flags f
               JOIN candidates k USING (candidate_id) WHERE %s::text IS NULL OR f.status = %s
               ORDER BY f.flag_id DESC LIMIT %s""",
            (status, status, limit),
        )
    return jsonable([_flag_row(r) for r in rows])


@router.get("/v1/flags/{flag_id}")
def get_flag(flag_id: int, request: Request) -> dict:
    """The flag, the candidate's frozen features and the agent transcript."""
    with request.app.state.deps.pool.connection() as conn:
        flag = one(conn, "SELECT * FROM flags WHERE flag_id = %s", (flag_id,))
        if flag is None:
            raise HTTPException(404, "no such flag")
        candidate = one(conn, "SELECT * FROM candidates WHERE candidate_id = %s", (flag["candidate_id"],))
    return jsonable({"flag": _flag_row(flag), "candidate": candidate, "agent": flag["agent_transcript"]})


@router.get("/v1/stormdesk/runs")
def list_runs(request: Request, case_id: int | None = None, candidate_id: int | None = None,
              limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(
            conn,
            """SELECT run_id, job, case_id, candidate_id, runner, status, citations_valid, session_id, error,
                      started_at, finished_at, jsonb_array_length(transcript->'steps') AS steps
               FROM stormdesk_runs WHERE (%s::bigint IS NULL OR case_id = %s) AND (%s::bigint IS NULL OR candidate_id = %s)
               ORDER BY run_id DESC LIMIT %s""",
            (case_id, case_id, candidate_id, candidate_id, limit),
        )
    return jsonable(rows)


@router.get("/v1/stormdesk/runs/{run_id}")
def get_run(run_id: int, request: Request) -> dict:
    """A stored run with its full transcript, for step-by-step replay (§14.8)."""
    with request.app.state.deps.pool.connection() as conn:
        row = one(conn, "SELECT * FROM stormdesk_runs WHERE run_id = %s", (run_id,))
    if row is None:
        raise HTTPException(404, "no such run")
    return jsonable(row)
