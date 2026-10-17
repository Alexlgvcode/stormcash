// One simulated storm in one city: a discrete-time, minute-by-minute model of
// the §16 town's rules at any size. See cpp/scale/README.md for the model and
// how it maps onto sim/stormcash_sim/engine.py.
//
// Payments are abstract: a tag is (cert, counter, prev, amount, cum) and an
// id, with no keys, signatures or hashes. The equivocation rules R1–R3 are
// evaluated on those fields exactly as §8.3 states them, so offline refusal
// (C6, and C2 once a freeze has spread) and server-side catches follow the
// protocol's logic without its cryptography.
#pragma once

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "scale/params.hpp"

namespace scale {

// What one replicate measured. Field names follow sim/out/<seed>/stats.json.
struct ReplicateResult {
  std::uint64_t seed = 0;

  // The city.
  int shops = 0;
  int adopters = 0;
  int cheaters = 0;

  // Activity.
  long long payments = 0;  // every payment a shop checked (incl. re-spends)
  long long accepted = 0;
  long long refused = 0;
  std::map<std::string, long long> refused_by_check;  // every refusal, not just re-spends: "C2", "C6"
  long long out_of_money = 0;
  long long contacts = 0;  // sync sessions
  long long uploads = 0;
  long long items_uploaded = 0;

  // Double spends (the re-spends after a rollback).
  int attempts = 0;
  int refused_offline = 0;
  int accepted_offline = 0;
  int caught_at_settlement = 0;                  // accepted offline, then in a case at the server
  std::map<std::string, int> refusals_by_check;  // "C2" (frozen), "C6"
  std::map<std::string, int> by_mode;            // "reuse", "skip"

  long long pool_loss_cents = 0;  // guarantee-pool money paid on cheaters' certs
  long long settled = 0;          // accepted payments that reached the server
  std::optional<double> median_hours_to_settlement;
  std::map<int, long long> hops_histogram;  // every PAY that reached the server

  double wall_seconds = 0.0;

  std::optional<double> share_refused_offline() const;
  std::optional<double> share_caught_at_settlement() const;
  std::optional<double> mean_loss_per_cheater_cents() const;
};

// Runs one replicate. Deterministic: the same params and seed give the same
// result (on one platform; see rng.hpp).
ReplicateResult run_replicate(const Params& params, std::uint64_t seed);

}  // namespace scale
