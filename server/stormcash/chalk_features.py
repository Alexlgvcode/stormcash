"""Chalk online queries for StormDesk's query_features tool (spec §15.2).

The feature classes and resolvers live in chalk/ (WS6) and run in Chalk's
cloud against the hosted Postgres. This module calls Chalk's online query API
with ChalkClient and logs every query's feature names and latency (the Chalk
add-on demo). Any failure raises ChalkUnavailable; the tool then falls back to
Postgres (source "postgres_fallback"). CHALK_DISABLED=1 skips Chalk entirely.

Credentials: CHALK_CLIENT_ID / CHALK_CLIENT_SECRET / CHALK_ENVIRONMENT when
set, otherwise whatever `chalk login` stored for this machine (~/.chalk.yml).
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
if not log.handlers:  # uvicorn only configures its own loggers; keep one visible line per query
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    log.addHandler(_handler)

TIMEOUT_S = 10.0

# The tool's entity names -> Chalk namespaces (chalk/features.py), and the
# features returned when the caller names none. Windows end at `as_of`, the
# sim clock (Unix seconds); Chalk defaults it to the server's latest sync.
NAMESPACES = {"merchant": "merchant", "cert": "certificate", "region": "region"}
FEATURES = {
    "merchant": (
        "name", "region_id", "simulated", "contacts_per_hour_6h", "neighbors_6h", "neighbor_median_contacts_6h",
        "silence_ratio_6h", "accepted_count_6h", "pool_funded_count_6h", "pool_funded_cents_6h",
        "pool_funded_share_6h", "distinct_cheater_certs_6h", "near_cap_share_6h", "paired_contact_share_6h",
        "one_sided_contacts_6h", "prior_windows_flagged",
    ),
    "cert": (
        "status", "storm_mode", "home_region", "cap_cents", "spent_15m_cents", "distinct_merchants_15m",
        "drain_share_15m", "regions_15m", "region_mismatch_15m", "minutes_since_storm_mode",
        "gap_since_last_activity_min", "hour_of_day",
    ),
    "region": (
        "name", "county", "active_certs", "expiring_12h_share", "hours_since_last_upload", "merchants_open_6h",
        "replayed_alert_events", "live_alert_events", "nws_reachable", "active_alert_events", "alert_source",
    ),
}


class ChalkUnavailable(RuntimeError):
    """Chalk couldn't answer; the caller falls back to Postgres."""


_client = None
_client_lock = threading.Lock()


def _get_client(settings):
    global _client
    with _client_lock:
        if _client is None:
            from chalk.client import ChalkClient  # imported on first use: chalkpy is slow to import

            creds = {"client_id": settings.chalk_client_id, "client_secret": settings.chalk_client_secret,
                     "environment": settings.chalk_environment}
            _client = ChalkClient(**{k: v for k, v in creds.items() if v}, default_request_timeout=TIMEOUT_S)
        return _client


def query(settings, entity: str, id: str, features: list[str] | None = None, as_of: int | None = None,
          client=None) -> dict:
    """One online query for one entity. Raises ChalkUnavailable if Chalk can't answer."""
    ns = NAMESPACES[entity]
    key = id.strip() if entity == "region" else id.strip().removeprefix("0x").lower()
    known = FEATURES[entity]
    names = [f for f in features if f in known] if features else list(known)
    unknown = [f for f in features or () if f not in known and f != "as_of"]
    inputs: dict = {f"{ns}.id": key}
    if as_of is not None:
        inputs[f"{ns}.as_of"] = int(as_of)
    outputs = [f"{ns}.as_of"] + [f"{ns}.{n}" for n in names]

    start = time.perf_counter()
    try:
        result = (client or _get_client(settings)).query(input=inputs, output=outputs, request_timeout=TIMEOUT_S)
    except Exception as exc:  # network, auth, a missing deployment: all mean "use the fallback"
        ms = round((time.perf_counter() - start) * 1000)
        log.warning("chalk query %s %s failed after %d ms: %s", ns, key, ms, exc)
        raise ChalkUnavailable(f"{type(exc).__name__}: {exc}") from exc
    ms = round((time.perf_counter() - start) * 1000)

    errors = [getattr(e, "message", None) or str(e) for e in result.errors or []]
    # The server doesn't import chalk/features.py, so values come back as plain JSON values.
    data = {d.field: d.value for d in result.data}
    values = {n: data.get(f"{ns}.{n}") for n in names}
    log.info("chalk query %s %s: %d features in %d ms [%s]%s", ns, key, len(names), ms, ", ".join(names),
             f" errors: {'; '.join(errors)}" if errors else "")
    if errors and all(v is None for v in values.values()):
        raise ChalkUnavailable("; ".join(errors))
    out = {"source": "chalk", "entity": entity, "id": key, "as_of": data.get(f"{ns}.as_of"),
           "features": values, "latency_ms": ms}
    if errors:
        out["errors"] = errors
    if unknown:
        out["unknown_features"] = unknown
        out["known_features"] = list(known)
    return out
