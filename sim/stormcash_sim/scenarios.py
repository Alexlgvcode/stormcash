"""Scenarios and traps with ground truth (spec §16.4).

`plant(sim)` assigns roles, windows and scripted events on top of the honest
town and returns the labels evals score against. Every scenario runs through
the same protocol and server code as the rest of the town; scripts only decide
who goes where and when. Choices come from their own seeded stream so the
honest town is unchanged by planting.

Scripted double spends pay first at the Downtown Shelter (good uplink, forced
to upload) so the rolled-back re-spend somewhere else needs guarantee-pool
money, which is what the soft signals look for.
"""

from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass, field

from psycopg.types.json import Jsonb

from . import town

REMOTE_SPOTS = ((0, 1), (0, 22))  # west-asheville map edge (trap_remote_shop)
SCRIPTED_AMOUNT = 3500  # of a $50 cap: the re-spend needs $20 of pool money
DARK_REGION, QUIET_REGION = "swannanoa", "black-mountain"


@dataclass
class Label:
    subject_type: str  # merchant | cert | region
    subject_id: str  # merchant_id hex | cert_id hex | region_id
    name: str
    scenario: str
    expected_kind: str  # merchant_silence | cap_drain | region_dark | hard_case | none
    expected_action: str  # hold_pool_payout | freeze_cert | dispatch_relay | none
    hard_rules: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Plan:
    labels: list[Label] = field(default_factory=list)
    cheaters: list[int] = field(default_factory=list)  # resident idx of every double spender


def place_remote_shops(specs: list[town.ShopSpec]) -> list[town.ShopSpec]:
    """Move two West Asheville shops to the map edge, away from any cluster."""
    out, moved = [], 0
    for spec in specs:
        if spec.region == "west-asheville" and moved < len(REMOTE_SPOTS):
            x, y = REMOTE_SPOTS[moved]
            spec = dataclasses.replace(spec, x=x, y=y)
            moved += 1
        out.append(spec)
    return out


