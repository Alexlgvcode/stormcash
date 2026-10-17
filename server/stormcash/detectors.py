"""Soft-signal detectors (spec §13): deterministic, they only create candidates.

They never act. Each candidate freezes its feature snapshot; StormDesk judges
it later (a candidate without a flag is a queued StormDesk job). Times are
protocol times (device and ingest `now`), so the simulator's virtual clock
works the same as real time.

- cap_drain: per cert, the 15 minutes ending at each newly received payment.
- merchant_silence: per merchant, the 6 h ending at each hour boundary.
- region_dark: per region, at each hour boundary.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from .db import all_rows, one, pipelined, scalar

log = logging.getLogger(__name__)

HOUR = 3600
SILENCE_WINDOW_S = 6 * HOUR
NEIGHBOR_RADIUS = 3
DRAIN_WINDOW_S = 15 * 60
LOCAL_UTC_OFFSET_S = -4 * HOUR  # Asheville, EDT
ACCEPTED = ("settled", "held", "denied_knowing")
MAX_CATCHUP_HOURS = 96


@dataclass
class DetectorState:
    """Per-process progress: the last evaluated hour and payment."""

    last_hour: int | None = None
    last_run: int | None = None
    # Payments cap_drain already looked at (tag_hash -> received). Several
    # uploads can land in the same second, so time alone can't be the cursor.
    seen: dict[bytes, int] = field(default_factory=dict)


def _insert(conn: psycopg.Connection, kind: str, subject_id: str, window_start: int, window_end: int,
            features: dict) -> dict | None:
    """Store a candidate unless one for the same subject overlaps this window
    (one candidate per silent stretch, drain or dark period)."""
    if scalar(
        conn,
        "SELECT 1 FROM candidates WHERE kind = %s AND subject_id = %s AND window_end > %s AND window_start < %s",
        (kind, subject_id, window_start, window_end),
    ):
        return None
    return one(
        conn,
        """INSERT INTO candidates (kind, subject_id, window_start, window_end, features)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (kind, subject_id, window_start) DO NOTHING RETURNING *""",
        (kind, subject_id, window_start, window_end, Jsonb(features)),
    )


# merchant_silence (§13.1) ---------------------------------------------------------------


def merchant_silence(conn: psycopg.Connection, window_end: int, only: set[bytes] | None = None) -> list[dict]:
    """Evaluate the 6 h window ending at window_end (for `only` these merchants)."""
    return _silence(conn, window_end, _silence_data(_send_silence(conn, window_end)), only)


def _send_silence(conn: psycopg.Connection, window_end: int) -> tuple[psycopg.Cursor, ...]:
    """merchant_silence's reads for one window, sent without waiting."""
    ws, we = window_end - SILENCE_WINDOW_S, window_end
    return (
        conn.execute("SELECT merchant_id, merchant_pub, x, y FROM merchants"),
        conn.execute(
            """SELECT m.merchant_id, count(DISTINCT c.contact_id) AS n FROM merchants m
               JOIN contacts c ON c.device_pub = m.merchant_pub OR c.peer_pub = m.merchant_pub
               WHERE c.ts >= %s AND c.ts < %s GROUP BY m.merchant_id""",
            (ws, we),
        ),
        conn.execute(
            """SELECT p.merchant_id,
                      count(*) AS accepted_count,
                      count(*) FILTER (WHERE p.funded_pool_cents > 0) AS pool_funded_count,
                      COALESCE(sum(p.funded_pool_cents), 0) AS pool_funded_cents,
                      count(*) FILTER (WHERE t.cum_cents >= 0.8 * s.max_cap_cents) AS near_cap_count,
                      count(DISTINCT p.cert_id) FILTER (
                          WHERE EXISTS (SELECT 1 FROM cases c WHERE c.cert_id = p.cert_id)) AS cheater_certs
               FROM payments p JOIN tags t ON t.tag_hash = p.tag_hash JOIN cert_status s ON s.cert_id = p.cert_id
               WHERE p.device_ts >= %s AND p.device_ts < %s AND p.status = ANY(%s)
               GROUP BY p.merchant_id""",
            (ws, we, list(ACCEPTED)),
        ),
    )


def _silence_data(sent: tuple[psycopg.Cursor, ...]) -> tuple[list[dict], dict[bytes, int], dict[bytes, dict]]:
    merchants, contacts, pay = sent
    return (
        merchants.fetchall(),
        {bytes(r["merchant_id"]): r["n"] for r in contacts.fetchall()},
        {bytes(r["merchant_id"]): r for r in pay.fetchall()},
    )


