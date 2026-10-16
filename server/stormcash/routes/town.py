"""GET /v1/town, /v1/relay/paths (spec §12.1, §18.4) and /v1/town/quick (§16.6)."""

from __future__ import annotations

import functools
import json
import time

from fastapi import APIRouter, HTTPException, Query, Request

from ..db import all_rows
from ..jsonutil import jsonable
from ..protocol.objects import device_short_id

router = APIRouter()

RECENT_S = 6 * 3600


def _device_names(conn) -> dict[str, dict]:
    """device_short_id -> who it is, for drawing relay paths."""
    names = {}
    for r in all_rows(conn, "SELECT display_name, holder_pub, simulated FROM residents"):
        names[device_short_id(bytes(r["holder_pub"]))] = {"name": r["display_name"], "kind": "resident",
                                                         "simulated": r["simulated"]}
    for r in all_rows(conn, "SELECT display_name, merchant_pub, simulated FROM merchants"):
        names[device_short_id(bytes(r["merchant_pub"]))] = {"name": r["display_name"], "kind": "merchant",
                                                           "simulated": r["simulated"]}
    return names


def _town_stats() -> dict | None:
    """stats.json of the latest simulator run on this machine, if any."""
    try:
        from stormcash_sim.outputs import OUT_DIR
    except ImportError:
        return None
    files = sorted(OUT_DIR.glob("*/stats.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(files[-1].read_text()) if files else None


@router.get("/v1/town")
def get_town(request: Request) -> dict:
    now = int(time.time())
    with request.app.state.deps.pool.connection() as conn:
        regions = all_rows(conn, "SELECT * FROM regions ORDER BY x")
        merchants = all_rows(
            conn,
            """SELECT merchant_id, display_name, region_id, x, y, simulated, pool_eligible FROM merchants
               WHERE x IS NOT NULL AND y IS NOT NULL ORDER BY simulated, display_name""",
        )
        latest = all_rows(conn, "SELECT max(device_ts) AS t FROM payments")[0]["t"] or now
        payments = all_rows(
            conn,
            """SELECT p.tag_hash, p.merchant_id, p.device_ts, p.status, p.hops, t.amount_cents
               FROM payments p JOIN tags t USING (tag_hash) ORDER BY p.device_ts DESC LIMIT 200""",
        )
        uploads = all_rows(
            conn,
            """SELECT upload_id, region_id, item_count, simulated, extract(epoch FROM received_at)::bigint AS at
               FROM uploads ORDER BY received_at DESC LIMIT 100""",
        )
        alerts = all_rows(
            conn,
            """SELECT alert_id, region_id, event, severity, onset, expires, source FROM weather_alerts
               WHERE expires IS NULL OR expires > %s ORDER BY onset""",
            (min(now, latest),),
        )
        dark = all_rows(
            conn,
            """SELECT DISTINCT subject_id AS region_id FROM candidates
               WHERE kind = 'region_dark' AND window_end >= %s""",
            (latest - RECENT_S,),
        )
    return jsonable({
        "grid": {"w": 40, "h": 24},
        "regions": regions,
        "merchants": merchants,
        "recent_payments": payments,
        "uploads": uploads,
        "alerts": alerts,
        "dark_regions": [r["region_id"] for r in dark],
        "town_stats": _town_stats(),
    })


@router.get("/v1/relay/paths")
def relay_paths(request: Request, limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    """Recent payments with the phones that carried them to the server."""
    with request.app.state.deps.pool.connection() as conn:
        names = _device_names(conn)
        rows = all_rows(
            conn,
            """SELECT p.tag_hash, p.device_ts, p.hops, p.path, p.status, p.relay_device, m.display_name AS merchant,
                      m.simulated, t.amount_cents, extract(epoch FROM p.received_at)::bigint AS received
               FROM payments p JOIN merchants m USING (merchant_id) JOIN tags t USING (tag_hash)
               WHERE p.path IS NOT NULL AND jsonb_array_length(p.path) > 0
               ORDER BY p.received_at DESC LIMIT %s""",
            (limit,),
        )
    out = []
    for r in rows:
        hops = [{"device": short, "at": at, **names.get(short, {"name": short, "kind": "unknown"})}
                for short, at in r["path"]]
        out.append({
            "tag_hash": r["tag_hash"], "merchant": r["merchant"], "simulated": r["simulated"],
            "amount_cents": r["amount_cents"], "status": r["status"], "hops": r["hops"], "path": hops,
            "uploaded_by": names.get(device_short_id(bytes(r["relay_device"])), {}).get("name")
            if r["relay_device"] else None,
            "paid_at": r["device_ts"], "received_at": r["received"],
            "latency_s": r["received"] - r["device_ts"],
        })
    return jsonable(out)


@functools.lru_cache(maxsize=64)
def _quick(adoption: float, p_link: float, p_uplink: float) -> dict:
    from stormcash_sim.quick import QuickParams, run_quick

    return run_quick(QuickParams(adoption=adoption, p_link=p_link, p_uplink=p_uplink))


@router.get("/v1/town/quick")
def town_quick(
    adoption: float = Query(0.6, ge=0.1, le=1.0),
    p_link: float = Query(0.6, ge=0.05, le=1.0),
    p_uplink: float = Query(0.03, ge=0.001, le=0.5),
) -> dict:
    """§16.6 sliders: a quick in-memory re-sim (seeded, nothing written), next to the defaults."""
    try:
        import stormcash_sim  # noqa: F401
    except ImportError as exc:
        raise HTTPException(501, "the simulator isn't installed here: pip install -e ./sim") from exc
    started = time.monotonic()
    current = _quick(round(adoption, 2), round(p_link, 2), round(p_uplink, 3))
    return {
        "simulated": True,
        "note": "Quick in-memory model of the simulated town, not live data.",
        "baseline": _quick(0.6, 0.6, 0.03),
        "current": current,
        "seconds": round(time.monotonic() - started, 2),
    }
