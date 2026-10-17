#include <gtest/gtest.h>

#include "scale/stats.hpp"

namespace scale {
namespace {

TEST(Stats, StudentT) {
  EXPECT_DOUBLE_EQ(t_quantile_975(1), 12.706);
  EXPECT_DOUBLE_EQ(t_quantile_975(30), 2.042);
  EXPECT_NEAR(t_quantile_975(31), 2.040, 1e-3);  // continuous with the table
  EXPECT_NEAR(t_quantile_975(60), 2.000, 1e-3);
  EXPECT_NEAR(t_quantile_975(120), 1.980, 1e-3);
  EXPECT_NEAR(t_quantile_975(100000), 1.960, 1e-3);
}

TEST(Stats, Estimate) {
  EXPECT_FALSE(estimate({}).has_value());
  auto one = estimate({3.0});
  ASSERT_TRUE(one);
  EXPECT_EQ(one->ci_low, 3.0);
  EXPECT_EQ(one->ci_high, 3.0);
  auto e = estimate({1.0, 2.0, 3.0, 4.0, 5.0});
  ASSERT_TRUE(e);
  EXPECT_DOUBLE_EQ(e->mean, 3.0);
  EXPECT_NEAR(e->sd, 1.5811, 1e-4);
  EXPECT_NEAR(e->ci_high - e->mean, 2.776 * 1.5811 / std::sqrt(5.0), 1e-3);
}

}  // namespace
}  // namespace scale
