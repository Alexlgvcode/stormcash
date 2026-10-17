"""Live NWS alerts for a region (spec §15.1), falling back to replayed rows.

GET https://api.weather.gov/alerts/active?area=NC (NWS asks for a User-Agent
naming the app; NWS_USER_AGENT, a Chalk secret, overrides the default). An
alert belongs to a region when its geocodes include the region's county or
forecast zone. Live alerts win when there are any for the region; otherwise the
region gets the `weather_alerts` rows with source='replayed' that are active at
its sim clock (region.replayed_alert_events). alert_source says which one
active_alert_events came from, so replayed weather is always labeled replayed.
"""

from __future__ import annotations

import logging
import os
import time

import requests
from chalk import online
from chalk.features import Features

from features import Region

log = logging.getLogger(__name__)

NWS_URL = "https://api.weather.gov/alerts/active?area=NC"
DEFAULT_USER_AGENT = "StormCash HackHarvard demo (https://github.com/Alexlgvcode/stormcash)"
CACHE_S = 60  # one NWS call a minute at most, however many regions a query asks for

# All four demo regions are in Buncombe County, NC (§16.3): its county FIPS
# (SAME), its county zone and its forecast zone (checked on api.weather.gov/zones).
BUNCOMBE = frozenset({"037021", "NCC021", "NCZ053"})
REGION_CODES = {
    "asheville-downtown": BUNCOMBE,
    "west-asheville": BUNCOMBE,
    "swannanoa": BUNCOMBE,
    "black-mountain": BUNCOMBE,
}

_cache: tuple[float, list[dict]] | None = None


def fetch_alerts() -> list[dict] | None:
    """The `properties` of every active NC alert, or None when NWS can't be reached."""
    global _cache
    if _cache is not None and time.monotonic() - _cache[0] < CACHE_S:
        return _cache[1]
    try:
        resp = requests.get(
            NWS_URL,
            headers={"User-Agent": os.getenv("NWS_USER_AGENT") or DEFAULT_USER_AGENT,
                     "Accept": "application/geo+json"},
            timeout=5,
        )
        resp.raise_for_status()
        alerts = [f["properties"] for f in resp.json()["features"]]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        log.warning("NWS alerts unavailable: %s", exc)
        return None
    _cache = (time.monotonic(), alerts)
    return alerts


def events_for(alerts: list[dict], codes: frozenset[str]) -> list[str]:
    """Distinct event names of the alerts whose geocodes touch these codes, in NWS order."""
    events: list[str] = []
    for alert in alerts:
        geocode = alert.get("geocode") or {}
        if codes & set(geocode.get("SAME", []) + geocode.get("UGC", [])) and alert.get("event") not in events:
            events.append(alert["event"])
    return events


def choose(live: list[str] | None, replayed: list[str]) -> tuple[list[str], str]:
    """Live alerts if NWS has any for the region, else the replayed ones.

    With NWS unreachable the answer is always labeled replayed; with NWS up
    and nothing live or replayed, it's an (empty) live answer."""
    if live:
        return live, "live"
    if replayed or live is None:
        return replayed, "replayed"
    return [], "live"


@online
def region_alerts(
    id: Region.id, replayed: Region.replayed_alert_events
) -> Features[Region.live_alert_events, Region.nws_reachable, Region.active_alert_events, Region.alert_source]:
    alerts = fetch_alerts()
    live = None if alerts is None else events_for(alerts, REGION_CODES.get(id, frozenset()))
    events, source = choose(live, list(replayed or []))
    return Region(live_alert_events=live or [], nws_reachable=alerts is not None,
                  active_alert_events=events, alert_source=source)
