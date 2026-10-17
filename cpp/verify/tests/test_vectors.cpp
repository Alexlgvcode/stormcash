// The whole of spec/vectors.json, plus mutation tests: a runner that can't
// fail proves nothing, so corrupt one expectation at a time and require the
// runner to report it.
#include <gtest/gtest.h>

#include <functional>

#include "stormcash/vectors.hpp"
#include "support.hpp"

namespace stormcash {
namespace {

Json& find(Json& root, const std::string& section, const std::string& name) {
  for (Json& v : root.at(section)) {
    if (v.at("name") == name) return v;
  }
  throw std::runtime_error("no vector " + name);
}

TEST(Vectors, AllMatchWithNothingSkipped) {
  VectorReport report = run_vectors(test::vectors());
  EXPECT_EQ(report.format, "stormcash-vectors/1");
  EXPECT_EQ(report.vectors(), 124);
  EXPECT_EQ(report.failed(), 0) << format_report(report);
  EXPECT_EQ(report.skipped(), 0);
  EXPECT_TRUE(report.problems.empty());
  EXPECT_TRUE(report.ok(/*strict=*/true)) << format_report(report);
  // Every section in the file has a checker.
  for (const auto& s : report.sections) EXPECT_EQ(s.passed, s.vectors) << s.name;
}

struct Mutation {
  std::string label;
  std::string section;
  std::string vector;
  std::function<void(Json&)> mutate;
};

class VectorMutation : public ::testing::TestWithParam<Mutation> {};

TEST_P(VectorMutation, IsReportedAsAMismatch) {
  Json root = test::vectors();
  const Mutation& m = GetParam();
  m.mutate(find(root, m.section, m.vector));
  VectorReport report = run_vectors(root);
  EXPECT_EQ(report.failed(), 1) << format_report(report);
  EXPECT_FALSE(report.ok(false));
}

INSTANTIATE_TEST_SUITE_P(
    OneAtATime, VectorMutation,
    ::testing::Values(
        Mutation{"canonical_one_char", "objects", "tag_counter1",
                 [](Json& v) { v["canonical"] = v["canonical"].get<std::string>() + "0"; }},
        Mutation{"digest", "objects", "cert_v1", [](Json& v) { v["digest"] = std::string(64, '0'); }},
        Mutation{"transport_json_value", "objects", "mcert_pharmacy", [](Json& v) { v["json"]["mv"] = 2; }},
        Mutation{"invalid_object_claimed_valid", "objects", "cert_v1_tampered_cap", [](Json& v) { v["valid"] = true; }},
        Mutation{"item_id", "objects", "rcpt", [](Json& v) { v["id8"] = "0000000000000000"; }},
        Mutation{"encoding_error_claimed_ok", "encoding", "string_49_chars",
                 [](Json& v) {
                   v.erase("error");
                   v["rendered"] = v["value"];
                 }},
        Mutation{"encoding_rendered", "encoding", "string_list_sorted",
                 [](Json& v) { v["rendered"] = "b:1,a:20,a:3"; }},
        Mutation{"high_s_claimed_invalid", "signatures", "high_s_must_verify", [](Json& v) { v["valid"] = false; }},
        Mutation{"bad_signature_claimed_valid", "signatures", "s_equals_n",
                 [](Json& v) {
                   v["valid"] = true;
                   v["low_s"] = false;
                 }},
        Mutation{"der_raw", "der", "der_high_s", [](Json& v) { v["raw"] = v["raw_low_s"]; }},
        Mutation{"contact_id", "contact_ids", "gas_station_maya",
                 [](Json& v) { v["contact_id"] = std::string(64, 'a'); }},
        Mutation{"single_tag", "single_tag", "counter1_wrong_genesis", [](Json& v) { v["valid"] = true; }},
        Mutation{"rule_precedence", "equivocation", "r2_and_r3_reports_r2",
                 [](Json& v) { v["rule"] = "TOTAL_BACKWARDS"; }},
        Mutation{"rules_fired", "equivocation", "chain_1_3",
                 [](Json& v) { v["rules_fired"] = Json::array({"SAME_COUNTER"}); }},
        Mutation{"proof_validity", "proofs", "proof_forged_signature", [](Json& v) { v["valid"] = true; }},
        Mutation{"merchant_reason", "merchant_checks", "c4_other_request",
                 [](Json& v) { v["expect"]["reason"] = "WRONG_AMOUNT"; }},
        Mutation{"merchant_ok", "merchant_checks", "c6_replay",
                 [](Json& v) {
                   v["expect"] = {
                       {"ok", true}, {"check", nullptr}, {"reason", nullptr}, {"rule", nullptr}, {"conflict", nullptr}};
                 }},
        Mutation{"merchant_now", "merchant_checks", "ok_expired_within_tolerance",
                 [](Json& v) { v["now"] = v["now"].get<std::int64_t>() + 600; }},
        Mutation{"over_cap", "over_cap", "r4_storm_cap_then_over", [](Json& v) { v["steps"][2]["over_cap"] = false; }},
        Mutation{"log_tamper", "log_tamper", "fork_at_seq_2", [](Json& v) { v["expect"]["seq"] = 3; }},
        Mutation{"merchant_knew_one_sided", "merchant_knew", "c_one_sided_contact",
                 [](Json& v) { v["expect"]["fired"] = true; }},
        Mutation{"merchant_knew_clause", "merchant_knew", "b_paired_contact",
                 [](Json& v) { v["expect"]["clause"] = "HELD_IDS"; }}),
    [](const ::testing::TestParamInfo<Mutation>& param_info) { return param_info.param.label; });

TEST(Vectors, NothingIsSkippedSilently) {
  Json root = test::vectors();
  root["future_section"] = Json::array({Json{{"name", "x"}}});
  find(root, "single_tag", "counter0")["new_expectation"] = 1;
  root["constants"]["new_limit"] = 7;
  VectorReport report = run_vectors(root);
  EXPECT_EQ(report.failed(), 0);
  EXPECT_EQ(report.skipped(), 1);            // the unknown section's one vector
  EXPECT_TRUE(report.ok(/*strict=*/false));  // no mismatch...
  EXPECT_FALSE(report.ok(/*strict=*/true));  // ...but strict mode refuses the gaps
  std::string text = format_report(report);
  EXPECT_NE(text.find("future_section"), std::string::npos);
  EXPECT_NE(text.find("new_expectation"), std::string::npos);
  EXPECT_NE(text.find("new_limit"), std::string::npos);
}

TEST(Vectors, WrongFormatOrConstantsAreProblems) {
  Json root = test::vectors();
  root["format"] = "stormcash-vectors/2";
  root["constants"]["max_string_chars"] = 64;
  VectorReport report = run_vectors(root);
  EXPECT_EQ(report.problems.size(), 2u);
  EXPECT_FALSE(report.ok(false));
}

}  // namespace
}  // namespace stormcash
