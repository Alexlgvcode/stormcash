#include <gtest/gtest.h>

#include "stormcash/bytes.hpp"

namespace stormcash {
namespace {

TEST(Hex, RoundTripsLowercase) {
  Bytes data = {0x00, 0x0f, 0xa0, 0xff};
  EXPECT_EQ(to_hex(data), "000fa0ff");
  EXPECT_EQ(from_hex("000fa0ff"), data);
  EXPECT_EQ(from_hex(""), Bytes{});
}

TEST(Hex, RejectsOtherSpellings) {
  EXPECT_THROW(from_hex("000FA0FF"), EncodingError);  // uppercase: one value, one spelling
  EXPECT_THROW(from_hex("abc"), EncodingError);       // odd length
  EXPECT_THROW(from_hex("zz"), EncodingError);
  EXPECT_THROW(from_hex("ab cd"), EncodingError);
}

// RFC 4648 §10 test vectors, unpadded.
TEST(Base64Url, Rfc4648Vectors) {
  const std::pair<std::string, std::string> cases[] = {
      {"", ""},           {"f", "Zg"},          {"fo", "Zm8"},          {"foo", "Zm9v"},
      {"foob", "Zm9vYg"}, {"fooba", "Zm9vYmE"}, {"foobar", "Zm9vYmFy"},
  };
  for (const auto& [plain, encoded] : cases) {
    EXPECT_EQ(b64u_encode(to_bytes(plain)), encoded);
    EXPECT_EQ(b64u_decode(encoded), to_bytes(plain));
  }
}

TEST(Base64Url, UsesTheUrlAlphabet) {
  Bytes data = {0xfb, 0xff, 0xbf};
  EXPECT_EQ(b64u_encode(data), "-_-_");
  EXPECT_EQ(b64u_decode("-_-_"), data);
}

TEST(Base64Url, IsStrict) {
  EXPECT_THROW(b64u_decode("Zg=="), EncodingError);  // padding
  EXPECT_THROW(b64u_decode("+/+/"), EncodingError);  // standard alphabet
  EXPECT_THROW(b64u_decode("Z"), EncodingError);     // length 1 mod 4 encodes nothing
  EXPECT_THROW(b64u_decode("Zh"), EncodingError);    // decodes to "f" too, but isn't canonical ("Zg")
  EXPECT_THROW(b64u_decode("Zm9 v"), EncodingError);
  EXPECT_THROW(b64u_decode("Zm9v\n"), EncodingError);
}

}  // namespace
}  // namespace stormcash
