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
  // 56 bytes: the length no longer fits in the first block, so padding takes two.
  EXPECT_EQ(to_hex(sha256(to_bytes("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"))),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
  EXPECT_EQ(to_hex(sha256(Bytes(1000000, 'a'))), "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
}

TEST(Sha256, EveryLengthAcrossPaddingBoundaries) {
  // The digests of every length from 0 to 299 bytes of (7i + 3) mod 256,
  // concatenated and hashed once more. The reference is Python's hashlib:
  //   b"".join(sha256(bytes((7*i+3) & 0xff for i in range(n))).digest() for n in range(300))
  Bytes all;
  for (std::size_t n = 0; n < 300; ++n) {
    Bytes msg(n);
    for (std::size_t i = 0; i < n; ++i) msg[i] = static_cast<std::uint8_t>((7 * i + 3) & 0xff);
    Bytes d = sha256(msg);
    all.insert(all.end(), d.begin(), d.end());
  }
  EXPECT_EQ(to_hex(sha256(all)), "7b074096cabb18dd0d1b468a173cb2f97f80e952525bca29542e606fd6d0753a");
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

TEST(PublicKey, XMustBeBelowP) {
  // x = p and x = 2^256 − 1 are 32-byte values but not field elements.
  Bytes x_is_p = hex("02ffffffff00000001000000000000000000000000ffffffffffffffffffffffff");
  EXPECT_FALSE(is_valid_public_key(x_is_p));
  Bytes x_max(33, 0xff);
  x_max[0] = 0x03;
  EXPECT_FALSE(is_valid_public_key(x_max));
}

TEST(PublicKey, OtherParityIsTheOtherPoint) {
  // Flipping 0x02/0x03 gives the negated point: still a valid key, not the signer's.
  auto v = low_s_vector();
  Bytes flipped = v.pub;
  flipped[0] ^= 0x01;
  EXPECT_TRUE(is_valid_public_key(flipped));
  EXPECT_FALSE(verify_digest(flipped, v.digest, v.sig));
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

TEST(Der, RejectsWhatOnlyBerAllows) {
  Bytes der = hex(test::vector("der", "der_high_s").at("der"));
  // A redundant leading zero on r.
  Bytes padded = {0x30, static_cast<std::uint8_t>(der[1] + 1), 0x02, static_cast<std::uint8_t>(der[3] + 1), 0x00};
  padded.insert(padded.end(), der.begin() + 4, der.end());
  EXPECT_THROW(der_to_raw(padded), CryptoError);
  // A negative integer, an empty one, and a long-form integer length.
  EXPECT_THROW(der_to_raw(hex("3006020180020101")), CryptoError);
  EXPECT_THROW(der_to_raw(hex("30050200020101")), CryptoError);
  EXPECT_THROW(der_to_raw(hex("300702810101020101")), CryptoError);
  // Something after s inside the SEQUENCE.
  EXPECT_THROW(der_to_raw(hex("30080201010201010500")), CryptoError);
  // A 33-byte r (too big for P-256), and r = 0.
  EXPECT_THROW(der_to_raw(hex("3026022101" + std::string(64, '0') + "020101")), CryptoError);
  EXPECT_THROW(der_to_raw(hex("3006020100020101")), CryptoError);
  // r = n: strict DER, but out of range.
  EXPECT_THROW(der_to_raw(hex("3026022100" + kOrderHex + "020101")), CryptoError);
  EXPECT_EQ(to_hex(der_to_raw(hex("3006020101020101"))), std::string(62, '0') + "01" + std::string(62, '0') + "01");
}

TEST(Der, EncodesMinimalIntegers) {
  // r = 1, s with its top bit set (needs a 0x00 sign byte).
  Bytes raw(64, 0);
  raw[31] = 0x01;
  std::fill(raw.begin() + 32, raw.end(), 0x80);
  Bytes der = raw_to_der(raw);
  std::string s_hex;
  for (int i = 0; i < 32; ++i) s_hex += "80";
  EXPECT_EQ(to_hex(der), "3026020101022100" + s_hex);
  EXPECT_EQ(der_to_raw(der), raw);
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
