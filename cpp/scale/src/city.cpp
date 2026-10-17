#include "scale/city.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <set>
#include <utility>

namespace scale {
namespace {

// sim/stormcash_sim/town.py, region by region, in its dict order.
struct RegionSpec {
  int x0, x1;  // x range [x0, x1) within the tile; every row
  int shops;
  double home_share;
};
constexpr std::array<RegionSpec, kRegionsPerTown> kRegions = {{
    {10, 20, 11, 0.30},  // asheville-downtown (shop 1 is the Downtown Shelter)
    {0, 10, 9, 0.25},    // west-asheville
    {20, 30, 9, 0.22},   // swannanoa
    {30, 40, 9, 0.23},   // black-mountain
}};
constexpr int kDowntown = 0;
// The real demo phones' spots (Pharmacy, Gas Station), kept free in every tile
// as town.py keeps them free in the town.
constexpr std::array<std::pair<int, int>, 2> kReservedSpots = {{{13, 10}, {16, 12}}};

int clamp(int v, int lo, int hi) { return std::max(lo, std::min(hi, v)); }

}  // namespace

double distance(int ax, int ay, int bx, int by) {
  double dx = ax - bx, dy = ay - by;
  return std::sqrt(dx * dx + dy * dy);
}

City build_city(const Params& p, Rng& rng) {
  City city;
  city.width = p.towns_x * kTownW;
  city.height = p.towns_y * kTownH;

  for (int ty = 0; ty < p.towns_y; ++ty) {
    for (int tx = 0; tx < p.towns_x; ++tx) {
      const int tile = ty * p.towns_x + tx;
      const int ox = tx * kTownW, oy = ty * kTownH;
      std::set<std::pair<int, int>> taken(kReservedSpots.begin(), kReservedSpots.end());
      for (int r = 0; r < kRegionsPerTown; ++r) {
        const RegionSpec& reg = kRegions[static_cast<std::size_t>(r)];
        // Two cluster centres: x in [x0 + 2, x1 - 2), y in [3, H - 3) (randrange bounds).
        std::array<std::pair<int, int>, 2> centres{};
        for (auto& c : centres) {
          c = {static_cast<int>(reg.x0 + 2 + rng.below(static_cast<std::uint64_t>(reg.x1 - 2 - (reg.x0 + 2)))),
               static_cast<int>(3 + rng.below(static_cast<std::uint64_t>(kTownH - 6)))};
        }
        for (int i = 0; i < reg.shops; ++i) {
          auto [cx, cy] = centres[static_cast<std::size_t>(i % 2)];
          int x = 0, y = 0;
          do {
            x = clamp(cx + static_cast<int>(rng.randint(-3, 3)), reg.x0, reg.x1 - 1);
            y = clamp(cy + static_cast<int>(rng.randint(-3, 3)), 0, kTownH - 1);
          } while (!taken.insert({x, y}).second);
          bool shelter = r == kDowntown && i == 1;
          city.shops.push_back(
              {ox + x, oy + y, tile * kRegionsPerTown + r, shelter, shelter ? p.shelter_uplink : p.p_uplink});
        }
      }
    }
  }

  // Residents: tile by turns (even spread), region by the town's home shares,
  // home cell uniform in the region.
  for (int i = 0; i < p.residents; ++i) {
    const int tile = i % p.towns();
    const int tx = tile % p.towns_x, ty = tile / p.towns_x;
    double u = rng.uniform(), acc = 0.0;
    int r = kRegionsPerTown - 1;
    for (int k = 0; k < kRegionsPerTown; ++k) {
      acc += kRegions[static_cast<std::size_t>(k)].home_share;
      if (u < acc) {
        r = k;
        break;
      }
    }
    const RegionSpec& reg = kRegions[static_cast<std::size_t>(r)];
    int x = reg.x0 + static_cast<int>(rng.below(static_cast<std::uint64_t>(reg.x1 - reg.x0)));
    int y = static_cast<int>(rng.below(kTownH));
    city.residents.push_back({tx * kTownW + x, ty * kTownH + y, tile * kRegionsPerTown + r});
  }
  return city;
}

}  // namespace scale
