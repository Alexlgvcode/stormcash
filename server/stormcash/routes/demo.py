"""Demo operations (spec §12.1): POST /v1/demo/seed-town and its status.

seed-town runs the town simulator (sim/, WS4) into the live database in a
background thread: 72 simulated hours ending now, with the planted scenarios
(Corner Store colluder with an R5 case, stolen phones, Swannanoa dark). It uses
its own Deps with Nessie off and a quiet event broker, so simulated money never
reaches Nessie and thousands of simulated events don't flood the dashboard.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from ..detectors import DetectorState
from ..nessie import MoneyMover
from ..sse import Broker

log = logging.getLogger(__name__)
router = APIRouter()


class SeedTownIn(BaseModel):
    seed: int = 42
    hours: int = 72
    residents: int = 400
    replace: bool = False  # clear the simulated town first (real-device data stays), e.g. after a scenario change


_job: dict = {"status": "idle"}
_lock = threading.Lock()


def require_operator(x_sc_operator: str | None) -> str:
    if not x_sc_operator:
        raise HTTPException(401, "operator actions need the X-SC-Operator header")
    return x_sc_operator


def _run(deps, body: SeedTownIn) -> None:
    from stormcash_sim import outputs
    from stormcash_sim.engine import Params, Sim

    sim_deps = dataclasses.replace(
        deps, nessie=None, mover=MoneyMover(deps.pool, None), events=Broker(), detector_state=DetectorState()
    )
    try:
        if body.replace:
            from ..demo import clear_town

            _job["cleared"] = clear_town(deps)
        sim = Sim(sim_deps, Params(seed=body.seed, hours=body.hours, residents=body.residents))
        _job["sim"] = sim
        summary = sim.run()
        folder = outputs.write(sim, summary)
        _job.update(status="done", summary=summary, outputs=str(folder), finished_at=int(time.time()))
        deps.events.publish("town", {"seed": body.seed, "status": "done", "summary": summary})
    except Exception as exc:  # report it on the status endpoint
        log.exception("seed-town failed")
        _job.update(status="failed", error=f"{type(exc).__name__}: {exc}", finished_at=int(time.time()))
    finally:
        _job.pop("sim", None)


class ResetIn(BaseModel):
    storm_cap_cents: int | None = None  # pre-stage Maya at Storm Mode (§21.1), e.g. 5000


@router.post("/v1/demo/reset")
def demo_reset(request: Request, body: ResetIn | None = None, x_sc_operator: str | None = Header(None)) -> dict:
    """Clean table for the next judge (§12.1): real-device data cleared, fresh Nessie
    accounts, Maya's cert reissued; the simulated town stays."""
    require_operator(x_sc_operator)
    from ..demo import reset_demo

    return reset_demo(request.app.state.deps, storm_cap_cents=body.storm_cap_cents if body else None)


@router.get("/v1/demo/dry-run")
def dry_run_info(request: Request) -> dict:
    """What `python -m stormcash.dryrun` asks before it writes anything (§21.6): this
    server's StormDesk worker skips the dry run's identities, so a dry run can't start
    Droid. A server without this endpoint might, and the dry run refuses to use it."""
    from ..demo import DRY_RUN_PREFIX

    s = request.app.state.deps.settings
    return {"prefix": DRY_RUN_PREFIX, "stormdesk_skips_dry_run": True,
            "stormdesk_worker": s.background_tasks and s.stormdesk_auto, "stormdesk_runner": s.stormdesk_runner,
            "stormdesk_review": s.stormdesk_review}


@router.post("/v1/demo/seed-town", status_code=202)
def seed_town(body: SeedTownIn, request: Request, x_sc_operator: str | None = Header(None)) -> dict:
    require_operator(x_sc_operator)
    try:
        import stormcash_sim  # noqa: F401
    except ImportError as exc:
        raise HTTPException(501, "the simulator isn't installed here: pip install -e ./sim") from exc
    with _lock:
        if _job.get("status") == "running":
            raise HTTPException(409, "seed-town is already running")
        _job.clear()
        _job.update(status="running", seed=body.seed, started_at=int(time.time()), operator=x_sc_operator)
    threading.Thread(target=_run, args=(request.app.state.deps, body), daemon=True, name="seed-town").start()
    return seed_town_status()


@router.get("/v1/demo/seed-town")
def seed_town_status() -> dict:
    out = {k: v for k, v in _job.items() if k != "sim"}
    sim = _job.get("sim")
    if sim is not None and getattr(sim, "progress", None) is not None:
        out["progress"] = round(sim.progress, 3)
    return out
