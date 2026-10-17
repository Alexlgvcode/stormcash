#include "scale/params.hpp"

#include <cmath>
#include <functional>
#include <map>
#include <stdexcept>

namespace scale {
namespace {

int parse_int(const std::string& v) {
  std::size_t used = 0;
  int out = std::stoi(v, &used);
  if (used != v.size()) throw std::invalid_argument("not an integer: " + v);
  return out;
}

bool parse_bool(const std::string& v) {
  if (v == "1" || v == "true") return true;
  if (v == "0" || v == "false") return false;
  throw std::invalid_argument("not a boolean (1/0/true/false): " + v);
}

double parse_double(const std::string& v) {
  std::size_t used = 0;
  double out = std::stod(v, &used);
  if (used != v.size()) throw std::invalid_argument("not a number: " + v);
  return out;
}

using Setter = std::function<void(Params&, const std::string&)>;

const std::map<std::string, Setter>& setters() {
  static const std::map<std::string, Setter> all = {
      {"towns_x", [](Params& p, const std::string& v) { p.towns_x = parse_int(v); }},
      {"towns_y", [](Params& p, const std::string& v) { p.towns_y = parse_int(v); }},
      {"residents", [](Params& p, const std::string& v) { p.residents = parse_int(v); }},
      {"hours", [](Params& p, const std::string& v) { p.hours = parse_int(v); }},
      {"start_local_minute", [](Params& p, const std::string& v) { p.start_local_minute = parse_int(v); }},
      {"adoption", [](Params& p, const std::string& v) { p.adoption = parse_double(v); }},
      {"storm_share", [](Params& p, const std::string& v) { p.storm_share = parse_double(v); }},
      {"storm_at_h", [](Params& p, const std::string& v) { p.storm_at_h = parse_double(v); }},
      {"p_link", [](Params& p, const std::string& v) { p.p_link = parse_double(v); }},
      {"p_uplink", [](Params& p, const std::string& v) { p.p_uplink = parse_double(v); }},
      {"shelter_uplink", [](Params& p, const std::string& v) { p.shelter_uplink = parse_double(v); }},
      {"trip_every_min", [](Params& p, const std::string& v) { p.trip_every_min = parse_double(v); }},
      {"pair_cooldown_min", [](Params& p, const std::string& v) { p.pair_cooldown_min = parse_int(v); }},
      {"carry_after_server_min", [](Params& p, const std::string& v) { p.carry_after_server_min = parse_int(v); }},
      {"trip_radius", [](Params& p, const std::string& v) { p.trip_radius = parse_double(v); }},
      {"policy_on_every_uplink", [](Params& p, const std::string& v) { p.policy_on_every_uplink = parse_bool(v); }},
      {"cheater_share", [](Params& p, const std::string& v) { p.cheater_share = parse_double(v); }},
      {"cheaters", [](Params& p, const std::string& v) { p.cheaters = parse_int(v); }},
      {"cheats_per_cheater", [](Params& p, const std::string& v) { p.cheats_per_cheater = parse_int(v); }},
  };
  return all;
}

}  // namespace

nlohmann::ordered_json to_json(const Params& p) {
  return {
      {"towns_x", p.towns_x},
      {"towns_y", p.towns_y},
      {"residents", p.residents},
      {"hours", p.hours},
      {"start_local_minute", p.start_local_minute},
      {"adoption", p.adoption},
      {"storm_share", p.storm_share},
      {"storm_at_h", p.storm_at_h},
      {"p_link", p.p_link},
      {"p_uplink", p.p_uplink},
      {"shelter_uplink", p.shelter_uplink},
      {"trip_every_min", p.trip_every_min},
      {"pair_cooldown_min", p.pair_cooldown_min},
      {"carry_after_server_min", p.carry_after_server_min},
      {"trip_radius", p.trip_radius},
      {"policy_on_every_uplink", p.policy_on_every_uplink},
      {"cheater_share", p.cheater_share},
      {"cheaters", p.cheaters},
      {"cheats_per_cheater", p.cheats_per_cheater},
  };
}

void set_param(Params& p, const std::string& name, const std::string& value) {
  auto it = setters().find(name);
  if (it == setters().end()) throw std::invalid_argument("unknown parameter: " + name);
  it->second(p, value);
}

void size_city_for(Params& p, int residents) {
  // Exactly residents / 400 tiles, so the density is the town's; laid out as
  // the most nearly square grid with that many tiles (250 tiles: 25 x 10).
  int towns = std::max(1, static_cast<int>(std::lround(residents / 400.0)));
  int short_side = static_cast<int>(std::floor(std::sqrt(static_cast<double>(towns))));
  while (towns % short_side != 0) --short_side;
  p.towns_y = short_side;
  p.towns_x = towns / short_side;
  p.residents = residents;
}

}  // namespace scale
