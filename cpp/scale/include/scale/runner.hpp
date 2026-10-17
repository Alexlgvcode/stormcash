// Monte Carlo: many replicates of one parameter point, run on a thread pool.
#pragma once

#include <cstdint>
#include <vector>

#include "scale/params.hpp"
#include "scale/rng.hpp"
#include "scale/sim.hpp"
#include "scale/thread_pool.hpp"

namespace scale {

// Replicate i runs with derive_seed(base_seed, i), so every replicate is
// reproducible on its own and the results don't depend on the thread count
// or on the order replicates finish in. Returned in replicate order.
inline std::vector<ReplicateResult> run_replicates(const Params& params, std::uint64_t base_seed, int replicates,
                                                   ThreadPool& pool) {
  std::vector<std::future<ReplicateResult>> pending;
  pending.reserve(static_cast<std::size_t>(replicates));
  for (int i = 0; i < replicates; ++i) {
    std::uint64_t seed = derive_seed(base_seed, static_cast<std::uint64_t>(i));
    pending.push_back(pool.submit([params, seed] { return run_replicate(params, seed); }));
  }
  std::vector<ReplicateResult> out;
  out.reserve(pending.size());
  for (auto& f : pending) out.push_back(f.get());
  return out;
}

}  // namespace scale
