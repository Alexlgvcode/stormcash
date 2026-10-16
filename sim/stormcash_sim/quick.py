"""Quick in-memory re-sim for the Town tab sliders (spec §16.6).

Same town layout, trips, gossip and relay rules as engine.py, but payments are
plain ids instead of signed objects and nothing touches the database, so a
72 h town runs in well under a second. It answers "how often does this work?"
as adoption, foot traffic (p_link) and relay density (p_uplink) change:

- share of double spends refused offline (the shop already held the tag),
- share caught at settlement (both payments reached the server by the end),
- mean guarantee-pool loss per cheater (spending beyond the cap),
- median hours for an honest payment to reach the server.

It is a model, not the live data: the UI labels it "simulated".
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import asdict, dataclass

from . import town

HOURS = 72
CAPS = (2000, 5000)  # always-on, Storm Mode
STORM_SHARE = 0.7
CHEATER_SHARE = 0.08  # more cheaters than the seeded town, so the shares are stable
RUNS = 5  # seeds pooled per answer, to steady the shares
CARRY_AFTER_SERVER_MIN = 60
DAY_START_MIN, DAY_END_MIN = 7 * 60, 21 * 60


@dataclass(frozen=True)
class QuickParams:
    seed: int = 42
    adoption: float = 0.6
    p_link: float = 0.6
    p_uplink: float = 0.03
    residents: int = 400
    shelter_uplink: float = 0.5
    trip_every_min: float = 240.0


class _Phone:
    __slots__ = ("x", "y", "items", "known", "p_up", "region", "cap", "spent", "cheater", "armed", "shop")

    def __init__(self, x, y, p_up, region, cap=0):
        self.x, self.y, self.p_up, self.region, self.cap = x, y, p_up, region, cap
        self.items: set[int] = set()  # carried for relay; dropped an hour after the server has them
        self.known: set[int] = set()  # tags kept for C6 (§10.4 keeps them ~72 h), never dropped here
        self.spent = 0
        self.cheater = False
        self.armed: tuple | None = None
        self.shop = None


def run_quick(params: QuickParams) -> dict:
    """Pool RUNS seeded towns (seed, seed+1, ...) into one answer."""
    runs = [_run_one(params, params.seed + k) for k in range(RUNS)]
    attempts = sum(r["attempts"] for r in runs)
    losses = [x for r in runs for x in r["losses"]]
    delays = [x for r in runs for x in r["delays"]]
    return {
        "params": asdict(params),
        "runs": RUNS,
        "residents": round(statistics.mean(r["residents"] for r in runs)),
        "cheaters": sum(len(r["losses"]) for r in runs),
        "double_spend_attempts": attempts,
        "share_refused_offline": round(sum(r["refused"] for r in runs) / attempts, 4) if attempts else None,
        "share_caught_at_settlement": round(sum(r["caught"] for r in runs) / attempts, 4) if attempts else None,
        "mean_loss_per_cheater_cents": round(statistics.mean(losses)) if losses else None,
        "median_hours_to_settlement": round(statistics.median(delays), 2) if delays else None,
        "payments": sum(r["payments"] for r in runs),
    }


def _run_one(params: QuickParams, seed: int) -> dict:
    rng = random.Random(seed)
    shops = [
        _Phone(s.x, s.y, 1 - (1 - s.uplink_per_hour) ** (1 / 60), s.region)
        for s in town.build_shops(rng, params.p_uplink, params.shelter_uplink)
    ]
    specs = [r for r in town.build_residents(rng, params.residents) if rng.random() < params.adoption]
    p_up = 1 - (1 - params.p_uplink) ** (1 / 60)
    people = []
    for spec in specs:
        p = _Phone(spec.x, spec.y, p_up, spec.region, CAPS[1] if rng.random() < STORM_SHARE else CAPS[0])
        p.cheater = rng.random() < CHEATER_SHARE
        people.append(p)
    neighbors = {id(s): [o for o in shops if town.distance(s.x, s.y, o.x, o.y) <= 2] for s in shops}
    weights = {id(p): [1 / (1 + town.distance(p.x, p.y, s.x, s.y)) ** 2 for s in shops] for p in people}

    next_id = 0
    pay_time: dict[int, int] = {}  # honest payment -> minute
    server: dict[int, int] = {}  # id -> minute it reached the server
    attempts: list[tuple[int, int | None, bool]] = []  # (first id, second id or None, refused offline)
    accepted_by: dict[int, int] = {}  # cheater idx -> cents accepted in total
    events: list[tuple[int, int, int]] = []  # (minute, kind 0=trip 1=leave, person idx)
    last_sync: dict[tuple[int, int], int] = {}
    present: dict[int, list[_Phone]] = {}

    def next_trip(t: int) -> int:
        t += max(1, int(rng.expovariate(1 / params.trip_every_min)))
        minute = t % 1440
        if minute < DAY_START_MIN:
            t += DAY_START_MIN - minute + rng.randrange(120)
        elif minute >= DAY_END_MIN:
            t += 1440 - minute + DAY_START_MIN + rng.randrange(120)
        return t

    for i, _ in enumerate(people):
        events.append((next_trip(0), 0, i))
    events.sort()

    def pay(i: int, p: _Phone, shop: _Phone, t: int) -> None:
        nonlocal next_id
        amount = round(min(45.0, max(3.0, rng.lognormvariate(math.log(12), 0.6))) * 100)
        if p.armed is not None:  # roll back and spend the same money again here
            first, first_amount, countdown = p.armed
            if countdown > 1:
                p.armed = (first, first_amount, countdown - 1)
            else:
                p.armed = None
                if first in shop.known:
                    attempts.append((first, None, True))
                    return
                next_id += 1
                shop.items.add(next_id)
                shop.known.add(next_id)
                attempts.append((first, next_id, False))
                accepted_by[i] = accepted_by.get(i, 0) + first_amount
                return
        amount = min(amount, p.cap - p.spent)
        if amount < 300:
            return
        next_id += 1
        p.spent += amount
        shop.items.add(next_id)
        shop.known.add(next_id)
        pay_time[next_id] = t
        if p.cheater:
            accepted_by[i] = accepted_by.get(i, 0) + amount
            if p.armed is None:
                p.armed = (next_id, amount, rng.randint(1, 3))
        else:
            p.items.add(next_id)  # an honest wallet gossips its own tags

    def prune(d: _Phone, t: int) -> None:
        d.items = {k for k in d.items if t - server.get(k, t) < CARRY_AFTER_SERVER_MIN}

    for t in range(HOURS * 60):
        while events and events[0][0] <= t:
            _, kind, i = events.pop(0)
            p = people[i]
            if kind == 0:
                shop = rng.choices(shops, weights[id(p)])[0]
                travel = max(2, math.ceil(town.distance(p.x, p.y, shop.x, shop.y) / 0.5))
                p.shop = shop
                present.setdefault(id(shop), []).append(p)
                pay(i, p, shop, t + travel)
                _insert(events, (t + travel + rng.randint(5, 12), 1, i))
            else:
                present[id(p.shop)].remove(p)
                p.shop = None
                _insert(events, (next_trip(t), 0, i))
        for shop in shops:
            here = present.get(id(shop))
            if not here:
                continue
            nearby = [r for s in neighbors[id(shop)] for r in present.get(id(s), ())]
            for p in here:
                if p.cheater:
                    continue  # a cheating phone relays nothing
                for other in [*neighbors[id(shop)], *(o for o in nearby if o is not p and not o.cheater)]:
                    key = (min(id(p), id(other)), max(id(p), id(other)))
                    if t - last_sync.get(key, -60) < 60 or rng.random() >= params.p_link:
                        continue
                    last_sync[key] = t
                    prune(p, t)
                    prune(other, t)
                    union = p.items | other.items
                    p.items, other.items = set(union), set(union)
                    p.known |= union
                    other.known |= union
        for d in (*shops, *people):
            if d.items and rng.random() < d.p_up:
                for k in d.items:
                    server.setdefault(k, t)

    caught = sum(1 for a, b, refused in attempts if not refused and a in server and b in server)
    refused = sum(1 for _, _, r in attempts if r)
    cheaters = [i for i, p in enumerate(people) if p.cheater]
    losses = [max(0, accepted_by.get(i, 0) - people[i].cap) for i in cheaters]
    delays = [(server[k] - t) / 60 for k, t in pay_time.items() if k in server]
    return {"residents": len(people), "attempts": len(attempts), "refused": refused, "caught": caught,
            "losses": losses, "delays": delays, "payments": len(pay_time)}


def _insert(events: list, item: tuple) -> None:
    lo, hi = 0, len(events)
    while lo < hi:
        mid = (lo + hi) // 2
        if events[mid] < item:
            lo = mid + 1
        else:
            hi = mid
    events.insert(lo, item)