def _silent(data: tuple, only: set[bytes] | None) -> list[tuple]:
    """The merchants that took pool money in the window while their contact
    rate stayed under 0.2 of their neighbors' median. Only these need more reads."""
    merchants, contact_counts, pay = data
    hours = SILENCE_WINDOW_S / HOUR
    out = []
    for m in merchants:
        mid = bytes(m["merchant_id"])
        if only is not None and mid not in only:
            continue
        stats = pay.get(mid)
        if stats is None or stats["pool_funded_count"] < 1:
            continue  # can't fire without pool money in the window
        cph = contact_counts.get(mid, 0) / hours
        neighbors = [
            contact_counts.get(bytes(o["merchant_id"]), 0) / hours
            for o in merchants
            if bytes(o["merchant_id"]) != mid and None not in (m["x"], m["y"], o["x"], o["y"])
            and ((m["x"] - o["x"]) ** 2 + (m["y"] - o["y"]) ** 2) ** 0.5 <= NEIGHBOR_RADIUS
        ]
        neighbor_median = statistics.median(neighbors) if neighbors else 0.0
        silence_ratio = cph / max(neighbor_median, 0.1)
        if silence_ratio < 0.2:
            out.append((m, stats, cph, neighbors, neighbor_median, silence_ratio))
    return out


def _silence(conn: psycopg.Connection, window_end: int, data: tuple, only: set[bytes] | None) -> list[dict]:
    ws, we = window_end - SILENCE_WINDOW_S, window_end
    out = []
    for m, stats, cph, neighbors, neighbor_median, silence_ratio in _silent(data, only):
        mid = bytes(m["merchant_id"])
        mine = all_rows(
            conn,
            """SELECT contact_id, bool_or(paired) AS paired, bool_or(device_pub = %s) AS logged_by_me
               FROM contacts WHERE (device_pub = %s OR peer_pub = %s) AND ts >= %s AND ts < %s
               GROUP BY contact_id""",
            (m["merchant_pub"], m["merchant_pub"], m["merchant_pub"], ws, we),
        )
        own = [r for r in mine if r["logged_by_me"]]
        features = {
            "contacts_per_hour": round(cph, 3),
            "neighbor_median_contacts_per_hour": round(neighbor_median, 3),
            "neighbors": len(neighbors),
            "silence_ratio": round(silence_ratio, 4),
            "pool_funded_count": stats["pool_funded_count"],
            "pool_funded_cents": int(stats["pool_funded_cents"]),
            "accepted_count": stats["accepted_count"],
            "pool_funded_share": round(stats["pool_funded_count"] / stats["accepted_count"], 4),
            "distinct_cheater_certs": stats["cheater_certs"],
            "near_cap_share": round(stats["near_cap_count"] / stats["accepted_count"], 4),
            "paired_contact_share": round(sum(r["paired"] for r in own) / len(own), 4) if own else None,
            "one_sided_contacts": sum(1 for r in mine if not r["paired"]),
            "prior_windows_flagged": scalar(
                conn,
                """SELECT count(*) FROM candidates WHERE kind = 'merchant_silence' AND subject_id = %s
                   AND window_start < %s""",
                (mid.hex(), ws),
            ),
        }
        row = _insert(conn, "merchant_silence", mid.hex(), ws, we, features)
        if row:
            out.append(row)
    return out


# cap_drain (§13.2) ---------------------------------------------------------------------


