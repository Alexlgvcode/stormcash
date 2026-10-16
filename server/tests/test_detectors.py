"""WS2 #26: soft-signal detectors (spec §13). They only create candidates."""

from __future__ import annotations

from stormcash import detectors, registry, settlement
from stormcash.db import all_rows, scalar
from stormcash.protocol import crypto
from stormcash.protocol.objects import Det, Item, Pay, Tag, genesis

T0 = 1792238400  # 08:00 in Asheville
HOUR = 3600


def key(n: int):
    return crypto.private_key_from_scalar(0x7000 + n)


def pub(k) -> bytes:
    return crypto.public_key_bytes(k)


class Town:
    """Simulated entities only, so nothing touches Nessie."""

    def __init__(self, deps) -> None:
        self.deps = deps
        self.shops: dict[str, tuple] = {}
        self.wallets: dict[str, dict] = {}

    def shop(self, name: str, x: int, y: int, region: str = "asheville-downtown"):
        k = key(len(self.shops) + 1)
        _, mcert, _ = registry.register_merchant(self.deps, name, pub(k), region, x, y, simulated=True, now=T0)
        self.shops[name] = (k, mcert)
        return mcert

    def resident(self, name: str, region: str = "asheville-downtown", cap: int | None = None, now: int = T0):
        k = key(100 + len(self.wallets))
        _, cert, _ = registry.register_resident(self.deps, name, pub(k), region, simulated=True, now=now)
        if cap:
            cert = registry.raise_storm_mode(self.deps, cert.cert_id, cap, now=now + 60)
        self.wallets[name] = {"key": k, "cert": cert, "k": 0, "head": genesis(cert.cert_id), "cum": 0, "hist": []}
        return cert

    def pay(self, who: str, shop: str, amount: int, ts: int, rollback: bool = False) -> Pay:
        w = self.wallets[who]
        if rollback:
            w["k"], w["head"], w["cum"] = w["hist"].pop()
        mk, mcert = self.shops[shop]
        det = Det(mcert.merchant_pub, ts.to_bytes(16, "big"), ts)
        tag = Tag(w["cert"].cert_id, w["k"] + 1, w["head"], amount, w["cum"] + amount, det.digest()).signed(w["key"])
        w["hist"].append((w["k"], w["head"], w["cum"]))
        w["k"], w["head"], w["cum"] = tag.counter, tag.tag_hash, tag.cum_cents
        pay = Pay(w["cert"], tag, det)
        settlement.ingest_items(self.deps, mcert.merchant_pub, [Item("PAY", pay)], simulated=True, now=ts + 60)
        return pay

    def contact(self, a: str, b: str, ts: int, n: int) -> None:
        pa, pb = self.shops[a][1].merchant_pub if a in self.shops else a, self.shops[b][1].merchant_pub
        with self.deps.pool.connection() as conn:
            for dev, peer in ((pa, pb), (pb, pa)):
                conn.execute(
                    """INSERT INTO contacts (contact_id, device_pub, peer_pub, ts, sent_ids, recv_ids, paired)
                       VALUES (%s, %s, %s, %s, '{}', '{}', TRUE)""",
                    (n.to_bytes(32, "big"), dev, peer, ts),
                )


def candidates(deps, kind: str) -> list[dict]:
    with deps.pool.connection() as conn:
        return all_rows(conn, "SELECT * FROM candidates WHERE kind = %s ORDER BY candidate_id", (kind,))


def test_merchant_silence_fires_on_a_silent_shop_taking_pool_money(deps):
    town = Town(deps)
    town.shop("Silent Shop", 10, 10)
    town.shop("Busy Grocer", 11, 10)
    town.shop("Busy Bakery", 12, 11)
    # The neighbors trade records all morning; the silent shop logs nothing.
    for i in range(12):
        town.contact("Busy Grocer", "Busy Bakery", T0 + i * 1200, i + 1)
    town.resident("Cheater")
    town.pay("Cheater", "Busy Grocer", 1700, T0 + HOUR)
    town.pay("Cheater", "Silent Shop", 1700, T0 + 2 * HOUR, rollback=True)  # $3 escrow + $14 pool

    with deps.pool.connection() as conn:
        rows = detectors.merchant_silence(conn, T0 + 5 * HOUR)
        again = detectors.merchant_silence(conn, T0 + 6 * HOUR)  # overlapping window: no repeat
    assert len(rows) == 1 and again == []
    f = rows[0]["features"]
    assert rows[0]["subject_id"] == town.shops["Silent Shop"][1].merchant_id.hex()
    assert f["contacts_per_hour"] == 0 and f["neighbor_median_contacts_per_hour"] == 2.0
    assert f["silence_ratio"] == 0 and f["neighbors"] == 2
    assert (f["pool_funded_count"], f["pool_funded_cents"], f["accepted_count"]) == (1, 1400, 1)
    assert f["distinct_cheater_certs"] == 1  # the double spend opened a hard case
    assert f["near_cap_share"] == 1.0
    assert f["prior_windows_flagged"] == 0
    assert set(f) >= {"paired_contact_share", "one_sided_contacts", "pool_funded_share"}


