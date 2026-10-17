// The proof checker on real GET /v1/proof responses (fixtures/capture_proofs.py
// captures them from the server app), and on tampered copies of them.
#include <gtest/gtest.h>

#include "stormcash/proof_check.hpp"
#include "support.hpp"

namespace stormcash {
namespace {

Json fixture(const std::string& name) {
  return Json::parse(test::read_file(std::string(STORMCASH_FIXTURES_DIR) + "/proof_" + name + ".json"));
}

Bytes file_server_pub(const Json& doc) { return b64u_decode(doc.at("server_pub").get<std::string>()); }

ProofVerdict check(const Json& doc, bool pin = true) {
  return check_proof(doc, pin ? std::optional<Bytes>(file_server_pub(doc)) : std::nullopt);
}

bool has_failed_line(const ProofVerdict& v, const std::string& fragment) {
  for (const auto& line : v.lines) {
    if (!line.ok && line.text.find(fragment) != std::string::npos) return true;
  }
  return false;
}

class RealProofs : public ::testing::TestWithParam<std::string> {};

TEST_P(RealProofs, VerifyAsProven) {
  Json doc = fixture(GetParam());
  ProofVerdict v = check(doc);
  EXPECT_EQ(v.status, ProofStatus::Proven) << format_proof(v);
  EXPECT_EQ(v.rule, test::str(doc.at("rule")));
  EXPECT_EQ(v.verdict.rfind(v.rule + ":", 0), 0u) << v.verdict;
  EXPECT_NE(v.verdict.find("signed by StormCash"), std::string::npos);
}

INSTANTIATE_TEST_SUITE_P(Fixtures, RealProofs,
                         ::testing::Values("same_counter", "broken_link", "total_backwards", "merchant_knew_held_ids"));

TEST(Proof, VerdictWording) {
  ProofVerdict v = check(fixture("same_counter"));
  EXPECT_EQ(v.verdict.rfind("SAME_COUNTER: both signatures valid under holder key 02700ac63d3db3d6...; certificate "
                            "signed by StormCash",
                            0),
            0u)
      << v.verdict;
}

TEST(Proof, UnpinnedKeyIsSaid) {
  ProofVerdict v = check(fixture("same_counter"), /*pin=*/false);
  EXPECT_EQ(v.status, ProofStatus::Proven);
  EXPECT_NE(v.verdict.find("not pinned"), std::string::npos);
  EXPECT_FALSE(v.notes.empty());
}

TEST(Proof, ClauseBIsIncompleteNotProven) {
  ProofVerdict v = check(fixture("merchant_knew_paired_contact"));
  EXPECT_EQ(v.status, ProofStatus::Incomplete) << format_proof(v);
  EXPECT_NE(v.verdict.find("NOT shown"), std::string::npos);
}

TEST(Proof, WrongServerKeyFails) {
  Json doc = fixture("same_counter");
  ProofVerdict v = check_proof(doc, test::vector_pub("server"));  // a different, valid key
  EXPECT_EQ(v.status, ProofStatus::Invalid);
  EXPECT_TRUE(has_failed_line(v, "CERT"));
}

TEST(Proof, TamperedSignedFieldFails) {
  Json doc = fixture("same_counter");
  doc["tag_b"]["json"]["amt"] = doc["tag_b"]["json"]["amt"].get<int>() + 100;
  ProofVerdict v = check(doc);
  EXPECT_EQ(v.status, ProofStatus::Invalid);
  EXPECT_TRUE(has_failed_line(v, "TAG B"));
}

TEST(Proof, DisplayedFieldsMustMatchWhatIsSigned) {
  Json doc = fixture("same_counter");
  doc["tag_a"]["fields"]["amount_cents"] = 1;  // the page would show $0.01; the signature says otherwise
  ProofVerdict v = check(doc);
  EXPECT_EQ(v.status, ProofStatus::Invalid);
  EXPECT_TRUE(has_failed_line(v, "TAG A: the fields and signed text shown"));

  Json doc2 = fixture("same_counter");
  doc2["cert"]["canonical"] = doc2["cert"]["canonical"].get<std::string>() + "0";
  EXPECT_EQ(check(doc2).status, ProofStatus::Invalid);
}

TEST(Proof, RuleMustHoldForTheSignedFields) {
  Json doc = fixture("same_counter");
  doc["rule"] = "TOTAL_BACKWARDS";
  ProofVerdict v = check(doc);
  EXPECT_EQ(v.status, ProofStatus::Invalid);
  EXPECT_TRUE(has_failed_line(v, "TOTAL_BACKWARDS holds"));
}

TEST(Proof, HolderKeyMustBeTheCertificates) {
  Json doc = fixture("same_counter");
  doc["holder_pub"] = b64u_encode(test::vector_pub("maya"));
  EXPECT_EQ(check(doc).status, ProofStatus::Invalid);
}

TEST(Proof, TamperedLogEntryFails) {
  Json doc = fixture("merchant_knew_held_ids");
  doc["log_entries"][0]["json"]["hi"] = Json::array();
  doc["log_entries"][0]["fields"]["held_ids"] = Json::array();
  doc["log_entries"][0]["canonical"] = Object::from_json("DLOG", doc["log_entries"][0]["json"]).canonical();
  doc["log_entries"][0]["digest"] = to_hex(Object::from_json("DLOG", doc["log_entries"][0]["json"]).digest());
  ProofVerdict v = check(doc);
  EXPECT_EQ(v.status, ProofStatus::Invalid) << format_proof(v);
  EXPECT_TRUE(has_failed_line(v, "log entry 1 (ACCEPT"));
}

TEST(Proof, RulesWithoutATagPairAreNotVerifiable) {
  Json doc = fixture("same_counter");
  doc["rule"] = "OVER_CAP";
  EXPECT_EQ(check(doc).status, ProofStatus::Invalid);
}

TEST(Proof, MalformedDocumentsThrow) {
  Json doc = fixture("same_counter");
  doc.erase("tag_b");
  EXPECT_THROW(check_proof(doc, std::nullopt), EncodingError);
  EXPECT_THROW(check_proof(Json::array(), std::nullopt), EncodingError);
  Json padded = fixture("same_counter");
  padded["tag_a"]["json"]["sig"] = padded["tag_a"]["json"]["sig"].get<std::string>() + "==";
  EXPECT_THROW(check_proof(padded, std::nullopt), EncodingError);
}

TEST(Proof, ServerKeyArgument) {
  Bytes pub = test::vector_pub("server");
  EXPECT_EQ(parse_public_key_arg(to_hex(pub)), pub);
  EXPECT_EQ(parse_public_key_arg(b64u_encode(pub)), pub);
  EXPECT_THROW(parse_public_key_arg("02" + std::string(63, '0') + "1"), EncodingError);  // x = 1 isn't on the curve
  EXPECT_THROW(parse_public_key_arg("nope"), EncodingError);
}

}  // namespace
}  // namespace stormcash
