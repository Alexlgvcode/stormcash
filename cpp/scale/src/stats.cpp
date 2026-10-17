#include "scale/stats.hpp"

#include <array>
#include <cmath>
#include <functional>

namespace scale {
namespace {

double round_to(double v, int places) {
  double f = std::pow(10.0, places);
  return std::nearbyint(v * f) / f;
}

Json optional_number(const std::optional<double>& v, int places) {
  if (!v) return nullptr;
  return round_to(*v, places);
}

Json estimate_json(const std::optional<Estimate>& e, int places) {
  if (!e) return nullptr;
  return Json{{"mean", round_to(e->mean, places)},
              {"ci95", Json::array({round_to(e->ci_low, places), round_to(e->ci_high, places)})},
              {"sd", round_to(e->sd, places)},
              {"n", e->n}};
}

std::vector<double> collect(const std::vector<ReplicateResult>& reps,
                            const std::function<std::optional<double>(const ReplicateResult&)>& get) {
  std::vector<double> out;
  for (const auto& r : reps) {
    if (auto v = get(r)) out.push_back(*v);
  }
  return out;
}

}  // namespace

double t_quantile_975(int df) {
  // Exact to 3 decimals for small samples (standard tables)...
  static constexpr std::array<double, 30> kTable = {
      12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
      2.120,  2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042};
  if (df < 1) return 0.0;
  if (df <= 30) return kTable[static_cast<std::size_t>(df - 1)];
  // ...then the Cornish-Fisher expansion around the normal quantile, good to
  // about 1e-4 from 30 degrees of freedom up.
  const double z = 1.959963984540054, v = df;
  const double z3 = z * z * z, z5 = z3 * z * z, z7 = z5 * z * z;
  return z + (z3 + z) / (4 * v) + (5 * z5 + 16 * z3 + 3 * z) / (96 * v * v) +
         (3 * z7 + 19 * z5 + 17 * z3 - 15 * z) / (384 * v * v * v);
}

std::optional<Estimate> estimate(const std::vector<double>& values) {
  if (values.empty()) return std::nullopt;
  Estimate e;
  e.n = static_cast<int>(values.size());
  for (double v : values) e.mean += v;
  e.mean /= e.n;
  if (e.n > 1) {
    double ss = 0.0;
    for (double v : values) ss += (v - e.mean) * (v - e.mean);
    e.sd = std::sqrt(ss / (e.n - 1));
  }
  double half = e.n > 1 ? t_quantile_975(e.n - 1) * e.sd / std::sqrt(static_cast<double>(e.n)) : 0.0;
  e.ci_low = e.mean - half;
  e.ci_high = e.mean + half;
  return e;
}

Json replicate_json(const ReplicateResult& r) {
  Json by_check = Json::object();
  for (const auto& [k, v] : r.refusals_by_check) by_check[k] = v;
  Json by_mode = Json::object();
  for (const auto& [k, v] : r.by_mode) by_mode[k] = v;
  Json hops = Json::object();
  for (const auto& [k, v] : r.hops_histogram) hops[std::to_string(k)] = v;
  Json refused = Json::object();
  for (const auto& [k, v] : r.refused_by_check) refused[k] = v;
  std::optional<double> loss = r.mean_loss_per_cheater_cents();
  return Json{
      {"seed", r.seed},
      {"summary",
       {{"shops", r.shops},
        {"residents", r.adopters},
        {"payments", r.payments},
        {"accepted", r.accepted},
        {"refused", refused},  // by check, as engine.py's summary has it
        {"out_of_money", r.out_of_money},
        {"contacts", r.contacts},
        {"uploads", r.uploads},
        {"items_uploaded", r.items_uploaded},
        {"settled", r.settled},
        {"wall_seconds", round_to(r.wall_seconds, 3)}}},
      {"double_spends",
       {{"attempts", r.attempts},
        {"refused_offline", r.refused_offline},
        {"accepted_offline", r.accepted_offline},
        {"caught_at_settlement", r.caught_at_settlement},
        {"not_caught_by_end", r.accepted_offline - r.caught_at_settlement},
        {"share_refused_offline", optional_number(r.share_refused_offline(), 4)},
        {"share_caught_at_settlement", optional_number(r.share_caught_at_settlement(), 4)},
        {"refusals_by_check", by_check},
        {"by_mode", by_mode}}},
      {"cheaters", r.cheaters},
      {"pool_loss_cents", r.pool_loss_cents},
      {"mean_loss_per_cheater_cents", loss ? Json(std::llround(*loss)) : Json(nullptr)},
      {"median_hours_to_settlement", optional_number(r.median_hours_to_settlement, 2)},
      {"hops_histogram", hops},
  };
}

Json summary_json(const std::vector<ReplicateResult>& reps) {
  long long attempts = 0, refused = 0, caught = 0, cheaters = 0, pool = 0, payments = 0, settled = 0, contacts = 0;
  std::map<int, long long> hops;
  for (const auto& r : reps) {
    attempts += r.attempts;
    refused += r.refused_offline;
    caught += r.caught_at_settlement;
    cheaters += r.cheaters;
    pool += r.pool_loss_cents;
    payments += r.payments;
    settled += r.settled;
    contacts += r.contacts;
    for (const auto& [k, v] : r.hops_histogram) hops[k] += v;
  }
  long long hop_total = 0;
  for (const auto& [k, v] : hops) hop_total += v;
  Json hops_json = Json::object();
  for (const auto& [k, v] : hops) {
    hops_json[std::to_string(k)] = {{"count", v}, {"share", round_to(static_cast<double>(v) / hop_total, 4)}};
  }
  auto ratio = [](long long num, long long den) -> Json {
    if (den == 0) return nullptr;
    return round_to(static_cast<double>(num) / den, 4);
  };
  auto wall = estimate(collect(reps, [](const ReplicateResult& r) { return std::optional(r.wall_seconds); }));
  return Json{
      {"replicates", reps.size()},
      {"totals",
       {{"payments", payments},
        {"settled", settled},
        {"contacts", contacts},
        {"double_spend_attempts", attempts},
        {"refused_offline", refused},
        {"caught_at_settlement", caught},
        {"cheaters", cheaters},
        {"pool_loss_cents", pool}}},
      {"share_refused_offline",
       {{"pooled", ratio(refused, attempts)},
        {"replicate_mean",
         estimate_json(estimate(collect(reps, [](const ReplicateResult& r) { return r.share_refused_offline(); })),
                       4)}}},
      {"share_caught_at_settlement",
       {{"pooled", ratio(caught, attempts)},
        {"replicate_mean",
         estimate_json(estimate(collect(reps, [](const ReplicateResult& r) { return r.share_caught_at_settlement(); })),
                       4)}}},
      {"mean_loss_per_cheater_cents",
       {{"pooled", cheaters ? Json(std::llround(static_cast<double>(pool) / cheaters)) : Json(nullptr)},
        {"replicate_mean",
         estimate_json(
             estimate(collect(reps, [](const ReplicateResult& r) { return r.mean_loss_per_cheater_cents(); })), 1)}}},
      {"median_hours_to_settlement",
       {{"replicate_mean",
         estimate_json(estimate(collect(reps, [](const ReplicateResult& r) { return r.median_hours_to_settlement; })),
                       3)}}},
      {"hops_histogram", hops_json},
      {"wall_seconds_per_replicate", estimate_json(wall, 3)},
  };
}

}  // namespace scale
