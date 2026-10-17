"""The simulation loop (spec §16.2, §16.3).

Real P-256 keys and signatures, the real merchant checks (rules.merchant_check)
and the real server ingest (settlement.ingest_items): the town is checked by
exactly the same code as the phones. Every row is simulated=true and money is
ledger-only; the Deps passed in must have Nessie switched off.

Simplifications, all deliberate:
- Only adopters are modelled. Residents make trips to shops; phones meet when
  they are within 2 cells of each other at a shop. Shops don't link to each
  other directly: customers carry records between them (§24 Q5).
- A pair of phones syncs at most once per `pair_cooldown_min`.
- A carried item is dropped one hour after the server first received it,
  standing in for the RCPT spreading back down (§10.4).
- POLICY travels as device state (the highest version wins on sync) rather than
  as items.

Scenario behaviour (§16.4) plugs in through device windows (gossip off,
uplink off, shop closed), clock offsets, lenient merchant apps, double
spenders' wallets and scripted events; see scenarios.py.
"""

from __future__ import annotations

import hashlib
import heapq
import math
import random
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from stormcash import registry
from stormcash.db import scalar
from stormcash.deps import Deps
from stormcash.protocol import crypto, rules
from stormcash.protocol.objects import (
    Cert,
    Det,
    Dlog,
    Item,
    Mcert,
    Pay,
    Policy,
    Req,
    Tag,
    contact_id,
    device_short_id,
    dlog_genesis,
    genesis,
    id8,
    item_id,
)
from stormcash.settlement import ingest_items

from . import town

TICK_S = 60
LOCAL_UTC_OFFSET_S = -4 * 3600  # Asheville, EDT
DAY_START_MIN, DAY_END_MIN = 7 * 60, 21 * 60
CONTACT_RANGE = 2
CARRY_AFTER_SERVER_S = 3600
STORM_CAP_CENTS = 5000
MIN_PAYMENT_CENTS = 300
GOSSIP_KINDS = ("TAG", "PAY", "PROOF")
LENIENT_SKIPS = ("C2", "C6")  # what a modified (colluding) merchant app ignores


@dataclass
class Params:
    seed: int = 42
    hours: int = 72
    residents: int = 400
    adoption: float = 0.6
    storm_share: float = 0.7
    storm_at_h: float = 2.0
    p_link: float = 0.6
    p_uplink: float = 0.03
    shelter_uplink: float = 0.5
    trip_every_min: float = 240.0
    pair_cooldown_min: int = 60
    start: int | None = None  # Unix seconds of T0; default: now − hours, on the hour
    scenarios: bool = True  # plant the §16.4 scenarios and traps


def derive_key(seed: int, name: str):
    digest = hashlib.sha256(f"stormcash-sim/{seed}/{name}".encode()).digest()
    return crypto.private_key_from_scalar(int.from_bytes(digest, "big") % (crypto.N - 1) + 1)


def derive_id(seed: int, name: str) -> bytes:
    """A 16-byte id fixed by the seed, so the same seed gives the same town."""
    return hashlib.sha256(f"stormcash-sim-id/{seed}/{name}".encode()).digest()[:16]


def _in(windows: list[tuple[int, int]], tick: int) -> bool:
    return any(start <= tick < end for start, end in windows)


