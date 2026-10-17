// Turning replicates into reported numbers.
//
// Each replicate is written in the shape of sim/out/<seed>/stats.json. A
// parameter point's summary gives, per metric, the pooled value (totals over
// all replicates) and the mean over replicates with a 95% confidence interval
// (Student t, replicates as independent samples).
#pragma once

#include <nlohmann/json.hpp>
#include <optional>
#include <vector>

#include "scale/params.hpp"
#include "scale/sim.hpp"

namespace scale {

using Json = nlohmann::ordered_json;

struct Estimate {
  int n = 0;
  double mean = 0.0;
  double sd = 0.0;
  double ci_low = 0.0;
  double ci_high = 0.0;
};

// Two-sided 97.5% quantile of Student's t with `df` degrees of freedom.
double t_quantile_975(int df);

// Mean and 95% CI of the values; none for an empty list. One value gives a
// zero-width interval (no spread to estimate).
std::optional<Estimate> estimate(const std::vector<double>& values);

// One replicate, shaped like stats.json (shares to 4 places, hours to 2,
// cents to whole cents, as outputs.py rounds them).
Json replicate_json(const ReplicateResult& r);

// Pooled values and replicate means with 95% CIs.
Json summary_json(const std::vector<ReplicateResult>& replicates);

}  // namespace scale
