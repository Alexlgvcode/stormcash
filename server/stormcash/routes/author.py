"""Droid proposes a detector as a pull request (spec §12.1, §14.7d).

POST starts one author run in the background and answers at once with its run
id; the run's steps stream as `stormdesk_step` events (subject "author run #N")
and its phases as `author` events. The result is the run itself
(`GET /v1/stormdesk/runs/{run_id}`): Droid's DetectorProposal, our re-run's
checks, and the pull request our code opened, if any. Nothing here merges.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from ..db import all_rows
from ..jsonutil import jsonable
from ..stormdesk import author
from .demo import require_operator

router = APIRouter()


class AuthorIn(BaseModel):
    gap: str  # a candidate kind (e.g. "region_dark"), or a description that names one
    examples: list[str | dict] = []  # dev row ids ("seed:candidate_id"), or {row_id, note}


def _author(request: Request) -> author.Author:
    if getattr(request.app.state, "author", None) is None:
        request.app.state.author = author.Author(request.app.state.deps)
    return request.app.state.author


@router.post("/v1/stormdesk/author-detector", status_code=202)
async def author_detector(body: AuthorIn, request: Request, x_sc_operator: str | None = Header(None)) -> dict:
    operator = require_operator(x_sc_operator)
    try:
        job = author.make_job(body.gap, body.examples, operator)
        return _author(request).start(job)
    except author.AuthorError as exc:
        raise HTTPException(409 if "can't run here" in str(exc) or "in progress" in str(exc) else 400, str(exc))


@router.get("/v1/stormdesk/author-detector")
def author_runs(request: Request) -> dict:
    """Whether the job can run here, and the latest author runs (newest first)."""
    deps = request.app.state.deps
    with deps.pool.connection() as conn:
        rows = all_rows(conn, """SELECT run_id, runner, status, output, error, started_at, finished_at,
                                        transcript->'pull_request' AS pull_request, transcript->'kind' AS kind,
                                        transcript->'usage' AS usage, transcript->'model' AS model
                                 FROM stormdesk_runs WHERE job = 'author' ORDER BY run_id DESC LIMIT 20""")
    running = getattr(request.app.state, "author", None)
    return jsonable({**author.status(deps), "running": bool(running and (running.lock.locked() or running.tasks)),
                     "runs": rows})