class Device:
    def __init__(self, idx: int, name: str, key, region: str, x: int, y: int, uplink_per_hour: float) -> None:
        self.idx, self.name, self.key, self.region, self.x, self.y = idx, name, key, region, x, y
        self.pub = crypto.public_key_bytes(key)
        self.short = device_short_id(self.pub)
        self.log: list[Dlog] = []
        self.carry: dict[bytes, Item] = {}  # item id -> item (with its path)
        self.tags: dict[bytes, dict[bytes, Tag]] = {}  # cert_id -> tag_hash -> tag
        self.policy: Policy | None = None
        self.p_uplink_tick = 1 - (1 - uplink_per_hour) ** (1 / 60)
        self.clock_offset = 0  # seconds this phone's clock is off (trap_clock_drift)
        self.gossip_off: list[tuple[int, int]] = []  # tick windows with Multipeer off
        self.uplink_off: list[tuple[int, int]] = []  # tick windows with no internet

    def gossip_on(self, tick: int) -> bool:
        return not _in(self.gossip_off, tick)

    def hold(self, item: Item, item_key: bytes) -> None:
        self.carry.setdefault(item_key, item)
        self.learn(item)

    def receive(self, item_key: bytes, item: Item, now: int) -> None:
        held = self.carry.get(item_key)
        if held is None or (held.kind == "TAG" and item.kind == "PAY"):  # a PAY supersedes its TAG
            self.carry[item_key] = Item(item.kind, item.body, item.path + ((self.short, now),))
            self.learn(item)

    def learn(self, item: Item) -> None:
        if item.kind == "PAY":
            self._tag(item.body.tag)
        elif item.kind == "TAG":
            self._tag(item.body)
        elif item.kind == "PROOF":
            self._tag(item.body.a)
            self._tag(item.body.b)

    def _tag(self, tag: Tag) -> None:
        self.tags.setdefault(tag.cert_id, {})[tag.tag_hash] = tag

    def append_log(self, now: int, **fields) -> Dlog:
        ts = now + self.clock_offset
        prev = self.log[-1].entry_hash if self.log else dlog_genesis(self.pub)
        entry = Dlog(device_pub=self.pub, seq=len(self.log) + 1, prev_hash=prev, ts=ts, **fields).signed(self.key)
        self.log.append(entry)
        self.hold(Item("DLOG", entry, ((self.short, now),)), entry.entry_hash)
        return entry


def _wants(d: Device, key: bytes, item: Item) -> bool:
    """Would `d` request this item in a sync? Yes if it lacks the id, or holds
    only the TAG and the peer offers the PAY (§10.3)."""
    held = d.carry.get(key)
    return held is None or (held.kind == "TAG" and item.kind == "PAY")


class Shop(Device):
    mcert: Mcert

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lenient = False  # colluder: the app skips C2 and C6
        self.closed: list[tuple[int, int]] = []  # tick windows the shop is shut (generator out)

    def open(self, tick: int) -> bool:
        return not _in(self.closed, tick)

    def gossip_on(self, tick: int) -> bool:
        return super().gossip_on(tick) and self.open(tick)


class Resident(Device):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cert: Cert | None = None
        self.counter, self.head, self.cum = 0, b"", 0
        self.at_shop: Shop | None = None
        self.storm = False
        self.role: str | None = None
        self.scripted = False  # moves only when a scenario script says so
        self.gossips_own_tags = True  # a cheating wallet keeps its tags to itself
        self.cheats_left = 0  # organic double spender: rollbacks still to do
        self.armed: dict | None = None  # {"snapshot", "countdown", "mode"}

    @property
    def remaining(self) -> int:
        return self.cert.cap_cents - self.cum

    def snapshot(self) -> tuple[int, bytes, int]:
        return self.counter, self.head, self.cum


@dataclass
class Attempt:
    """One double-spend attempt (the rolled-back payment)."""

    cheater: int
    cert_id: bytes
    tag_hash: bytes
    shop: int
    at: int
    mode: str
    scenario: str
    refused: str | None  # failed check, or None if the shop accepted it


@dataclass
class Stats:
    payments: int = 0
    accepted: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    out_of_money: int = 0
    contacts: int = 0
    uploads: int = 0
    items_uploaded: int = 0
    pay_time: dict[bytes, int] = field(default_factory=dict)  # tag_hash -> accepted at
    settle_time: dict[bytes, int] = field(default_factory=dict)  # tag_hash -> first reached the server
    attempts: list[Attempt] = field(default_factory=list)


