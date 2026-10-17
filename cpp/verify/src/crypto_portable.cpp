// The portable backend (STORMCASH_CRYPTO=portable): no system library, so the
// same code builds natively and to WebAssembly.
//
// - SHA-256 is written out below from FIPS 180-4 (§4.1.2, §5.1.1, §6.2). It is
//   tested against NIST's examples and against Python's hashlib on every
//   length that crosses a padding boundary (tests/test_crypto.cpp).
// - The curve math is p256-m (Manuel Pégourié-Gonnard, from Mbed TLS;
//   Apache-2.0), compiled as portable C (verify/CMakeLists.txt). Its
//   p256_ecdsa_verify takes the 32-byte digest as the hash, rejects r or s
//   outside [1, n−1], accepts high-S, and validates the key: x, y < p and on
//   the curve. p256-m takes uncompressed keys, so p256m_sec1.c decompresses.
// - DER is parsed by hand, accepting strict DER only, the same inputs the
//   OpenSSL backend accepts.
//
// micro-ecc 1.1 was tried first. It rejects two valid signatures in Project
// Wycheproof's P-256 tests (tcId 60, "Edge case for Shamir multiplication",
// and tcId 210): its verify computes u1·G + u2·Q in one pass with an addition
// that has no doubling case. p256-m computes the two multiples separately and
// adds them with a full add-or-double, and passes all 262
// (tests/test_wycheproof.cpp).
#include <p256-m.h>

#include <algorithm>
#include <array>
#include <cstdint>

#include "crypto_backend.hpp"
#include "p256m_sec1.h"
#include "stormcash/crypto.hpp"

namespace stormcash::backend {
namespace {

// SHA-256 ------------------------------------------------------------------------

constexpr std::array<std::uint32_t, 64> kRoundConstants = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

constexpr std::array<std::uint32_t, 8> kInitialHash = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                                       0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};

constexpr std::uint32_t rotr(std::uint32_t x, unsigned n) { return (x >> n) | (x << (32 - n)); }

// One 64-byte block into the running hash (FIPS 180-4 §6.2.2).
void compress(std::array<std::uint32_t, 8>& h, const std::uint8_t* block) {
  std::array<std::uint32_t, 64> w{};
  for (std::size_t t = 0; t < 16; ++t) {
    w[t] = std::uint32_t{block[4 * t]} << 24 | std::uint32_t{block[4 * t + 1]} << 16 |
           std::uint32_t{block[4 * t + 2]} << 8 | std::uint32_t{block[4 * t + 3]};
  }
  for (std::size_t t = 16; t < 64; ++t) {
    std::uint32_t s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >> 3);
    std::uint32_t s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >> 10);
    w[t] = w[t - 16] + s0 + w[t - 7] + s1;
  }
  std::uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], k = h[7];
  for (std::size_t t = 0; t < 64; ++t) {
    std::uint32_t t1 = k + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + kRoundConstants[t] + w[t];
    std::uint32_t t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
    k = g;
    g = f;
    f = e;
    e = d + t1;
    d = c;
    c = b;
    b = a;
    a = t1 + t2;
  }
  h[0] += a;
  h[1] += b;
  h[2] += c;
  h[3] += d;
  h[4] += e;
  h[5] += f;
  h[6] += g;
  h[7] += k;
}

// DER -----------------------------------------------------------------------------

// The INTEGER at der[pos], in strict DER (short-form length, minimal, not
// negative), as 32 big-endian bytes. Advances pos past it.
void read_integer(const Bytes& der, std::size_t& pos, std::uint8_t* out32) {
  if (pos + 2 > der.size() || der[pos] != 0x02) throw CryptoError("invalid DER signature");
  std::size_t len = der[pos + 1];
  if (len & 0x80) throw CryptoError("signature is not strict DER");  // no integer here needs a long form
  if (len == 0 || pos + 2 + len > der.size()) throw CryptoError("invalid DER signature");
  const std::uint8_t* value = der.data() + pos + 2;
  if (value[0] & 0x80) throw CryptoError("signature scalar out of range");  // negative
  if (len > 1 && value[0] == 0x00 && !(value[1] & 0x80)) throw CryptoError("signature is not strict DER");
  if (len > 1 && value[0] == 0x00) {  // the sign byte in front of a high bit
    ++value;
    --len;
  }
  if (len > 32) throw CryptoError("signature scalar out of range");
  std::fill(out32, out32 + 32, std::uint8_t{0});
  std::copy(value, value + len, out32 + (32 - len));
  pos = static_cast<std::size_t>(value + len - der.data());
}

