// Deterministic random numbers for the Scale Lab.
//
// xoshiro256** (Blackman and Vigna, 2018) seeded through SplitMix64, with the
// few distributions the town needs written out here rather than taken from
// <random>: the C++ standard fixes what the engines output but not what the
// distributions do with it, so std::uniform_int_distribution can give
// different draws under libstdc++ and libc++. log, exp, sqrt and cos still
// come from the platform's libm, which may differ in the last bit between
// platforms, so a seed is reproducible on one platform and statistically
// equivalent across platforms.
#pragma once

#include <array>
#include <cmath>
#include <cstdint>
#include <limits>

namespace scale {

// SplitMix64 step: turns any 64-bit value into a well-mixed one.
inline std::uint64_t splitmix64(std::uint64_t& state) {
  std::uint64_t z = (state += 0x9E3779B97F4A7C15ull);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
  return z ^ (z >> 31);
}

// Independent seed for stream `stream` of base seed `base` (replicate i, the
// layout stream, ...). Same inputs, same seed, on any platform.
inline std::uint64_t derive_seed(std::uint64_t base, std::uint64_t stream) {
  std::uint64_t state = base ^ (0xD1B54A32D192ED03ull * (stream + 1));
  splitmix64(state);
  return splitmix64(state);
}

class Rng {
 public:
  explicit Rng(std::uint64_t seed) {
    std::uint64_t state = seed;
    for (auto& word : s_) word = splitmix64(state);
  }

  std::uint64_t next() {
    const std::uint64_t result = rotl(s_[1] * 5, 7) * 9;
    const std::uint64_t t = s_[1] << 17;
    s_[2] ^= s_[0];
    s_[3] ^= s_[1];
    s_[1] ^= s_[2];
    s_[0] ^= s_[3];
    s_[2] ^= t;
    s_[3] = rotl(s_[3], 45);
    return result;
  }

  // Uniform in [0, 1) with 53 random bits, like Python's random().
  double uniform() { return static_cast<double>(next() >> 11) * 0x1.0p-53; }

  bool chance(double p) { return uniform() < p; }

  // Uniform in [0, n), unbiased: reject the top sliver that would make
  // `r % n` favour small values.
  std::uint64_t below(std::uint64_t n) {
    const std::uint64_t threshold = (0 - n) % n;  // = 2^64 mod n
    for (;;) {
      std::uint64_t r = next();
      if (r >= threshold) return r % n;
    }
  }

  // Uniform integer in [lo, hi], both ends included (Python's randint).
  std::int64_t randint(std::int64_t lo, std::int64_t hi) {
    return lo + static_cast<std::int64_t>(below(static_cast<std::uint64_t>(hi - lo) + 1));
  }

  // Exponential with the given mean (Python's expovariate(1 / mean)).
  double exponential(double mean) { return -std::log(1.0 - uniform()) * mean; }

  // Standard normal by Box-Muller (one value per call, no hidden state).
  double normal() {
    double u1 = 1.0 - uniform();  // (0, 1], so log(u1) is finite
    double u2 = uniform();
    return std::sqrt(-2.0 * std::log(u1)) * std::cos(2.0 * kPi * u2);
  }

  double lognormal(double mu, double sigma) { return std::exp(mu + sigma * normal()); }

  // Number of Bernoulli(p) trials up to and including the first success (≥ 1).
  // Used to schedule "a phone gets internet with probability p per minute"
  // without drawing a number for every phone every minute.
  std::int64_t geometric(double p) {
    if (p >= 1.0) return 1;
    if (p <= 0.0) return std::numeric_limits<std::int64_t>::max();
    return static_cast<std::int64_t>(std::floor(std::log(1.0 - uniform()) / std::log1p(-p))) + 1;
  }

 private:
  static constexpr double kPi = 3.14159265358979323846;
  static std::uint64_t rotl(std::uint64_t x, int k) { return (x << k) | (x >> (64 - k)); }
  std::array<std::uint64_t, 4> s_{};
};

}  // namespace scale
