"""The StormDesk worker (spec §14.1): picks up new work and runs it, 4 at a time.

A candidate without a flag and a hard case without a case file are queued
jobs (§13.3a). The worker polls for them, so nothing in settlement has to know
about it and a restart loses nothing. A job that keeps failing stops after
`MAX_ATTEMPTS` runs.
"""

from __future__ import annotations

import asyncio
import logging

from ..db import all_rows
from .runner import Job
from .service import StormDesk

log = logging.getLogger(__name__)

POLL_S = 5.0
MAX_ATTEMPTS = 2
BATCH = 20


def pending_jobs(deps) -> list[Job]:
    with deps.pool.connection() as conn:
        cases = all_rows(
            conn,
            """SELECT c.case_id FROM cases c WHERE c.case_file_md IS NULL
               AND (SELECT count(*) FROM stormdesk_runs r WHERE r.case_id = c.case_id) < %s
               ORDER BY c.case_id LIMIT %s""",
            (MAX_ATTEMPTS, BATCH),
        )
        candidates = all_rows(
            conn,
            """SELECT k.candidate_id FROM candidates k
               WHERE NOT EXISTS (SELECT 1 FROM flags f WHERE f.candidate_id = k.candidate_id)
               AND (SELECT count(*) FROM stormdesk_runs r WHERE r.candidate_id = k.candidate_id) < %s
               ORDER BY k.candidate_id LIMIT %s""",
            (MAX_ATTEMPTS, BATCH),
        )
    return [Job("investigate", case_id=r["case_id"]) for r in cases] + [
        Job("triage", candidate_id=r["candidate_id"]) for r in candidates]


class Worker:
    def __init__(self, desk: StormDesk) -> None:
        self.desk = desk
        self.inflight: set[tuple] = set()

    async def tick(self) -> int:
        """Start every pending job not already running; returns how many started."""
        started = 0
        for job in await asyncio.to_thread(pending_jobs, self.desk.deps):
            key = (job.kind, job.case_id, job.candidate_id)
            if key in self.inflight:
                continue
            self.inflight.add(key)
            asyncio.create_task(self._run(job, key))
            started += 1
        return started

    async def _run(self, job: Job, key: tuple) -> None:
        try:
            await self.desk.run(job)
        except Exception:
            log.exception("StormDesk job %s failed", key)
        finally:
            self.inflight.discard(key)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("StormDesk worker tick failed")
            await asyncio.sleep(POLL_S)
