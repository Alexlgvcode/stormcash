// Project Wycheproof's ECDSA P-256 / SHA-256 tests in IEEE P1363 form (raw
// r || s, the signature format of spec §7.1): 262 signatures that must or must
// not verify, including the edge cases where implementations go wrong (r or s
// out of range, s = 1 or n − 1, points that double during the multiplication,
// keys with extreme coordinates). Both crypto backends run them.
//
// Wycheproof signs the message with SHA-256, so the digest is computed here
// and verified as the prehashed message. Its keys are uncompressed; they are
// compressed here (0x02 or 0x03 by the parity of y), the form StormCash uses.
#include <gtest/gtest.h>

#include "stormcash/crypto.hpp"
#include "support.hpp"

namespace stormcash {
namespace {

Bytes compress(const Bytes& uncompressed) {
  if (uncompressed.size() != 65 || uncompressed[0] != 0x04) throw std::runtime_error("not an uncompressed point");
  Bytes out(uncompressed.begin(), uncompressed.begin() + 33);
  out[0] = (uncompressed[64] & 1) ? 0x03 : 0x02;
  return out;
}

TEST(Wycheproof, EcdsaP256Sha256P1363) {
  Json file = Json::parse(test::read_file(STORMCASH_WYCHEPROOF_PATH));
  ASSERT_EQ(test::str(file.at("algorithm")), "ECDSA");
  int run = 0, valid = 0;
  for (const Json& group : file.at("testGroups")) {
    ASSERT_EQ(test::str(group.at("type")), "EcdsaP1363Verify");
    ASSERT_EQ(test::str(group.at("sha")), "SHA-256");
    ASSERT_EQ(test::str(group.at("publicKey").at("curve")), "secp256r1");
    Bytes pub = compress(test::hex(group.at("publicKey").at("uncompressed")));
    ASSERT_TRUE(is_valid_public_key(pub));
    for (const Json& t : group.at("tests")) {
      std::string result = test::str(t.at("result"));
      ASSERT_TRUE(result == "valid" || result == "invalid") << "tcId " << t.at("tcId") << ": " << result;
      bool expected = result == "valid";
      bool got = verify_digest(pub, sha256(test::hex(t.at("msg"))), test::hex(t.at("sig")));
      EXPECT_EQ(got, expected) << "tcId " << t.at("tcId") << " (" << test::str(t.at("comment")) << ")";
      ++run;
      valid += expected;
    }
  }
  EXPECT_EQ(run, file.at("numberOfTests").get<int>());
  EXPECT_GT(valid, 0);
}

}  // namespace
}  // namespace stormcash
