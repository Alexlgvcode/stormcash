#include <gtest/gtest.h>

#include "stormcash/crypto.hpp"
#include "support.hpp"

namespace stormcash {
namespace {

using test::hex;

const std::string kOrderHex = "ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551";

struct SignedDigest {
  Bytes pub, digest, sig;
};

SignedDigest low_s_vector() {
  const Json& v = test::vector("signatures", "low_s");
  return {hex(v.at("pub")), hex(v.at("digest")), hex(v.at("sig"))};
}

TEST(Sha256, NistVectors) {
  EXPECT_EQ(to_hex(sha256(to_bytes("abc"))), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  EXPECT_EQ(to_hex(sha256({})), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
}

TEST(PublicKey, CompressedPointsOnly) {
  Bytes good = test::vector_pub("maya");
  EXPECT_TRUE(is_valid_public_key(good));
  Bytes wrong_prefix = good;
  wrong_prefix[0] = 0x04;
  EXPECT_FALSE(is_valid_public_key(wrong_prefix));
  EXPECT_FALSE(is_valid_public_key(Bytes(good.begin(), good.end() - 1)));
  // x = 1 has no point on P-256: x^3 - 3x + b is not a square mod p.
  Bytes off_curve(33, 0x00);
  off_curve[0] = 0x02;
  off_curve[32] = 0x01;
  EXPECT_FALSE(is_valid_public_key(off_curve));
}

TEST(Verify, ValidSignature) {
  auto v = low_s_vector();
  EXPECT_TRUE(verify_digest(v.pub, v.digest, v.sig));
}

TEST(Verify, AcceptsHighS) {
  auto v = low_s_vector();
  // (r, n - s) is the same signature with high S.
  Bytes high = v.sig;
  Bytes order = hex(kOrderHex);
  int borrow = 0;
  for (int i = 31; i >= 0; --i) {
    int d = int{order[static_cast<std::size_t>(i)]} - int{v.sig[static_cast<std::size_t>(32 + i)]} - borrow;
    borrow = d < 0;
    high[static_cast<std::size_t>(32 + i)] = static_cast<std::uint8_t>(d + 256 * borrow);
  }
  EXPECT_FALSE(is_low_s(high));
  EXPECT_TRUE(verify_digest(v.pub, v.digest, high));
  EXPECT_EQ(normalize_low_s(high), v.sig);
}

TEST(Verify, RejectsTampering) {
  auto v = low_s_vector();
  Bytes sig = v.sig;
  sig[10] ^= 0x01;
  EXPECT_FALSE(verify_digest(v.pub, v.digest, sig));
  Bytes digest = v.digest;
  digest[0] ^= 0x80;
  EXPECT_FALSE(verify_digest(v.pub, digest, v.sig));
  EXPECT_FALSE(verify_digest(test::vector_pub("pharmacy"), v.digest, v.sig));
}

TEST(Verify, RejectsMalformedInputWithoutThrowing) {
  auto v = low_s_vector();
  Bytes r_zero = v.sig;
  std::fill(r_zero.begin(), r_zero.begin() + 32, 0);
  EXPECT_FALSE(verify_digest(v.pub, v.digest, r_zero));
  Bytes s_zero = v.sig;
  std::fill(s_zero.begin() + 32, s_zero.end(), 0);
  EXPECT_FALSE(verify_digest(v.pub, v.digest, s_zero));
  Bytes s_is_n = v.sig;
  Bytes order = hex(kOrderHex);
  std::copy(order.begin(), order.end(), s_is_n.begin() + 32);
  EXPECT_FALSE(verify_digest(v.pub, v.digest, s_is_n));
  EXPECT_FALSE(verify_digest(v.pub, v.digest, Bytes(v.sig.begin(), v.sig.end() - 1)));
  EXPECT_FALSE(verify_digest(v.pub, Bytes(31, 0), v.sig));
  EXPECT_FALSE(verify_digest(Bytes(33, 0), v.digest, v.sig));
}

TEST(Der, RoundTripsTheVector) {
  const Json& v = test::vector("der", "der_short_integer");
  Bytes raw = der_to_raw(hex(v.at("der")));
  EXPECT_EQ(to_hex(raw), test::str(v.at("raw")));
  EXPECT_EQ(to_hex(raw_to_der(raw)), test::str(v.at("der")));
  EXPECT_EQ(raw[0], 0x00);  // a 31-byte r is left-padded to 32 bytes
}

TEST(Der, IsStrict) {
  Bytes der = hex(test::vector("der", "der_high_s").at("der"));
  Bytes trailing = der;
  trailing.push_back(0x00);
  EXPECT_THROW(der_to_raw(trailing), CryptoError);
  // Same signature with a long-form length (BER, not DER).
  Bytes long_form = {0x30, 0x81};
  long_form.insert(long_form.end(), der.begin() + 1, der.end());
  EXPECT_THROW(der_to_raw(long_form), CryptoError);
  EXPECT_THROW(der_to_raw({0x30, 0x00}), CryptoError);
  EXPECT_THROW(der_to_raw({}), CryptoError);
}

TEST(LowS, NormalizeIsIdempotent) {
  auto v = low_s_vector();
  EXPECT_TRUE(is_low_s(v.sig));
  EXPECT_EQ(normalize_low_s(v.sig), v.sig);
  // s = n - 1 is high; its low form is 1.
  Bytes sig = v.sig;
  Bytes n_minus_1 = hex(kOrderHex);
  n_minus_1[31] -= 1;
  std::copy(n_minus_1.begin(), n_minus_1.end(), sig.begin() + 32);
  Bytes low = normalize_low_s(sig);
  EXPECT_EQ(to_hex(Bytes(low.begin() + 32, low.end())), std::string(62, '0') + "01");
}

}  // namespace
}  // namespace stormcash
