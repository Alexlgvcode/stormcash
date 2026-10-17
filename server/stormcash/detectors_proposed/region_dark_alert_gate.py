"""Raises a region_dark candidate only when the region is both stale and under an active weather alert. The current rule
(expiring share >= 0.3 and no upload for >= 48 h) also fires on quiet regions where nothing is happening, which are
honest traps: a region with no alert has no storm reason to have gone silent, so it is not raised."""

KIND = "region_dark"
NAME = "region_dark_alert_gate"

MIN_EXPIRING_SHARE = 0.3
MIN_HOURS_SINCE_UPLOAD = 48.0


def fires(features: dict) -> bool:
    alerts = features.get("active_alerts") or []
    if len(alerts) == 0:
        return False
    if features.get("expiring_12h_share", 0.0) < MIN_EXPIRING_SHARE:
        return False
    return features.get("hours_since_last_upload", 0.0) >= MIN_HOURS_SINCE_UPLOAD