class Sim:
    def __init__(self, deps: Deps, params: Params) -> None:
        if deps.nessie is not None:
            raise ValueError("the simulator must run with Nessie switched off (ledger-only money)")
        self.deps, self.p = deps, params
        self.rng = random.Random(params.seed)
        hours = params.hours
        self.t0 = params.start if params.start is not None else (int(time.time()) // 3600 - hours) * 3600
        self.server_pub = deps.settings.server_pub
        self.shops: list[Shop] = []
        self.residents: list[Resident] = []
        self.devices: list[Device] = []
        self.stats = Stats()
        self.server_has: dict[bytes, int] = {}  # receipted id -> when
        self.server_tags: set[bytes] = set()  # TAGs stored without their PAY yet
        self.events: list[tuple[int, int, str, int]] = []
        self.seq = 0
        self.scripts: dict[int, Callable[[int], None]] = {}
        self.last_sync: dict[tuple[int, int], int] = {}
        self.present: dict[int, list[Resident]] = {}  # shop idx -> residents there
        self.plan = None  # scenarios.Plan once planted
        self.progress: float | None = None  # share of ticks done, for the seed-town status

    # Setup -----------------------------------------------------------------------------

    def setup(self) -> None:
        p, rng = self.p, self.rng
        shop_specs = town.build_shops(rng, p.p_uplink, p.shelter_uplink)
        adopters = [r for r in town.build_residents(rng, p.residents) if rng.random() < p.adoption]
        if p.scenarios:
            from . import scenarios

            shop_specs = scenarios.place_remote_shops(shop_specs)
        first_key = derive_key(p.seed, shop_specs[0].name)
        with self.deps.pool.connection() as conn:
            if scalar(conn, "SELECT 1 FROM merchants WHERE merchant_pub = %s",
                      (crypto.public_key_bytes(first_key),)):
                raise RuntimeError(f"seed {p.seed} already ran in this database; reset the demo first")

        for spec in shop_specs:
            shop = Shop(len(self.devices), spec.name, derive_key(p.seed, spec.name), spec.region, spec.x, spec.y,
                        spec.uplink_per_hour)
            self.shops.append(shop)
            self.devices.append(shop)
        for spec in adopters:
            r = Resident(len(self.devices), spec.name, derive_key(p.seed, spec.name), spec.region, spec.x, spec.y,
                         p.p_uplink)
            self.residents.append(r)
            self.devices.append(r)
        # One transaction for the whole town: a round trip per entity is slow on a hosted DB.
        mcerts, certs = registry.register_simulated(
            self.deps,
            [dict(display_name=s.name, merchant_pub=s.pub, region_id=s.region, x=s.x, y=s.y,
                  merchant_id=derive_id(p.seed, s.name)) for s in self.shops],
            [dict(display_name=r.name, holder_pub=r.pub, region_id=r.region, cert_id=derive_id(p.seed, r.name))
             for r in self.residents],
            now=self.t0,
        )
        for shop, mcert in zip(self.shops, mcerts, strict=True):
            shop.mcert = mcert
        for r, cert in zip(self.residents, certs, strict=True):
            r.cert = cert
            r.head = genesis(r.cert.cert_id)
            r.storm = rng.random() < p.storm_share
        self.neighbors = {
            s.idx: [o for o in self.shops if town.distance(s.x, s.y, o.x, o.y) <= CONTACT_RANGE]
            for s in self.shops
        }
        if p.scenarios:
            from . import scenarios

            self.plan = scenarios.plant(self)
        self._push(int(p.storm_at_h * 60), "storm", -1)
        for r in self.residents:
            if not r.scripted:
                self._push(self._next_trip(0), "trip", r.idx)

    # Events ------------------------------------------------------------------------------

    def _push(self, tick: int, kind: str, idx: int) -> None:
        self.seq += 1
        heapq.heappush(self.events, (tick, self.seq, kind, idx))

    def at(self, tick: int, fn: Callable[[int], None]) -> None:
        """Run a scenario script at a tick (with the tick as argument)."""
        self.seq += 1
        self.scripts[self.seq] = fn
        heapq.heappush(self.events, (tick, self.seq, "script", self.seq))

    def _local_minute(self, tick: int) -> int:
        return ((self.t0 + tick * TICK_S + LOCAL_UTC_OFFSET_S) // 60) % 1440

    def _next_trip(self, tick: int) -> int:
        t = tick + max(1, int(self.rng.expovariate(1 / self.p.trip_every_min)))
        minute = self._local_minute(t)
        if minute < DAY_START_MIN:
            t += DAY_START_MIN - minute + self.rng.randrange(120)
        elif minute >= DAY_END_MIN:
            t += 1440 - minute + DAY_START_MIN + self.rng.randrange(120)
        return t

    def _now(self, tick: int) -> int:
        return self.t0 + tick * TICK_S

    def tick_of(self, hours: float) -> int:
        return int(hours * 60)

    def _handle(self, tick: int, kind: str, idx: int) -> None:
        if kind == "script":
            self.scripts.pop(idx)(tick)
            return
        if kind == "storm":
            storm = [r for r in self.residents if r.storm]
            certs = registry.raise_storm_mode_many(self.deps, [r.cert.cert_id for r in storm], STORM_CAP_CENTS,
                                                   now=self._now(tick))
            for r, cert in zip(storm, certs, strict=True):
                r.cert = cert
            return
        r = self.devices[idx]
        assert isinstance(r, Resident)
        if kind == "trip":
            if r.scripted:
                return
            shops = [s for s in self.shops if s.open(tick)]
            weights = [1 / (1 + town.distance(r.x, r.y, s.x, s.y)) ** 2 for s in shops]
            shop = self.rng.choices(shops, weights)[0]
            travel = max(2, math.ceil(town.distance(r.x, r.y, shop.x, shop.y) / 0.5))
            r.at_shop = None
            self._push(tick + travel, f"arrive:{shop.idx}", r.idx)
        elif kind.startswith("arrive:"):
            shop = self.devices[int(kind.split(":")[1])]
            r.at_shop = shop
            self.present.setdefault(shop.idx, []).append(r)
            self.visit(r, shop, tick)
            self._push(tick + self.rng.randint(5, 12), "leave", r.idx)
        elif kind == "leave":
            shop = r.at_shop
            self.present[shop.idx].remove(r)
            r.at_shop = None
            self._push(self._next_trip(tick), "trip", r.idx)

    # Payments ------------------------------------------------------------------------------

    def amount_cents(self) -> int:
        dollars = min(45.0, max(3.0, self.rng.lognormvariate(math.log(12), 0.6)))
        return round(dollars * 100)

    def visit(self, r: Resident, shop: Shop, tick: int) -> None:
        """A resident at a shop pays; an organic double spender may roll back."""
        now = self._now(tick)
        if r.armed is not None:
            r.armed["countdown"] -= 1
            if r.armed["countdown"] <= 0:
                armed, r.armed = r.armed, None
                self.respend(r, shop, now, armed["snapshot"], armed["amount"], armed["mode"], "double_spender")
                return
        before = r.snapshot()
        pay = self.pay(r, shop, now)
        if pay is not None and r.cheats_left > 0 and r.cert.cap_cents == STORM_CAP_CENTS:
            r.cheats_left -= 1
            mode = "reuse" if r.idx % 2 == 0 else "skip"
            r.armed = {"snapshot": before, "countdown": self.rng.randint(1, 3), "amount": pay.tag.amount_cents,
                       "mode": mode}

    def pay(self, r: Resident, shop: Shop, now: int, amount: int | None = None) -> Pay | None:
        """Maya-style payment by QR, checked by the shop with C1–C6 (§8.1, §8.2)."""
        amount = min(amount or self.amount_cents(), r.remaining)
        if amount < MIN_PAYMENT_CENTS:
            self.stats.out_of_money += 1
            return None
        tag, det, req = self._sign(r, shop, now, r.counter + 1, r.head, amount, r.cum + amount)
        r.counter, r.head, r.cum = tag.counter, tag.tag_hash, tag.cum_cents
        if r.gossips_own_tags:
            r.hold(Item("TAG", tag, ((r.short, now),)), tag.tag_hash)  # the wallet keeps and gossips its tags
        pay = Pay(r.cert, tag, det)
        self.accept(shop, pay, req, now)
        return pay

    def respend(self, r: Resident, shop: Shop, now: int, snapshot: tuple[int, bytes, int], amount: int, mode: str,
                scenario: str) -> rules.CheckResult:
        """Spend money a rolled-back wallet already spent (§16.4 double_spender).
        reuse: same counter again (R1). skip: jump a counter with the old
        total, so the running total goes backwards (R3)."""
        counter, head, cum = snapshot
        if mode == "reuse":
            tag, det, req = self._sign(r, shop, now, counter + 1, head, amount, cum + amount)
        else:
            fake_prev = hashlib.sha256(b"skip" + r.head).digest()
            tag, det, req = self._sign(r, shop, now, r.counter + 2, fake_prev, amount, cum + amount)
        r.counter, r.head, r.cum = tag.counter, tag.tag_hash, tag.cum_cents  # the rolled-back wallet goes on from here
        result = self.accept(shop, Pay(r.cert, tag, det), req, now)
        self.stats.attempts.append(Attempt(r.idx, r.cert.cert_id, tag.tag_hash, shop.idx, now, mode, scenario,
                                           None if result.ok else result.check))
        return result

    def _sign(self, r: Resident, shop: Shop, now: int, counter: int, prev: bytes, amount: int,
              cum: int) -> tuple[Tag, Det, Req]:
        nonce = self.rng.randbytes(16)
        req = Req(shop.mcert.merchant_id, amount, nonce, now + 120)
        det = Det(shop.pub, nonce, now + r.clock_offset)
        tag = Tag(r.cert.cert_id, counter, prev, amount, cum, det.digest()).signed(r.key)
        return tag, det, req

    def accept(self, shop: Shop, pay: Pay, req: Req, now: int) -> rules.CheckResult:
        tag = pay.tag
        stored = list(shop.tags.get(tag.cert_id, {}).values())
        result = rules.merchant_check(
            pay, server_pub=self.server_pub, merchant=shop.mcert, req=req, policy=shop.policy,
            stored_tags=stored, now=now,
        )
        self.stats.payments += 1
        if result.ok or (shop.lenient and result.check in LENIENT_SKIPS):
            shop.hold(Item("PAY", pay, ((shop.short, now),)), tag.tag_hash)
            # Logged honestly, even by a lenient app: held_ids lists what it held (§9.4 a).
            shop.append_log(now, kind="ACCEPT", tag_hash=tag.tag_hash, cert_id=tag.cert_id,
                            held_ids=tuple(t.tag_hash for t in stored))
            self.stats.accepted += 1
            self.stats.pay_time[tag.tag_hash] = now
            return rules.PASSED
        shop.append_log(now, kind="REFUSE", tag_hash=tag.tag_hash, cert_id=tag.cert_id, check=result.check)
        if result.rule is not None:
            proof = rules.make_proof(result.conflict, tag)
            shop.hold(Item("PROOF", proof, ((shop.short, now),)), item_id("PROOF", proof))
        shop.hold(Item("PAY", pay, ((shop.short, now),)), tag.tag_hash)  # kept as evidence
        self.stats.refused[result.check] = self.stats.refused.get(result.check, 0) + 1
        return result

    # Gossip and relays ---------------------------------------------------------------------------

    def _prune(self, d: Device, now: int) -> None:
        stale = [k for k in d.carry if now - self.server_has.get(k, now) >= CARRY_AFTER_SERVER_S]
        for k in stale:
            del d.carry[k]

    def sync(self, a: Device, b: Device, now: int) -> None:
        """One sync session (§10.3): exchange items, then both sides log CONTACT."""
        self._prune(a, now)
        self._prune(b, now)
        a_to_b = [(k, it) for k, it in a.carry.items() if _wants(b, k, it)]
        b_to_a = [(k, it) for k, it in b.carry.items() if _wants(a, k, it)]
        for k, it in a_to_b:
            b.receive(k, it, now)
        for k, it in b_to_a:
            a.receive(k, it, now)
        if a.policy and (b.policy is None or a.policy.policy_ver > b.policy.policy_ver):
            b.policy = a.policy
        elif b.policy and (a.policy is None or b.policy.policy_ver > a.policy.policy_ver):
            a.policy = b.policy
        sent_ab = [id8(k) for k, it in a_to_b if it.kind in GOSSIP_KINDS]
        sent_ba = [id8(k) for k, it in b_to_a if it.kind in GOSSIP_KINDS]
        na, nb = self.rng.randbytes(16), self.rng.randbytes(16)
        cid = contact_id(a.pub, na, b.pub, nb)
        for me, peer, sent, recv in ((a, b, sent_ab, sent_ba), (b, a, sent_ba, sent_ab)):
            me.append_log(now, kind="CONTACT", contact_id=cid, peer_pub=peer.pub, sent_ids=tuple(sent[:200]),
                          recv_ids=tuple(recv[:200]), sent_overflow=max(0, len(sent) - 200),
                          recv_overflow=max(0, len(recv) - 200))
        self.stats.contacts += 1

    def meet(self, tick: int) -> None:
        """Phones within 2 cells at the same tick may sync (p_link, cooldown)."""
        now = self._now(tick)
        cooldown = self.p.pair_cooldown_min
        for shop_idx in sorted(self.present):
            here = self.present[shop_idx]
            if not here:
                continue
            nearby_shops = self.neighbors[shop_idx]
            nearby = [r for s in nearby_shops for r in self.present.get(s.idx, ())]
            for r in here:
                if not r.gossip_on(tick):
                    continue
                partners: list[Device] = [s for s in nearby_shops]
                partners += [o for o in nearby if o.idx > r.idx]
                for other in partners:
                    if not other.gossip_on(tick):
                        continue
                    pair = (min(r.idx, other.idx), max(r.idx, other.idx))
                    if tick - self.last_sync.get(pair, -cooldown) < cooldown:
                        continue
                    if self.rng.random() < self.p.p_link:
                        self.last_sync[pair] = tick
                        self.sync(r, other, now)

    def upload(self, d: Device, now: int) -> None:
        """A relay found internet: POST everything not yet receipted (§10.5).
        (TAGs the server already stored but can't receipt yet are skipped here
        only to save time; a phone would send them again.)"""
        pending = [(k, it) for k, it in d.carry.items()
                   if k not in self.server_has and not (it.kind == "TAG" and k in self.server_tags)]
        if not pending:
            return
        result = ingest_items(self.deps, d.pub, [it for _, it in pending], simulated=True, now=now)
        self.server_tags.update(result.unreceipted)
        for k in result.accepted:
            self.server_has.setdefault(k, now)
            d.carry.pop(k, None)
        for k, it in pending:
            if it.kind == "PAY":
                self.stats.settle_time.setdefault(k, now)
        if d.policy is None or result.policy.policy_ver > d.policy.policy_ver:
            d.policy = result.policy
        self.stats.uploads += 1
        self.stats.items_uploaded += len(pending)

    # Run --------------------------------------------------------------------------------------

    def run(self) -> dict:
        started = time.monotonic()
        self.setup()
        ticks = self.p.hours * 60
        rng = self.rng
        for tick in range(ticks):
            self.progress = tick / ticks
            while self.events and self.events[0][0] <= tick:
                _, _, kind, idx = heapq.heappop(self.events)
                self._handle(tick, kind, idx)
            self.meet(tick)
            now = self._now(tick)
            for d in self.devices:
                if rng.random() < d.p_uplink_tick and not _in(d.uplink_off, tick):
                    self.upload(d, now)
        self.progress = 1.0
        return self.summary(time.monotonic() - started)

    def summary(self, wall_s: float) -> dict:
        s = self.stats
        delays = [(s.settle_time[k] - t) / 60 for k, t in s.pay_time.items() if k in s.settle_time]
        return {
            "seed": self.p.seed,
            "hours": self.p.hours,
            "start": self.t0,
            "shops": len(self.shops),
            "residents": len(self.residents),
            "payments": s.payments,
            "accepted": s.accepted,
            "refused": dict(sorted(s.refused.items())),
            "out_of_money": s.out_of_money,
            "double_spend_attempts": len(s.attempts),
            "contacts": s.contacts,
            "uploads": s.uploads,
            "items_uploaded": s.items_uploaded,
            "settled": len(delays),
            "median_minutes_to_server": statistics.median(delays) if delays else None,
            "wall_seconds": round(wall_s, 1),
        }