def cap_drain_for_payment(conn: psycopg.Connection, cert_id: bytes, t: int) -> dict | None:
    """The 15 minutes of this cert's payments ending at t."""
    rows = all_rows(
        conn,
        """SELECT p.device_ts, p.merchant_id, t.amount_cents, m.region_id
           FROM payments p JOIN tags t ON t.tag_hash = p.tag_hash JOIN merchants m ON m.merchant_id = p.merchant_id
           WHERE p.cert_id = %s AND p.device_ts BETWEEN %s AND %s AND p.status = ANY(%s)
           ORDER BY p.device_ts""",
        (cert_id, t - DRAIN_WINDOW_S, t, list(ACCEPTED)),
    )
    merchants = {bytes(r["merchant_id"]) for r in rows}
    if len(merchants) < 3:
        return None
    cap = scalar(
        conn,
        """SELECT cap_cents FROM certificates WHERE cert_id = %s AND issued_at <= %s
           ORDER BY cert_ver DESC LIMIT 1""",
        (cert_id, t),
    ) or scalar(conn, "SELECT max_cap_cents FROM cert_status WHERE cert_id = %s", (cert_id,))
    spent = sum(r["amount_cents"] for r in rows)
    if spent / cap < 0.8:
        return None
    status = one(conn, "SELECT * FROM cert_status WHERE cert_id = %s", (cert_id,))
    home = scalar(
        conn,
        """SELECT r.region_id FROM residents r JOIN certificates c ON c.resident_id = r.resident_id
           WHERE c.cert_id = %s LIMIT 1""",
        (cert_id,),
    )
    first = rows[0]["device_ts"]
    previous = scalar(
        conn,
        """SELECT max(device_ts) FROM payments WHERE cert_id = %s AND device_ts < %s AND status = ANY(%s)""",
        (cert_id, first, list(ACCEPTED)),
    )
    regions = sorted({r["region_id"] for r in rows if r["region_id"]})
    features = {
        "distinct_merchants_15m": len(merchants),
        "spent_15m_cents": spent,
        "cap_cents": cap,
        "drain_share": round(spent / cap, 4),
        "minutes_since_storm_mode": (
            round((t - status["storm_mode_at"]) / 60, 1) if status and status["storm_mode_at"] else None
        ),
        "home_region": home,
        "regions_in_window": regions,
        "region_mismatch": bool(home) and any(r != home for r in regions),
        "hour_of_day": ((t + LOCAL_UTC_OFFSET_S) // HOUR) % 24,
        "gap_since_last_activity_min": None if previous is None else round((first - previous) / 60, 1),
        # The owner texted FREEZE for this cert (Photon, §17.2) before this candidate was created.
        "owner_freeze_request": bool(status and status["owner_freeze_at"] is not None),
    }
    return _insert(conn, "cap_drain", cert_id.hex(), first, t, features)


# region_dark (§13.3) -------------------------------------------------------------------


def region_dark(conn: psycopg.Connection, now: int) -> list[dict]:
    return _region_dark(conn, now, _dark_data(_send_dark(conn)))


def _send_dark(conn: psycopg.Connection) -> tuple[psycopg.Cursor, ...]:
    """region_dark's reads for every region at once (they don't depend on the
    hour), sent without waiting."""
    return (
        conn.execute("SELECT region_id FROM regions ORDER BY region_id"),
        # Each cert's latest version, unless frozen; a cert's region is its resident's.
        conn.execute(
            """SELECT DISTINCT ON (c.cert_id) r.region_id, c.cert_id, c.expires_at, c.issued_at
               FROM certificates c JOIN residents r ON r.resident_id = c.resident_id
               JOIN cert_status s ON s.cert_id = c.cert_id
               WHERE s.status <> 'frozen'
               ORDER BY c.cert_id, c.cert_ver DESC"""
        ),
        conn.execute(
            "SELECT region_id, extract(epoch FROM max(received_at))::bigint AS t FROM uploads GROUP BY region_id"
        ),
    )


def _dark_data(sent: tuple[psycopg.Cursor, ...]) -> tuple[list[str], dict[str, list[dict]], dict[str, int]]:
    regions, certs, uploads = sent
    by_region: dict[str, list[dict]] = {}
    for c in certs.fetchall():
        by_region.setdefault(c["region_id"], []).append(c)
    return [r["region_id"] for r in regions.fetchall()], by_region, {r["region_id"]: r["t"] for r in uploads.fetchall()}


def _dark(data: tuple, now: int) -> list[tuple]:
    """The regions dark at `now`: most active certs expire within 12 h and
    nobody there uploaded for 48 h. Only these need more reads."""
    regions, by_region, last_uploads = data
    out = []
    for rid in regions:
        certs = by_region.get(rid, [])
        active = [c for c in certs if c["expires_at"] > now and c["issued_at"] <= now]
        if not active:
            continue
        expiring = sum(1 for c in active if c["expires_at"] < now + 12 * HOUR) / len(active)
        last_upload = last_uploads.get(rid)
        since = last_upload if last_upload is not None else min(c["issued_at"] for c in certs)
        hours_since = (now - since) / HOUR
        if expiring < 0.3 or hours_since < 48:
            continue
        out.append((rid, active, expiring, since, hours_since))
    return out


def _region_dark(conn: psycopg.Connection, now: int, data: tuple) -> list[dict]:
    out = []
    for rid, active, expiring, since, hours_since in _dark(data, now):
        alerts = all_rows(
            conn,
            """SELECT event, severity, source FROM weather_alerts WHERE region_id = %s
               AND (onset IS NULL OR onset <= %s) AND (expires IS NULL OR expires > %s) ORDER BY alert_id""",
            (rid, now, now),
        )
        features = {
            "active_certs": len(active),
            "expiring_12h_share": round(expiring, 4),
            "hours_since_last_upload": round(hours_since, 1),
            "active_alerts": alerts,
            "population_weight": len(active),
            "merchants_open": scalar(
                conn,
                """SELECT count(DISTINCT p.merchant_id) FROM payments p JOIN merchants m ON m.merchant_id = p.merchant_id
                   WHERE m.region_id = %s AND p.device_ts >= %s AND p.device_ts < %s""",
                (rid, now - SILENCE_WINDOW_S, now),
            ),
        }
        # The window is the dark stretch itself, so later hours of it don't repeat.
        row = _insert(conn, "region_dark", rid, int(since), now, features)
        if row:
            out.append(row)
    return out


# Entry point ------------------------------------------------------------------------------


@dataclass
class Reads:
    """What one detector run reads, sent and not yet waited for."""

    since: int
    hour: int
    ends: list[int]  # hour boundaries to evaluate
    new: psycopg.Cursor
    hourly: list[tuple[psycopg.Cursor, ...]]
    dark: tuple[psycopg.Cursor, ...] | None


def run_incremental(deps, now: int) -> list[dict]:
    """Evaluate what's new since the last run; returns the new candidates.

    cap_drain looks at payments received since the last run; merchant_silence
    and region_dark run once per hour boundary passed (catching up on missed
    hours), so they cost nothing on most uploads. Store-and-forward data can
    arrive hours late, so a newly received pool-funded payment also re-checks
    the silence windows (of its merchant) that contain it."""
    with pipelined(deps.pool) as conn:
        reads = send_incremental(deps, conn, now)
    return finish_incremental(deps, now, reads)


def send_incremental(deps, conn: psycopg.Connection, now: int) -> Reads:
    """Send what every run reads, without waiting: ingest sends it with its
    COMMIT, so a run costs no round trip of its own unless a candidate may fire."""
    state: DetectorState = deps.detector_state
    since = state.last_run if state.last_run is not None else now - HOUR
    hour = now // HOUR
    first = hour if state.last_hour is None else max(state.last_hour + 1, hour - MAX_CATCHUP_HOURS)
    ends = [h * HOUR for h in range(first, hour + 1)]
    # merchants_15m counts what cap_drain_for_payment needs at least 3 of.
    new = conn.execute(
        """SELECT p.cert_id, p.device_ts, p.merchant_id, p.funded_pool_cents, p.tag_hash,
                  extract(epoch FROM p.received_at)::bigint AS received,
                  (SELECT count(DISTINCT q.merchant_id) FROM payments q
                   WHERE q.cert_id = p.cert_id AND q.device_ts BETWEEN p.device_ts - %s AND p.device_ts
                   AND q.status = ANY(%s)) AS merchants_15m
           FROM payments p
           WHERE p.received_at >= to_timestamp(%s) AND p.received_at <= to_timestamp(%s) AND p.status = ANY(%s)
           ORDER BY p.device_ts, p.tag_hash""",
        (DRAIN_WINDOW_S, list(ACCEPTED), since, now, list(ACCEPTED)),
    )
    return Reads(since, hour, ends, new, [_send_silence(conn, end) for end in ends],
                 _send_dark(conn) if ends else None)


def finish_incremental(deps, now: int, reads: Reads) -> list[dict]:
    """The rest of run_incremental, once its reads are in. Candidates are created
    in the same order as evaluating one by one."""
    state: DetectorState = deps.detector_state
    rows = reads.new.fetchall()
    hourly = [_silence_data(sent) for sent in reads.hourly]
    dark = _dark_data(reads.dark) if reads.dark else None

    late: dict[int, set[bytes]] = {}  # window_end -> merchants to re-check
    new = [p for p in rows if bytes(p["tag_hash"]) not in state.seen]
    for p in new:
        state.seen[bytes(p["tag_hash"])] = p["received"]
        if p["funded_pool_cents"] > 0:
            first_end = (p["device_ts"] // HOUR + 1) * HOUR
            for end in range(first_end, min(first_end + SILENCE_WINDOW_S, now // HOUR * HOUR + 1), HOUR):
                late.setdefault(end, set()).add(bytes(p["merchant_id"]))
    state.last_run = now
    state.seen = {h: t for h, t in state.seen.items() if t >= reads.since}  # only the look-back needs them
    drains = [p for p in new if p["merchants_15m"] >= 3]

    created: list[dict] = []
    if drains or late or any(_silent(d, None) for d in hourly) or any(_dark(dark, end) for end in reads.ends):
        with pipelined(deps.pool) as conn:
            for p in drains:
                row = cap_drain_for_payment(conn, bytes(p["cert_id"]), p["device_ts"])
                if row:
                    created.append(row)
            late_sent = {end: _send_silence(conn, end) for end in sorted(late)}
            for end in sorted(late):
                created += _silence(conn, end, _silence_data(late_sent[end]), late[end])
            for end, data in zip(reads.ends, hourly, strict=True):
                created += _silence(conn, end, data, None)
                created += _region_dark(conn, end, dark)
    state.last_hour = reads.hour

    for row in created:
        deps.events.publish("candidate", row)
    return created
