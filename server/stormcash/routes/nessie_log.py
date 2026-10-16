"""GET /v1/nessie/log: rows of nessie_calls for the dashboard call log (§12.1, §18.2)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..db import all_rows
from ..jsonutil import jsonable

router = APIRouter()


@router.get("/v1/nessie/log")
def nessie_log(request: Request, limit: int = Query(50, ge=1, le=500), reads: bool = False) -> list[dict]:
    """Newest first. Balance reads (GET) are logged too but hidden unless reads=1."""
    with request.app.state.deps.pool.connection() as conn:
        rows = all_rows(
            conn,
            """SELECT * FROM nessie_calls WHERE %s OR method <> 'GET'
               ORDER BY call_id DESC LIMIT %s""",
            (reads, limit),
        )
    return jsonable(rows)
