// Rule logic on hand-built (unsigned) tags: the equivocation rules don't look
// at signatures, so the conditions can be exercised one at a time here. The
// signed cases are in spec/vectors.json (test_vectors.cpp).
#include <gtest/gtest.h>

#include "stormcash/encoding.hpp"
#include "stormcash/rules.hpp"
#include "support.hpp"

namespace stormcash {
namespace {

const Bytes kCert(16, 0xc1);
const Bytes kOtherCert(16, 0xc2);
const Bytes kDetails(32, 0xdd);

Tag make_tag(const Bytes& cert_id, std::int64_t counter, const Bytes& prev, std::int64_t amount, std::int64_t cum,
             const Bytes& details = kDetails) {
  Json fields = {{"cert_id", to_hex(cert_id)}, {"counter", counter}, {"prev_hash", to_hex(prev)},
                 {"amount_cents", amount},     {"cum_cents", cum},   {"details_hash", to_hex(details)}};
  return Tag(Object::from_fields("TAG", fields, nullptr));
}

// An honest chain on kCert: $10, then $5, then $7.
struct Chain {
  Tag t1 = make_tag(kCert, 1, genesis(kCert), 1000, 1000);
  Tag t2 = make_tag(kCert, 2, t1.tag_hash(), 500, 1500);
  Tag t3 = make_tag(kCert, 3, t2.tag_hash(), 700, 2200);
};

std::vector<Rule> rules(const Tag& x, const Tag& y) { return rules_fired(x, y); }

TEST(TagValid, Conditions) {
  Chain c;
  EXPECT_TRUE(tag_valid(c.t1));
  EXPECT_TRUE(tag_valid(c.t2));
  EXPECT_FALSE(tag_valid(make_tag(kCert, 0, genesis(kCert), 100, 100)));       // counter starts at 1
  EXPECT_FALSE(tag_valid(make_tag(kCert, 2, c.t1.tag_hash(), 0, 1000)));       // amount > 0
  EXPECT_FALSE(tag_valid(make_tag(kCert, 2, c.t1.tag_hash(), 500, 400)));      // cum >= amount
  EXPECT_FALSE(tag_valid(make_tag(kCert, 1, Bytes(32, 0), 100, 100)));         // counter 1 links to GENESIS
  EXPECT_FALSE(tag_valid(make_tag(kCert, 1, genesis(kCert), 100, 200)));       // counter 1 has cum = amount
  EXPECT_FALSE(tag_valid(make_tag(kCert, 1, genesis(kOtherCert), 100, 100)));  // GENESIS of its own cert
}

TEST(Equivocation, HonestChainBreaksNothing) {
  Chain c;
  EXPECT_TRUE(rules(c.t1, c.t2).empty());
  EXPECT_TRUE(rules(c.t2, c.t3).empty());
  EXPECT_TRUE(rules(c.t1, c.t3).empty());
  EXPECT_TRUE(rules(c.t2, c.t2).empty());  // the same tag twice is not a double spend
}

TEST(Equivocation, R1SameCounter) {
  Chain c;
  Tag other = make_tag(kCert, 1, genesis(kCert), 800, 800, Bytes(32, 0xee));
  EXPECT_EQ(rules(c.t1, other), std::vector<Rule>{Rule::SameCounter});
  EXPECT_EQ(rules(other, c.t1), std::vector<Rule>{Rule::SameCounter});
}

TEST(Equivocation, R2BrokenLink) {
  Chain c;
  // Right counter and total, but not linked to t1.
  Tag forked = make_tag(kCert, 2, Bytes(32, 0x42), 500, 1500);
  EXPECT_EQ(rules(c.t1, forked), std::vector<Rule>{Rule::BrokenLink});
}

TEST(Equivocation, R3TotalBackwards) {
  Chain c;
  // A rolled-back wallet skips to counter 3: its total before this tag is
  // 1200 - 700 = 500, below t1's 1000, so money was spent twice.
  Tag skipped = make_tag(kCert, 3, Bytes(32, 0x42), 700, 1200);
  EXPECT_EQ(rules(c.t1, skipped), std::vector<Rule>{Rule::TotalBackwards});
  // Equal is fine: the total before b may equal a's total.
  Tag exact = make_tag(kCert, 3, Bytes(32, 0x42), 700, 1700);
  EXPECT_TRUE(rules(c.t1, exact).empty());
}

TEST(Equivocation, R2AndR3TogetherReportR2) {
  Chain c;
  Tag both = make_tag(kCert, 2, Bytes(32, 0x42), 500, 1200);  // unlinked and 700 < 1000
  EXPECT_EQ(rules(c.t1, both), (std::vector<Rule>{Rule::BrokenLink, Rule::TotalBackwards}));
  EXPECT_EQ(equivocation(c.t1, both), Rule::BrokenLink);
  auto proof = make_proof(both, c.t1);
  ASSERT_TRUE(proof.has_value());
  EXPECT_EQ(proof->rule, Rule::BrokenLink);
  EXPECT_EQ(proof->a.tag_hash(), c.t1.tag_hash());  // builders order a.counter <= b.counter
}

TEST(Equivocation, DifferentCertsNeverEquivocate) {
  Tag a = make_tag(kCert, 1, genesis(kCert), 100, 100);
  Tag b = make_tag(kOtherCert, 1, genesis(kOtherCert), 200, 200);
  EXPECT_TRUE(rules(a, b).empty());
}

TEST(OverCap, HighestCumAgainstHighestCap) {
  Chain c;
  EXPECT_FALSE(over_cap({}, {2000}));
  EXPECT_FALSE(over_cap({c.t1, c.t2}, {2000, 5000}));
  EXPECT_TRUE(over_cap({c.t1, c.t3}, {2000}));  // 2200 > 2000
  EXPECT_FALSE(over_cap({c.t3}, {2000, 5000, 2000}));
  EXPECT_THROW(over_cap({c.t1}, {}), std::invalid_argument);
}

TEST(LogTamper, EmptyAndMixedDevices) {
  EXPECT_FALSE(log_tamper({}).has_value());
  const Json& chain = test::vector("log_tamper", "chain_of_4");
  const Json& other = test::vector("merchant_knew", "b_paired_contact");
  std::vector<Dlog> mixed = {Dlog(Object::from_vector(chain.at("entries")[0]))};
  for (const Json& e : other.at("logs")) {
    Dlog d(Object::from_vector(e));
    if (d.device_pub() != mixed.front().device_pub()) {
      mixed.push_back(d);
      break;
    }
  }
  ASSERT_EQ(mixed.size(), 2u);
  EXPECT_THROW(log_tamper(mixed), std::invalid_argument);
}

}  // namespace
}  // namespace stormcash
