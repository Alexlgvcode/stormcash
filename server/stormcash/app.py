"""FastAPI app and router wiring (spec §12). Owned by WS2.

Run with the app factory so settings load at startup, not at import:

    uvicorn --factory stormcash.app:create_app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

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
from .config import Settings, load_settings
from .db import make_pool
from .deps import Deps
from .nessie import MoneyMover, NessieClient
from .regions import ensure_regions
from .routes import accounts, cases, demo, nessie_log, registration, sync

log = logging.getLogger(__name__)

REPLAY_EVERY_S = 10
ESCROW_RELEASE_EVERY_S = 60


def build_deps(settings: Settings, nessie_transport: httpx.BaseTransport | None = None) -> Deps:
    pool = make_pool(settings.database_url)
    events = sse.Broker()
    nessie = None
    if settings.nessie_enabled:
        nessie = NessieClient(
            settings.nessie_base_url, settings.nessie_api_key, pool, events, transport=nessie_transport
        )
    deps = Deps(settings, pool, events, nessie, MoneyMover(pool, nessie, events))
    with pool.connection() as conn:
        if conn.execute("SELECT to_regclass('nessie_moves') AS t").fetchone()["t"] is None:
            raise RuntimeError("database is missing nessie_moves: apply server/migrations/001_nessie_moves.sql")
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
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        deps = build_deps(settings, nessie_transport)
        app.state.deps = deps
        stop = threading.Event()
        if settings.background_tasks:
            threading.Thread(target=_background, args=(deps, stop), daemon=True, name="stormcash-bg").start()
        try:
            yield
        finally:
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

    app.include_router(registration.router)
    app.include_router(sync.router)
    app.include_router(cases.router)
    app.include_router(accounts.router)
    app.include_router(demo.router)
    app.include_router(nessie_log.router)
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
