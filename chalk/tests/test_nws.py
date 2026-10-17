"""The NWS resolver's mapping and live/replayed choice (no network)."""

from resolvers import nws

FLOOD = {"event": "Flash Flood Warning", "geocode": {"SAME": ["037021"], "UGC": ["NCZ053"]}}
WIND = {"event": "Wind Advisory", "geocode": {"SAME": ["037053"], "UGC": ["NCZ102"]}}
ZONE_ONLY = {"event": "Freeze Warning", "geocode": {"UGC": ["NCZ053", "NCZ052"]}}


def test_events_map_to_buncombe_regions_only():
    alerts = [WIND, FLOOD, ZONE_ONLY, FLOOD]
    assert nws.events_for(alerts, nws.REGION_CODES["swannanoa"]) == ["Flash Flood Warning", "Freeze Warning"]
    assert nws.events_for(alerts, frozenset()) == []
    assert nws.events_for([{"event": "X"}], nws.BUNCOMBE) == []


def test_choose_labels_the_source():
    assert nws.choose(["Flash Flood Warning"], ["Hurricane Warning"]) == (["Flash Flood Warning"], "live")
    assert nws.choose([], ["Flash Flood Warning"]) == (["Flash Flood Warning"], "replayed")
    assert nws.choose(None, ["Flash Flood Warning"]) == (["Flash Flood Warning"], "replayed")
    assert nws.choose(None, []) == ([], "replayed")
    assert nws.choose([], []) == ([], "live")


def test_resolver_falls_back_when_nws_is_down(monkeypatch):
    monkeypatch.setattr(nws, "fetch_alerts", lambda: None)
    out = nws.region_alerts("swannanoa", ["Flash Flood Warning"])
    assert out.active_alert_events == ["Flash Flood Warning"]
    assert out.alert_source == "replayed"
    assert out.nws_reachable is False


def test_resolver_prefers_live(monkeypatch):
    monkeypatch.setattr(nws, "fetch_alerts", lambda: [WIND, FLOOD])
    out = nws.region_alerts("black-mountain", [])
    assert (out.active_alert_events, out.alert_source, out.live_alert_events) == (
        ["Flash Flood Warning"], "live", ["Flash Flood Warning"])
