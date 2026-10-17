// Invariants of the simulator, and the properties the Monte Carlo relies on:
// a replicate depends only on (params, seed), never on threads.
#include <gtest/gtest.h>

#include "scale/runner.hpp"
#include "scale/stats.hpp"

namespace scale {
namespace {

Params town(int cheaters = 12) {
  Params p;  // the §16 town's defaults: one 40x24 tile, 400 residents
  p.cheaters = cheaters;
  return p;
}

long long hops_total(const ReplicateResult& r) {
  long long n = 0;
  for (const auto& [h, c] : r.hops_histogram) n += c;
  return n;
}

TEST(Sim, SameSeedSameResult) {
  auto a = run_replicate(town(), 7), b = run_replicate(town(), 7);
  a.wall_seconds = b.wall_seconds = 0;
  EXPECT_EQ(replicate_json(a), replicate_json(b));
  auto c = run_replicate(town(), 8);
  c.wall_seconds = 0;
  EXPECT_NE(replicate_json(a), replicate_json(c));
}

TEST(Sim, ResultsDoNotDependOnThreadCount) {
  ThreadPool one(1), four(4);
  auto x = run_replicates(town(), 99, 6, one);
  auto y = run_replicates(town(), 99, 6, four);
  ASSERT_EQ(x.size(), y.size());
  for (std::size_t i = 0; i < x.size(); ++i) {
    x[i].wall_seconds = y[i].wall_seconds = 0;
    EXPECT_EQ(replicate_json(x[i]), replicate_json(y[i])) << "replicate " << i;
  }
}

TEST(Sim, TownLooksLikeTheTown) {
  auto r = run_replicate(town(), 1);
  EXPECT_EQ(r.shops, 38);
  EXPECT_GT(r.adopters, 200);  // 60% of 400
  EXPECT_LT(r.adopters, 280);
  EXPECT_EQ(r.cheaters, 12);
  EXPECT_GT(r.payments, 500);
  EXPECT_GT(r.contacts, 0);
}

TEST(Sim, CountsAddUp) {
  for (std::uint64_t seed = 1; seed <= 5; ++seed) {
    auto r = run_replicate(town(), seed);
    EXPECT_EQ(r.accepted + r.refused, r.payments);
    EXPECT_EQ(r.refused_offline + r.accepted_offline, r.attempts);
    EXPECT_LE(r.caught_at_settlement, r.accepted_offline);
    EXPECT_LE(r.settled, r.accepted);
    EXPECT_GE(hops_total(r), r.settled);  // refused PAYs uploaded as evidence count in hops too
    EXPECT_LE(r.attempts, r.cheaters * 2);
    int by_check = 0;
    for (const auto& [k, v] : r.refusals_by_check) by_check += v;
    EXPECT_EQ(by_check, r.refused_offline);
  }
}

TEST(Sim, HonestTownHasNoDoubleSpends) {
  auto r = run_replicate(town(0), 3);
  EXPECT_EQ(r.attempts, 0);
  EXPECT_EQ(r.refused, 0);  // honest chains never fail C6, and nothing is frozen
  EXPECT_EQ(r.pool_loss_cents, 0);
  EXPECT_FALSE(r.share_refused_offline().has_value());
  EXPECT_TRUE(r.median_hours_to_settlement.has_value());
}

TEST(Sim, NoInternetNothingSettles) {
  Params p = town();
  p.p_uplink = 0;
  p.shelter_uplink = 0;
  auto r = run_replicate(p, 4);
  EXPECT_EQ(r.settled, 0);
  EXPECT_EQ(r.uploads, 0);
  EXPECT_EQ(r.caught_at_settlement, 0);
  EXPECT_EQ(r.pool_loss_cents, 0);
  EXPECT_FALSE(r.median_hours_to_settlement.has_value());
}

TEST(Sim, InstantInternetCatchesEveryAcceptedDoubleSpend) {
  // Every phone uploads every minute: each re-spend reaches the server within
  // a minute of the payment it conflicts with, so every accepted one is caught.
  Params p = town();
  p.p_uplink = 1;
  p.shelter_uplink = 1;
  for (std::uint64_t seed = 1; seed <= 3; ++seed) {
    auto r = run_replicate(p, seed);
    EXPECT_GT(r.attempts, 0);
    EXPECT_EQ(r.caught_at_settlement, r.accepted_offline);
    ASSERT_TRUE(r.median_hours_to_settlement.has_value());
    EXPECT_LT(*r.median_hours_to_settlement, 0.05);
    // Shops upload their own PAYs the minute they take them, so almost all
    // arrive with 0 hops. (Not all: in that same minute a customer can carry
    // one to a neighbouring shop that uploads first.)
    EXPECT_GT(static_cast<double>(r.hops_histogram[0]), 0.9 * static_cast<double>(hops_total(r)));
  }
}

TEST(Sim, NoMeetingsNoRelays) {
  Params p = town();
  p.p_link = 0;
  auto r = run_replicate(p, 5);
  EXPECT_EQ(r.contacts, 0);
  for (const auto& [h, c] : r.hops_histogram) EXPECT_EQ(h, 0) << "a PAY moved without a sync";
}

TEST(Sim, HomesWithNoShopInReachUseTheNearest) {
  // A 1-cell radius leaves most homes with no shop in reach (this used to
  // index an empty candidate list; run under ASan in CI).
  Params p = town();
  size_city_for(p, 1600);
  p.trip_radius = 1;
  auto r = run_replicate(p, 9);
  EXPECT_GT(r.payments, 0);
  EXPECT_EQ(r.accepted + r.refused, r.payments);
}

TEST(Sim, CityOfTowns) {
  Params p = town(-1);
  size_city_for(p, 1600);
  EXPECT_EQ(p.towns(), 4);
  auto r = run_replicate(p, 6);
  EXPECT_EQ(r.shops, 4 * 38);
  EXPECT_NEAR(r.cheaters, 0.025 * r.adopters, 1.0);
}

}  // namespace
}  // namespace scale
