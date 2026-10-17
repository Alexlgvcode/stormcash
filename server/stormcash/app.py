"""FastAPI app and router wiring (spec §12). Owned by WS2.

Run with the app factory so settings load at startup, not at import:

    uvicorn --factory stormcash.app:create_app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import registry, sse
from .approvals import ApprovalError
from .config import Settings, load_settings
from .db import make_pool
from .deps import Deps
from .nessie import MoneyMover, NessieClient
from .photon import routes as photon_routes
from .photon.config import PhotonSettings
from .photon.config import load as load_photon
from .regions import ensure_regions
from .stormdesk.service import StormDesk, StormDeskError
from .stormdesk.worker import Worker
from .routes import accounts, cases, demo, droid_console, evals, nessie_log, registration, stormdesk, sync, town

log = logging.getLogger(__name__)

REPLAY_EVERY_S = 10
ESCROW_RELEASE_EVERY_S = 60


def _settled_notice(deps: Deps, payout_id: int) -> None:
    """Tell a real shop it was paid (§17), off the money path: a slow or failed send never delays ingest."""
    if deps.photon is None:
        return
    from .photon import notices

    with deps.pool.connection() as conn:  # only shops that registered a handle get notices
        if conn.execute("""SELECT 1 FROM payouts o JOIN merchant_contacts c USING (merchant_id)
                           WHERE o.payout_id = %s""", (payout_id,)).fetchone() is None:
            return

    def send() -> None:
        try:
            notices.settled_notice(deps, deps.photon, payout_id)
        except Exception:
            log.exception("settled notice for payout %s failed", payout_id)

    threading.Thread(target=send, daemon=True, name=f"settled-{payout_id}").start()


def build_deps(settings: Settings, nessie_transport: httpx.BaseTransport | None = None) -> Deps:
    pool = make_pool(settings.database_url)
    events = sse.Broker()
    nessie = None
    if settings.nessie_enabled:
        nessie = NessieClient(
            settings.nessie_base_url, settings.nessie_api_key, pool, events, transport=nessie_transport
        )
    deps = Deps(settings, pool, events, nessie, MoneyMover(pool, nessie, events))
    deps.mover.on_payout_executed = lambda payout_id: _settled_notice(deps, payout_id)
    with pool.connection() as conn:
        for table, migration in (("nessie_moves", "001_nessie_moves"), ("stormdesk_runs", "002_stormdesk_runs"),
                                 ("resident_contacts", "004_resident_freeze")):
            if conn.execute("SELECT to_regclass(%s) AS t", (table,)).fetchone()["t"] is None:
                raise RuntimeError(f"database is missing {table}: apply server/migrations/{migration}.sql")
        check = conn.execute(
            "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conname = 'payouts_status_check'"
        ).fetchone()
        if check is None or "held" not in check["d"]:
            raise RuntimeError("payouts can't be held yet: apply server/migrations/003_payouts_held.sql")
        ensure_regions(conn)
    return deps


def _background(deps: Deps, stop: threading.Event) -> None:
    """Replay queued Nessie moves every 10 s; release due escrows every 60 s."""
    ticks = 0
    while not stop.wait(REPLAY_EVERY_S):
        ticks += 1
        try:
            deps.mover.replay_queued()
            if ticks % (ESCROW_RELEASE_EVERY_S // REPLAY_EVERY_S) == 0:
                registry.release_due_escrows(deps)
        except Exception:  # keep the loop alive; the next tick retries
            log.exception("background task failed")


DASHBOARD_DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"


def create_app(
    settings: Settings | None = None,
    nessie_transport: httpx.BaseTransport | None = None,
    dashboard_dist: Path | None = DASHBOARD_DIST,
    photon: PhotonSettings | None = None,
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        deps = build_deps(settings, nessie_transport)
        app.state.deps = deps
        app.state.photon = deps.photon = photon or load_photon()
        app.state.stormdesk = StormDesk(deps)
        stop = threading.Event()
        worker = None
        if settings.background_tasks:
            threading.Thread(target=_background, args=(deps, stop), daemon=True, name="stormcash-bg").start()
            if settings.stormdesk_auto:
                worker = asyncio.create_task(Worker(app.state.stormdesk).run_forever())
        try:
            yield
        finally:
            if worker is not None:
                worker.cancel()
            stop.set()
            if deps.nessie is not None:
                deps.nessie.close()
            deps.pool.close()

    app = FastAPI(title="StormCash", lifespan=lifespan)
    # Demo: the dashboard dev server and the public proof page call from other origins.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(registry.RegistryError)
    async def registry_error(request: Request, exc: registry.RegistryError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(ApprovalError)
    async def approval_error(request: Request, exc: ApprovalError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(StormDeskError)
    async def stormdesk_error(request: Request, exc: StormDeskError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    app.include_router(registration.router)
    app.include_router(sync.router)
    app.include_router(cases.router)
    app.include_router(accounts.router)
    app.include_router(demo.router)
    app.include_router(town.router)
    app.include_router(stormdesk.router)
    app.include_router(droid_console.router)
    app.include_router(photon_routes.router)
    app.include_router(nessie_log.router)
    app.include_router(evals.router)
    app.include_router(sse.router)
    _serve_dashboard(app, dashboard_dist)
    return app


def _serve_dashboard(app: FastAPI, dist: Path | None) -> None:
    """Serve the built dashboard (npm run build) from the same origin as the API,
    so one public URL gives judges both /proof/<case_id> and the API it calls."""
    if dist is None or not (dist / "index.html").exists():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("v1/"):
            raise HTTPException(404, "not found")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist.resolve()):
            return FileResponse(file)
        return FileResponse(dist / "index.html")
