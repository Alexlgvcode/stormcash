#include <gtest/gtest.h>

#include "stormcash/encoding.hpp"
#include "support.hpp"

namespace stormcash {
namespace {

std::string repeat(const std::string& s, int n) {
  std::string out;
  for (int i = 0; i < n; ++i) out += s;
  return out;
}

const std::string kCombiningAcute = "\xCC\x81";   // U+0301
const std::string kEAcute = "\xC3\xA9";           // U+00E9, the NFC of "e" + U+0301
const std::string kCyclone = "\xF0\x9F\x8C\x80";  // U+1F300, outside the BMP

TEST(RenderInt, Range) {
  EXPECT_EQ(render_int(0), "0");
  EXPECT_EQ(render_int(1792238400), "1792238400");
  EXPECT_EQ(render_int(kMaxInt), "9007199254740991");
  EXPECT_THROW(render_int(-1), EncodingError);
  EXPECT_THROW(render_int(kMaxInt + 1), EncodingError);
}

TEST(RenderBytes, ChecksLength) {
  EXPECT_EQ(render_bytes({0xab, 0xcd}, 2), "abcd");
  EXPECT_EQ(render_bytes({0xab, 0xcd}), "abcd");
  EXPECT_THROW(render_bytes({0xab}, 2), EncodingError);
}

TEST(RenderString, NormalizesToNfc) {
  EXPECT_EQ(render_string("Cafe" + kCombiningAcute), "Caf" + kEAcute);
  EXPECT_EQ(render_string(""), "");
}

TEST(RenderString, ForbiddenCharacters) {
  EXPECT_THROW(render_string("a|b"), EncodingError);
  EXPECT_THROW(render_string("a,b"), EncodingError);
  EXPECT_THROW(render_string("a\nb"), EncodingError);
  EXPECT_EQ(render_string("a\tb"), "a\tb");  // only the three separators are forbidden
}

TEST(RenderString, LengthCountsCodePointsAfterNfc) {
  EXPECT_NO_THROW(render_string(repeat("x", 48)));
  EXPECT_THROW(render_string(repeat("x", 49)), EncodingError);
  // An astral character is one code point (two UTF-16 units, four UTF-8 bytes).
  EXPECT_NO_THROW(render_string(repeat(kCyclone, 48)));
  EXPECT_THROW(render_string(repeat(kCyclone, 49)), EncodingError);
  // 49 "e + combining acute" pairs are 98 code points before NFC and 49 after.
  EXPECT_EQ(render_string(repeat("e" + kCombiningAcute, 48)), repeat(kEAcute, 48));
  EXPECT_THROW(render_string(repeat("e" + kCombiningAcute, 49)), EncodingError);
}

TEST(RenderString, RejectsInvalidUtf8) {
  EXPECT_THROW(render_string("\xff"), EncodingError);
  EXPECT_THROW(render_string("\xC3"), EncodingError);  // truncated sequence
}

TEST(RenderString, EmbeddedNulIsKeptAndCounted) {
  std::string with_nul("a\0b", 3);
  EXPECT_EQ(render_string(with_nul), with_nul);
  EXPECT_EQ(count_code_points(with_nul), 3u);
}

TEST(RenderEnum, Tokens) {
  EXPECT_EQ(render_enum("ACCEPT"), "ACCEPT");
  EXPECT_EQ(render_enum("C6"), "C6");
  EXPECT_EQ(render_enum("SAME_COUNTER"), "SAME_COUNTER");
  EXPECT_THROW(render_enum("accept"), EncodingError);
  EXPECT_THROW(render_enum("6C"), EncodingError);
  EXPECT_THROW(render_enum(""), EncodingError);
  EXPECT_THROW(render_enum("A-B"), EncodingError);
  const std::string_view allowed[] = {"ACCEPT", "REFUSE"};
  EXPECT_EQ(render_enum("REFUSE", allowed), "REFUSE");
  EXPECT_THROW(render_enum("CONTACT", allowed), EncodingError);
}

TEST(RenderLists, SortedAndJoined) {
  EXPECT_EQ(render_bytes_list({{0xff, 0x01}, {0x00, 0xff}, {0x0a, 0x00}}, 2), "00ff,0a00,ff01");
  EXPECT_EQ(render_bytes_list({}), "");
  EXPECT_THROW(render_bytes_list({{0x00}, {0x00, 0x01}}, 2), EncodingError);
  EXPECT_EQ(render_string_list({"b:1", "a:20", "a:3"}), "a:20,a:3,b:1");
  EXPECT_EQ(render_string_list({}), "");
}

TEST(RenderLists, StringsSortByUtf8BytesNotUtf16Units) {
  // U+FF5E sorts before U+1F600 by code point and by UTF-8 bytes (EF.. < F0..),
  // but after it by UTF-16 units (FF5E > D83D), which is how JS sorts strings.
  const std::string fullwidth_tilde = "\xEF\xBD\x9E";
  const std::string grinning_face = "\xF0\x9F\x98\x80";
  EXPECT_EQ(render_string_list({grinning_face, fullwidth_tilde}), fullwidth_tilde + "," + grinning_face);
}

TEST(Canonical, PrefixTypeAndFields) {
  EXPECT_EQ(canonical("GEN", {"abc"}), "SC1|GEN|abc");
  EXPECT_EQ(canonical("RCPT", {"1", ""}), "SC1|RCPT|1|");
  EXPECT_THROW(canonical("gen", {"abc"}), EncodingError);
}

TEST(Canonical, DigestIsSha256OfUtf8) {
  const Json& gen = test::vector("objects", "gen_maya");
  EXPECT_EQ(to_hex(digest(test::str(gen.at("canonical")))), test::str(gen.at("digest")));
}

}  // namespace
}  // namespace stormcash