def test_busy_shop_or_no_pool_money_does_not_fire(deps):
    town = Town(deps)
    town.shop("Grocer", 10, 10)
    town.shop("Bakery", 11, 10)
    town.resident("Honest")
    town.pay("Honest", "Grocer", 1000, T0 + HOUR)  # escrow only
    with deps.pool.connection() as conn:
        assert detectors.merchant_silence(conn, T0 + 5 * HOUR) == []


def test_cap_drain_fires_on_three_shops_in_fifteen_minutes(deps):
    town = Town(deps)
    for i, name in enumerate(("A Shop", "B Shop", "C Shop")):
        town.shop(name, 30 + i, 5, region="black-mountain")
    town.resident("Stolen", region="swannanoa", cap=5000)
    t = T0 + 5 * HOUR
    town.pay("Stolen", "A Shop", 1500, t)
    town.pay("Stolen", "B Shop", 1500, t + 300)
    town.pay("Stolen", "C Shop", 1200, t + 600)  # each ingest runs the detectors
    [row] = candidates(deps, "cap_drain")
    assert row["subject_id"] == town.wallets["Stolen"]["cert"].cert_id.hex()
    assert (row["window_start"], row["window_end"]) == (t, t + 600)
    f = row["features"]
    assert (f["distinct_merchants_15m"], f["spent_15m_cents"], f["cap_cents"]) == (3, 4200, 5000)
    assert f["drain_share"] == 0.84
    assert f["home_region"] == "swannanoa" and f["regions_in_window"] == ["black-mountain"]
    assert f["region_mismatch"] is True
    assert f["hour_of_day"] == 13
    assert f["gap_since_last_activity_min"] is None
    assert f["owner_freeze_request"] is False


def test_cap_drain_needs_three_shops_and_80_percent(deps):
    town = Town(deps)
    for i, name in enumerate(("A Shop", "B Shop", "C Shop")):
        town.shop(name, 30 + i, 5, region="black-mountain")
    town.resident("Shopper", cap=5000)
    t = T0 + 5 * HOUR
    town.pay("Shopper", "A Shop", 1000, t)
    town.pay("Shopper", "B Shop", 1000, t + 300)
    town.pay("Shopper", "C Shop", 1000, t + 600)  # 60% of the cap
    with deps.pool.connection() as conn:
        assert detectors.cap_drain_for_payment(conn, town.wallets["Shopper"]["cert"].cert_id, t + 600) is None
    assert candidates(deps, "cap_drain") == []


def test_run_incremental_creates_and_publishes_cap_drain(deps, monkeypatch):
    seen = []
    monkeypatch.setattr(deps.events, "publish", lambda e, d: seen.append(e))
    town = Town(deps)
    for i, name in enumerate(("A Shop", "B Shop", "C Shop")):
        town.shop(name, 30 + i, 5, region="black-mountain")
    town.resident("Stolen", region="swannanoa", cap=5000)
    t = T0 + 5 * HOUR
    for i, shop in enumerate(("A Shop", "B Shop", "C Shop")):
        town.pay("Stolen", shop, 1400, t + i * 300)  # ingest runs the detectors each time
    assert [c["kind"] for c in candidates(deps, "cap_drain")] == ["cap_drain"]
    assert "candidate" in seen


def test_region_dark_fires_when_certs_expire_and_no_one_uploads(deps):
    town = Town(deps)
    for i in range(4):
        town.resident(f"Dark {i}", region="swannanoa")
    now = T0 + 62 * HOUR  # every cert expires within 12 h; nobody in swannanoa ever uploaded
    with deps.pool.connection() as conn:
        conn.execute(
            """INSERT INTO weather_alerts (alert_id, region_id, event, severity, onset, expires, source)
               VALUES ('a1', 'swannanoa', 'Flash Flood Warning', 'Severe', %s, %s, 'replayed')""",
            (T0, T0 + 80 * HOUR),
        )
        rows = detectors.region_dark(conn, now)
        assert detectors.region_dark(conn, now + HOUR) == []  # same dark stretch
    f = rows[0]["features"]
    assert rows[0]["subject_id"] == "swannanoa"
    assert (f["active_certs"], f["expiring_12h_share"], f["hours_since_last_upload"]) == (4, 1.0, 62.0)
    assert f["active_alerts"] == [{"event": "Flash Flood Warning", "severity": "Severe", "source": "replayed"}]


def test_region_with_a_recent_upload_is_not_dark(deps):
    town = Town(deps)
    town.resident("Lit", region="swannanoa")
    with deps.pool.connection() as conn:
        conn.execute(
            """INSERT INTO uploads (device_pub, region_id, item_count, simulated, received_at)
               VALUES (%s, 'swannanoa', 1, TRUE, to_timestamp(%s))""",
            (b"\x02" * 33, T0 + 40 * HOUR),
        )
        assert detectors.region_dark(conn, T0 + 62 * HOUR) == []
        assert scalar(conn, "SELECT count(*) FROM candidates") == 0
