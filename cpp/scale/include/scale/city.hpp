// The city's layout: a grid of town tiles, each built the way the §16 town
// is (sim/stormcash_sim/town.py), from the same rules and constants.
#pragma once

#include <vector>

#include "scale/params.hpp"
#include "scale/rng.hpp"

namespace scale {

inline constexpr int kTownW = 40;
inline constexpr int kTownH = 24;
inline constexpr int kRegionsPerTown = 4;

struct ShopSpec {
  int x;
  int y;
  int region;  // tile * 4 + region within the tile
  bool shelter;
  double uplink_per_hour;
};

struct ResidentSpec {
  int x;
  int y;
  int region;
};

struct City {
  int width = 0;
  int height = 0;
  std::vector<ShopSpec> shops;
  std::vector<ResidentSpec> residents;  // everyone, before adoption
};

// Builds every tile like town.build_shops / build_residents: per region, two
// cluster centres and shops scattered ±3 cells around them (9 to 11 shops a
// region, 38 a tile), the Downtown Shelter with good uplink, residents homed
// by the town's regional shares. Residents are spread evenly over the tiles.
City build_city(const Params& p, Rng& rng);

double distance(int ax, int ay, int bx, int by);

}  // namespace scale
