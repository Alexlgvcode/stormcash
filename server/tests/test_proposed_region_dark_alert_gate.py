from stormcash.detectors_proposed.region_dark_alert_gate import fires

ALERT = [{"event": "Flash Flood Warning", "severity": "Severe", "source": "replayed"}]


def base(**kw):
    row = {
        "active_alerts": ALERT,
        "active_certs": 50,
        "expiring_12h_share": 0.5,
        "hours_since_last_upload": 55.0,
        "merchants_open": 0,
        "population_weight": 50,
    }
    row.update(kw)
    return row


def test_stale_region_with_alert_fires():
    assert fires(base())


def test_quiet_region_without_alert_is_not_raised():
    assert not fires(base(active_alerts=[], expiring_12h_share=1.0))


def test_recent_upload_does_not_fire():
    assert not fires(base(hours_since_last_upload=10.0))


def test_low_expiring_share_does_not_fire():
    assert not fires(base(expiring_12h_share=0.1))


def test_open_merchants_do_not_block():
    assert fires(base(merchants_open=2))
