// Parameters of one simulated city. Defaults are the §16 town's
// (sim/stormcash_sim/engine.py: Params), so a 1-town city with the defaults
// is the Python town at the same settings.
#pragma once

#include <cstdint>
#include <nlohmann/json.hpp>
#include <string>

namespace scale {

struct Params {
  // City: a towns_x × towns_y grid of 40×24-cell town tiles, each laid out
  // like the §16 town (4 regions, 38 shops, one shelter with good uplink).
  int towns_x = 1;
  int towns_y = 1;
  int residents = 400;  // before adoption, spread evenly over the tiles

  int hours = 72;
  int start_local_minute = 0;  // local time of day at T0 (0 = midnight)
  double adoption = 0.6;
  double storm_share = 0.7;  // share of adopters raised to the $50 cap
  double storm_at_h = 2.0;
  double p_link = 0.6;     // two phones in range sync this minute (§16.3)
  double p_uplink = 0.03;  // a phone gets internet, per hour
  double shelter_uplink = 0.5;
  double trip_every_min = 240.0;
  int pair_cooldown_min = 60;       // a pair syncs at most once an hour
  int carry_after_server_min = 60;  // relays drop an item an hour after the server has it
  // Residents shop within this many cells of home, weighted 1 / (1 + d)^2.
  // 50 covers a whole 40×24 tile from anywhere in it, so one tile matches
  // the Python town (which weighs every shop) exactly.
  double trip_radius = 50.0;
  // A phone that gets internet always comes back with the latest POLICY
  // (§10.5). engine.py only calls the server when a phone has items to send,
  // but its phones nearly always do: their own DLOG entries and TAG copies,
  // which this model leaves out. false = refresh only when a PAY is uploaded
  // (this model's first version; see README, "Validation").
  bool policy_on_every_uplink = true;

  // Double spenders (§16.4 double_spender, the organic kind): adopters who
  // roll back after a payment and spend again 1–3 shops later.
  double cheater_share = 0.025;  // of adopters (6 of ~240 in the Python town)
  int cheaters = -1;             // exact count for the whole city; overrides the share when ≥ 0
  int cheats_per_cheater = 2;

  int towns() const { return towns_x * towns_y; }
};

nlohmann::ordered_json to_json(const Params& p);
// Applies "name=value" (CLI flags and sweep axes). Throws std::invalid_argument.
void set_param(Params& p, const std::string& name, const std::string& value);
// Tiles for about `residents` people at the town's 400 per tile, as close to square as divides evenly.
void size_city_for(Params& p, int residents);

}  // namespace scale
