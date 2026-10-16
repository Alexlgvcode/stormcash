"""Town model (spec §16.3): the grid, regions, shops and residents' homes.

Everything is derived from the seed. The two real demo shops (Pharmacy, Gas
Station) are real phones registered through the API, not created here; the
simulator builds the other 38 shops, including Corner Store.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

GRID_W, GRID_H = 40, 24

# region_id -> x range [x0, x1) on the grid (all rows), matching server/stormcash/regions.py
REGION_X = {
    "west-asheville": (0, 10),
    "asheville-downtown": (10, 20),
    "swannanoa": (20, 30),
    "black-mountain": (30, 40),
}
SHOPS_PER_REGION = {"asheville-downtown": 11, "west-asheville": 9, "swannanoa": 9, "black-mountain": 9}
HOME_SHARE = {"asheville-downtown": 0.30, "west-asheville": 0.25, "swannanoa": 0.22, "black-mountain": 0.23}
REGION_NAME = {
    "asheville-downtown": "Downtown", "west-asheville": "West Asheville",
    "swannanoa": "Swannanoa", "black-mountain": "Black Mountain",
}
SHOP_KINDS = (
    "Grocer", "Hardware", "Cafe", "Bakery", "Diner", "General Store", "Laundromat", "Pet Supply",
    "Bike Shop", "Books", "Deli", "Market", "Feed Store", "Pharmacy", "Gas & Go", "Outfitters",
)
# Fixed spots of the real demo phones, drawn by the Town tab (§16.3).
REAL_SHOP_SPOTS = {"Pharmacy": (13, 10), "Gas Station": (16, 12)}


@dataclass(frozen=True)
class ShopSpec:
    name: str
    region: str
    x: int
    y: int
    uplink_per_hour: float


@dataclass(frozen=True)
class ResidentSpec:
    name: str
    region: str
    x: int
    y: int


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def build_shops(rng: random.Random, p_uplink: float, shelter_uplink: float = 0.5) -> list[ShopSpec]:
    """38 simulated shops in clusters per region. Corner Store (the colluder in
    seed 42) and the Shelter (good uplink) sit downtown."""
    shops: list[ShopSpec] = []
    taken = set(REAL_SHOP_SPOTS.values())
    for region, count in SHOPS_PER_REGION.items():
        x0, x1 = REGION_X[region]
        centers = [(rng.randrange(x0 + 2, x1 - 2), rng.randrange(3, GRID_H - 3)) for _ in range(2)]
        kinds = rng.sample(SHOP_KINDS, count)
        for i in range(count):
            cx, cy = centers[i % 2]
            while True:
                x = _clamp(cx + rng.randint(-3, 3), x0, x1 - 1)
                y = _clamp(cy + rng.randint(-3, 3), 0, GRID_H - 1)
                if (x, y) not in taken:
                    taken.add((x, y))
                    break
            name = f"{REGION_NAME[region]} {kinds[i]}"
            uplink = p_uplink
            if region == "asheville-downtown" and i == 0:
                name, uplink = "Corner Store", p_uplink
            elif region == "asheville-downtown" and i == 1:
                name, uplink = "Downtown Shelter", shelter_uplink
            shops.append(ShopSpec(name, region, x, y, uplink))
    return shops


def build_residents(rng: random.Random, count: int) -> list[ResidentSpec]:
    regions = list(HOME_SHARE)
    weights = [HOME_SHARE[r] for r in regions]
    out = []
    for i in range(count):
        region = rng.choices(regions, weights)[0]
        x0, x1 = REGION_X[region]
        out.append(ResidentSpec(f"Resident {i + 1:03d}", region, rng.randrange(x0, x1), rng.randrange(GRID_H)))
    return out


def distance(ax: int, ay: int, bx: int, by: int) -> float:
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
