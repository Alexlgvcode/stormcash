"""Citation check (spec §14.7): every evidence id must exist in the database.

Accepted ids: tag / payment hashes, device-log entry hashes, contact ids, a
hard case's proof item id (get_case returns it), cert ids and merchant ids
(lowercase hex, optionally with a "kind:" prefix) and weather alert ids. Any miss makes the output invalid; it is never shown as
actionable.
"""

from __future__ import annotations

import re

from ..db import scalar

_PREFIX = re.compile(r"^(tag|payment|entry|dlog|contact|proof|cert|merchant|alert)[:/]", re.IGNORECASE)
_HEX = re.compile(r"^[0-9a-f]+$")
_HEX_LOOKUPS = {
    32: ("SELECT 1 FROM tags WHERE tag_hash = %(b)s UNION ALL SELECT 1 FROM device_log WHERE entry_hash = %(b)s "
         "UNION ALL SELECT 1 FROM contacts WHERE contact_id = %(b)s "
         "UNION ALL SELECT 1 FROM cases WHERE evidence->>'proof_item_id' = %(h)s LIMIT 1"),
    16: ("SELECT 1 FROM certificates WHERE cert_id = %(b)s UNION ALL SELECT 1 FROM merchants WHERE merchant_id = %(b)s "
         "LIMIT 1"),
}


def normalize(evidence_id: str) -> str:
    return _PREFIX.sub("", str(evidence_id).strip())


def missing_ids(conn, evidence_ids: list[str]) -> list[str]:
    missing = []
    for raw in evidence_ids:
        value = normalize(raw)
        lowered = value.lower()
        sql = _HEX_LOOKUPS.get(len(lowered) // 2) if _HEX.match(lowered) and len(lowered) % 2 == 0 else None
        if sql is not None:
            found = scalar(conn, sql, {"b": bytes.fromhex(lowered), "h": lowered})
        else:
            found = scalar(conn, "SELECT 1 FROM weather_alerts WHERE alert_id = %s", (value,))
        if found is None:
            missing.append(raw)
    return missing


def citations_valid(conn, evidence_ids: list[str], *, required: bool) -> tuple[bool, list[str]]:
    """(valid, missing). `required`: a claim must cite at least one id."""
    missing = missing_ids(conn, evidence_ids)
    return (not missing and (bool(evidence_ids) or not required)), missing
