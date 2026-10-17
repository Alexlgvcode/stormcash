#include <gtest/gtest.h>

#include <cmath>
#include <set>

#include "scale/rng.hpp"

namespace scale {
namespace {

TEST(Rng, SameSeedSameStream) {
  Rng a(42), b(42), c(43);
  for (int i = 0; i < 100; ++i) {
    std::uint64_t x = a.next();
    EXPECT_EQ(x, b.next());
    EXPECT_NE(x, c.next());
  }
}

TEST(Rng, DerivedSeedsAreDistinct) {
  std::set<std::uint64_t> seen;
  for (std::uint64_t s = 0; s < 1000; ++s) seen.insert(derive_seed(7, s));
  EXPECT_EQ(seen.size(), 1000u);
  EXPECT_NE(derive_seed(1, 0), derive_seed(2, 0));
}

TEST(Rng, RangesIncludeBothEndsAndNothingElse) {
  Rng r(1);
  std::set<std::int64_t> seen;
  for (int i = 0; i < 10000; ++i) {
    auto v = r.randint(5, 12);  // a visit lasts 5 to 12 minutes
    ASSERT_GE(v, 5);
    ASSERT_LE(v, 12);
    seen.insert(v);
    double u = r.uniform();
    ASSERT_GE(u, 0.0);
    ASSERT_LT(u, 1.0);
  }
  EXPECT_EQ(seen.size(), 8u);
}

// Loose statistical checks (fixed seed, so they can't flake).
TEST(Rng, DistributionMeans) {
  Rng r(2);
  const int n = 200000;
  double exp_sum = 0, geo_sum = 0, norm_sum = 0, norm_sq = 0;
  for (int i = 0; i < n; ++i) {
    exp_sum += r.exponential(240.0);
    geo_sum += static_cast<double>(r.geometric(0.01));
    double z = r.normal();
    norm_sum += z;
    norm_sq += z * z;
  }
  EXPECT_NEAR(exp_sum / n, 240.0, 3.0);
  EXPECT_NEAR(geo_sum / n, 100.0, 1.5);  // mean of a geometric = 1 / p
  EXPECT_NEAR(norm_sum / n, 0.0, 0.01);
  EXPECT_NEAR(norm_sq / n, 1.0, 0.01);
}

TEST(Rng, GeometricEdges) {
  Rng r(3);
  EXPECT_EQ(r.geometric(1.0), 1);
  EXPECT_EQ(r.geometric(0.0), std::numeric_limits<std::int64_t>::max());
  for (int i = 0; i < 1000; ++i) ASSERT_GE(r.geometric(0.5), 1);
}

}  // namespace
}  // namespace scale