def plant(sim) -> Plan:
    plan = Plan()
    rng = random.Random(sim.p.seed * 7919 + 1)
    H = sim.tick_of
    end = sim.p.hours * 60
    shops = {s.name: s for s in sim.shops}
    shelter, corner = shops["Downtown Shelter"], shops["Corner Store"]
    remote = [s for s in sim.shops if (s.x, s.y) in REMOTE_SPOTS]
    special = {shelter.idx, corner.idx, *(s.idx for s in remote)}
    clustered = [
        s for s in sim.shops
        if s.idx not in special and s.region in ("asheville-downtown", "west-asheville")
        and sum(1 for o in sim.shops if o is not s and town.distance(s.x, s.y, o.x, o.y) <= 3) >= 2
    ]
    pool = list(sim.residents)
    rng.shuffle(pool)
    taken: set[int] = set()

    def residents(n: int, cond=lambda r: True) -> list:
        chosen = [r for r in pool if r.idx not in taken and cond(r)][:n]
        assert len(chosen) == n, "not enough residents for the scenarios"
        taken.update(r.idx for r in chosen)
        return chosen

    def label_cert(r, scenario, kind, action, rules=(), note=""):
        plan.labels.append(Label("cert", r.cert.cert_id.hex(), r.name, scenario, kind, action, list(rules), note))

    def label_shop(s, scenario, kind, action, rules=(), note=""):
        plan.labels.append(Label("merchant", s.mcert.merchant_id.hex(), s.name, scenario, kind, action, list(rules),
                                 note))

    def cheater(r):
        r.storm, r.scripted, r.gossips_own_tags, r.role = True, True, False, "double_spender"
        plan.cheaters.append(r.idx)

    def scripted_double_spend(r, victim, first_h: float, respend_h: float, upload_h: float, scenario: str,
                              amount: int = SCRIPTED_AMOUNT):
        cheater(r)
        state = {}

        def first(tick):
            state["snapshot"] = r.snapshot()
            sim.pay(r, shelter, sim._now(tick), amount)
            sim.upload(shelter, sim._now(tick))  # the honest payment settles first, from escrow

        def again(tick):
            sim.respend(r, victim, sim._now(tick), state["snapshot"], amount, "reuse", scenario)

        sim.at(H(first_h), first)
        sim.at(H(respend_h), again)
        sim.at(H(upload_h), lambda tick: sim.upload(victim, sim._now(tick)))
        label_cert(r, "double_spender", "hard_case", "freeze_cert", ["SAME_COUNTER"],
                   f"scripted for {scenario}; frozen automatically")

    # double_spender ×6: organic rollbacks 1–3 shops later, half reuse a counter, half skip one.
    for r in residents(6):
        r.storm, r.role, r.gossips_own_tags, r.cheats_left = True, "double_spender", False, 2
        r.gossip_off.append((0, end))  # a cheating phone doesn't relay anything
        plan.cheaters.append(r.idx)
        label_cert(r, "double_spender", "hard_case", "freeze_cert",
                   ["SAME_COUNTER" if r.idx % 2 == 0 else "TOTAL_BACKWARDS"], "frozen automatically when caught")

    # colluder ×2: gossip and uplink off for 6 h, the app skips C2/C6, takes a pool-funded double spend.
    other_colluder = clustered[rng.randrange(len(clustered))]
    for shop, start_h in ((corner, 26.0), (other_colluder, 50.0)):
        shop.lenient = True
        window = (H(start_h), H(start_h + 6))
        shop.gossip_off.append(window)
        shop.uplink_off.append(window)
        [r] = residents(1)
        scripted_double_spend(r, shop, start_h + 0.5, start_h + 2, start_h + 6.5, "colluder")
        label_shop(shop, "colluder", "merchant_silence", "hold_pool_payout",
                   ["MERCHANT_KNEW"] if shop is corner else [], "silent 6 h while taking pool money")

    # Planted R5 (§16.4, seed 42 demo): a paired contact delivers the conflicting tag to Corner Store,
    # then Corner Store accepts the rolled-back payment anyway and logs that it held the tag.
    d, courier = residents(1)[0], residents(1)[0]
    cheater(d)
    courier.scripted, courier.role = True, "courier"
    label_cert(d, "double_spender", "hard_case", "freeze_cert", ["SAME_COUNTER"], "planted MERCHANT_KNEW at Corner Store")
    r5 = {}

    def r5_first(tick):
        r5["snapshot"] = d.snapshot()
        sim.pay(d, shelter, sim._now(tick), 3000)

    sim.at(H(34), r5_first)
    sim.at(H(34) + 10, lambda tick: sim.sync(courier, shelter, sim._now(tick)))  # the courier picks up the tag
    sim.at(H(34) + 15, lambda tick: sim.upload(shelter, sim._now(tick)))  # (an upload drops receipted items)
    sim.at(H(34) + 30, lambda tick: sim.sync(courier, corner, sim._now(tick)))
    sim.at(H(34) + 35, lambda tick: sim.respend(d, corner, sim._now(tick), r5["snapshot"], 3000, "reuse",
                                                "colluder_merchant_knew"))
    sim.at(H(35), lambda tick: (sim.upload(corner, sim._now(tick)), sim.upload(courier, sim._now(tick))))

    # stolen_phone ×2: idle phone drains ≥ 80 % at 3 shops in 15 min, away from home.
    west_shops = [s for s in sim.shops if s.region == "west-asheville" and s.idx not in special][:3]
    for r, theft_h in zip(residents(2, lambda r: r.region != "west-asheville"), (40.0, 44.0), strict=True):
        r.storm, r.scripted, r.role = True, True, "stolen_phone"

        def spree(tick, r=r):
            for i, (shop, amount) in enumerate(zip(west_shops, (1500, 1500, 1300), strict=True)):
                sim.pay(r, shop, sim._now(tick + 4 * i), amount)

        sim.at(H(theft_h), spree)
        sim.at(H(theft_h + 1), lambda tick: [sim.upload(s, sim._now(tick)) for s in west_shops])
        label_cert(r, "stolen_phone", "cap_drain", "freeze_cert", note="idle since T0, drained in another region")

    # dark_region: Swannanoa has no uplink for 60 h during an active (replayed) alert.
    for dev in sim.devices:
        if dev.region == DARK_REGION:
            dev.uplink_off.append((H(6), H(66)))
    with sim.deps.pool.connection() as conn:
        conn.execute(
            """INSERT INTO weather_alerts (alert_id, region_id, event, severity, onset, expires, source, raw)
               VALUES (%s, %s, 'Flash Flood Warning', 'Severe', %s, %s, 'replayed', %s)
               ON CONFLICT (alert_id) DO NOTHING""",
            (f"sim-{sim.p.seed}-{DARK_REGION}", DARK_REGION, sim.t0, sim._now(end + H(12)),
             Jsonb({"note": "simulated replay for the town simulator"})),
        )
    plan.labels.append(Label("region", DARK_REGION, "Swannanoa", "dark_region", "region_dark", "dispatch_relay",
                             note="no uplink for 60 h during a flash flood warning (replayed)"))

    # trap_remote_shop ×2: honest edge shop, few contacts, one pool-funded payment as a victim.
    for shop, h in zip(remote, (14.0, 38.0), strict=True):
        [r] = residents(1)
        scripted_double_spend(r, shop, h, h + 1.5, h + 2.5, "trap_remote_shop")
        label_shop(shop, "trap_remote_shop", "none", "none", note="honest shop at the map edge, a victim")

    # trap_victim_shop ×2: honest shop shut 4 h (generator out), then victimized once.
    victims = [s for s in clustered if s is not other_colluder][:2]
    for shop, h in zip(victims, (20.0, 46.0), strict=True):
        shop.closed.append((H(h), H(h + 4)))
        [r] = residents(1)
        scripted_double_spend(r, shop, h + 2, h + 4.3, h + 5, "trap_victim_shop")
        label_shop(shop, "trap_victim_shop", "none", "none", note="briefly closed, then a victim")

    # trap_stockup ×3: right after Storm Mode, ≥ 80 % at 3 home-region shops within 30 min.
    for r in residents(3, lambda r: r.region == "asheville-downtown"):
        r.storm, r.scripted, r.role = True, True, "stockup"
        home = sorted((s for s in sim.shops if s.region == r.region and s.idx not in special),
                      key=lambda s: town.distance(r.x, r.y, s.x, s.y))[:3]
        start = H(sim.p.storm_at_h) + 10

        def stock_up(tick, r=r, home=home):
            for i, (shop, amount) in enumerate(zip(home, (1500, 1400, 1300), strict=True)):
                sim.pay(r, shop, sim._now(tick + 5 * i), amount)
            r.scripted = False
            sim._push(sim._next_trip(tick + 30), "trip", r.idx)

        sim.at(start, stock_up)
        sim.at(start + 40, lambda tick, home=home: [sim.upload(s, sim._now(tick)) for s in home])
        label_cert(r, "trap_stockup", "none", "none", note="honest stock-up right after Storm Mode")

    # trap_clock_drift ×2: honest phones 8 minutes fast.
    for r in residents(2):
        r.clock_offset, r.role = 480, "clock_drift"
        label_cert(r, "trap_clock_drift", "none", "none", note="phone clock 8 min off; no hard rule fires")

    # trap_quiet_region: no uploads from Black Mountain after T+12 h, and no alert.
    for dev in sim.devices:
        if dev.region == QUIET_REGION:
            dev.uplink_off.append((H(12), end))
    plan.labels.append(Label("region", QUIET_REGION, "Black Mountain", "trap_quiet_region", "none", "none",
                             note="quiet but no alert; `info` at most"))
    return plan