// A 32-byte big-endian scalar as a minimal DER INTEGER.
void write_integer(Bytes& out, const std::uint8_t* scalar32) {
  std::size_t start = 0;
  while (start < 31 && scalar32[start] == 0) ++start;
  bool sign_byte = scalar32[start] & 0x80;
  out.push_back(0x02);
  out.push_back(static_cast<std::uint8_t>(32 - start + (sign_byte ? 1 : 0)));
  if (sign_byte) out.push_back(0x00);
  out.insert(out.end(), scalar32 + start, scalar32 + 32);
}

}  // namespace

const char* const kName = "portable (p256-m, built-in SHA-256)";

Bytes sha256(const Bytes& data) {
  std::array<std::uint32_t, 8> h = kInitialHash;
  std::size_t full = data.size() / 64 * 64;
  for (std::size_t i = 0; i < full; i += 64) compress(h, data.data() + i);

  // Padding (FIPS 180-4 §5.1.1): 0x80, zeros, then the length in bits as a
  // 64-bit big-endian integer, filling one or two final blocks.
  std::array<std::uint8_t, 128> tail{};
  std::size_t rest = data.size() - full;
  std::copy(data.begin() + static_cast<std::ptrdiff_t>(full), data.end(), tail.begin());
  tail[rest] = 0x80;
  std::size_t tail_len = rest < 56 ? 64 : 128;
  std::uint64_t bits = static_cast<std::uint64_t>(data.size()) * 8;
  for (std::size_t i = 0; i < 8; ++i) tail[tail_len - 1 - i] = static_cast<std::uint8_t>(bits >> (8 * i));
  for (std::size_t i = 0; i < tail_len; i += 64) compress(h, tail.data() + i);

  Bytes out(kDigestLen);
  for (std::size_t i = 0; i < 8; ++i) {
    out[4 * i] = static_cast<std::uint8_t>(h[i] >> 24);
    out[4 * i + 1] = static_cast<std::uint8_t>(h[i] >> 16);
    out[4 * i + 2] = static_cast<std::uint8_t>(h[i] >> 8);
    out[4 * i + 3] = static_cast<std::uint8_t>(h[i]);
  }
  return out;
}

bool public_key_on_curve(const Bytes& pub) {
  std::array<std::uint8_t, 64> point{};
  return stormcash_p256_decompress(point.data(), pub.data()) == 0;
}

bool verify_prehashed(const Bytes& pub, const Bytes& digest, const Bytes& sig) {
  std::array<std::uint8_t, 64> point{};
  if (stormcash_p256_decompress(point.data(), pub.data()) != 0) return false;
  return p256_ecdsa_verify(sig.data(), point.data(), digest.data(), digest.size()) == P256_SUCCESS;
}

Bytes der_to_raw(const Bytes& der) {
  // SEQUENCE { INTEGER r, INTEGER s }. The longest one is 72 bytes, so its
  // length always has the short form.
  if (der.size() < 2 || der[0] != 0x30) throw CryptoError("invalid DER signature");
  if (der[1] & 0x80) throw CryptoError("signature is not strict DER");
  if (std::size_t{der[1]} + 2 != der.size()) throw CryptoError("invalid DER signature");
  Bytes raw(kSigLen);
  std::size_t pos = 2;
  read_integer(der, pos, raw.data());
  read_integer(der, pos, raw.data() + 32);
  if (pos != der.size()) throw CryptoError("invalid DER signature");
  return raw;
}

Bytes raw_to_der(const Bytes& raw) {
  Bytes body;
  write_integer(body, raw.data());
  write_integer(body, raw.data() + 32);
  Bytes der = {0x30, static_cast<std::uint8_t>(body.size())};
  der.insert(der.end(), body.begin(), body.end());
  return der;
}

}  // namespace stormcash::backend
