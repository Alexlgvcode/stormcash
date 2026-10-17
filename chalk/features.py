"""StormCash feature classes (spec §15.1), served online to StormDesk (§15.2).

They mirror the detector features in §13 and are computed by the SQL resolvers
in resolvers/ against the hosted Postgres, plus one Python resolver for live
NWS alerts (resolvers/nws.py).

Time is simulated time (§16): every class has an `as_of` feature, in Unix
seconds, that its windows end at. By default a SQL resolver sets it to the
server's latest sync (`max(uploads.received_at)`), which is "now" for both the
seeded town and real phones. Pass it as a query input to look at another
moment, e.g. a candidate's `window_end`. Wall-clock `now` is not used: the
seeded town is days old by the time it's demoed.
"""

from chalk.features import features


@features
class Merchant:
    id: str  # merchant_id, lowercase hex
    as_of: int  # end of the windows, sim-clock Unix seconds
    name: str
    region_id: str
    simulated: bool
    # merchant_silence (§13.1): the 6 h ending at as_of.
    contacts_per_hour_6h: float
    neighbors_6h: int  # shops within 3 grid cells
    neighbor_median_contacts_6h: float
    silence_ratio_6h: float
    accepted_count_6h: int
    pool_funded_count_6h: int
    pool_funded_cents_6h: int
    pool_funded_share_6h: float | None  # None without accepted payments
    distinct_cheater_certs_6h: int
    near_cap_share_6h: float | None
    paired_contact_share_6h: float | None  # None without contacts in the shop's own log
    one_sided_contacts_6h: int
    prior_windows_flagged: int


@features
class Certificate:
    id: str  # cert_id, lowercase hex
    as_of: int
    status: str
    storm_mode: bool
    home_region: str | None
    # cap_drain (§13.2): the 15 minutes ending at as_of.
    cap_cents: int | None  # the cap of the version in force at as_of
    spent_15m_cents: int
    distinct_merchants_15m: int
    drain_share_15m: float | None
    regions_15m: list[str]
    region_mismatch_15m: bool
    minutes_since_storm_mode: float | None
    gap_since_last_activity_min: float | None
    hour_of_day: int  # Asheville local time (EDT)


@features
class Region:
    id: str  # e.g. 'swannanoa'
    as_of: int
    name: str
    county: str
    # region_dark (§13.3), at as_of.
    active_certs: int
    expiring_12h_share: float | None
    hours_since_last_upload: float | None
    merchants_open_6h: int
    # Weather: replayed rows active at as_of, live NWS alerts now, and which one
    # active_alert_events came from (§0 rule 3: replayed is labeled replayed).
    replayed_alert_events: list[str]
    live_alert_events: list[str]
    nws_reachable: bool
    active_alert_events: list[str]
    alert_source: str  # 'live' | 'replayed'
