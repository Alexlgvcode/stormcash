#include "stormcash/crypto.hpp"

#include <algorithm>
#include <array>

#include "crypto_backend.hpp"

namespace stormcash {
namespace {

// 256-bit big-endian scalars. r and s are compared with the group order n and
// S is normalized with plain byte arithmetic, so the range rules are visible
// here instead of hidden inside a bignum library, and both backends get the
// same ones.
using Scalar = std::array<std::uint8_t, 32>;

// Order n of the P-256 group.
constexpr Scalar kOrder = {0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF,
                           0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xBC, 0xE6, 0xFA, 0xAD, 0xA7, 0x17,
                           0x9E, 0x84, 0xF3, 0xB9, 0xCA, 0xC2, 0xFC, 0x63, 0x25, 0x51};

// floor(n / 2): a one-bit right shift of n.
constexpr Scalar half(const Scalar& x) {
  Scalar out{};
  unsigned carry = 0;
  for (std::size_t i = 0; i < x.size(); ++i) {
    out[i] = static_cast<std::uint8_t>((x[i] >> 1) | (carry << 7));
    carry = x[i] & 1u;
  }
  return out;
}
constexpr Scalar kHalfOrder = half(kOrder);

// -1, 0, 1 like memcmp; equal-length big-endian, so byte order = numeric order.
int compare(const Scalar& a, const Scalar& b) {
  for (std::size_t i = 0; i < a.size(); ++i) {
    if (a[i] != b[i]) return a[i] < b[i] ? -1 : 1;
  }
  return 0;
}

bool is_zero(const Scalar& a) {
  for (std::uint8_t b : a) {
    if (b) return false;
  }
  return true;
}

// a − b for a ≥ b.
Scalar subtract(const Scalar& a, const Scalar& b) {
  Scalar out{};
  int borrow = 0;
  for (std::size_t i = a.size(); i-- > 0;) {
    int d = int{a[i]} - int{b[i]} - borrow;
    borrow = d < 0 ? 1 : 0;
    out[i] = static_cast<std::uint8_t>(d + (borrow << 8));
  }
  return out;
}

// 0 < x < n: the valid range for r and s.
bool in_scalar_range(const Scalar& x) { return !is_zero(x) && compare(x, kOrder) < 0; }

Scalar scalar_at(const Bytes& raw, std::size_t offset) {
  Scalar out{};
  std::copy(raw.begin() + static_cast<std::ptrdiff_t>(offset), raw.begin() + static_cast<std::ptrdiff_t>(offset + 32),
            out.begin());
  return out;
}

bool has_compressed_prefix(const Bytes& pub) { return pub.size() == kPubLen && (pub[0] == 0x02 || pub[0] == 0x03); }

}  // namespace

const char* crypto_backend() { return backend::kName; }

Bytes sha256(const Bytes& data) { return backend::sha256(data); }

bool is_valid_public_key(const Bytes& pub) { return has_compressed_prefix(pub) && backend::public_key_on_curve(pub); }

bool verify_digest(const Bytes& pub, const Bytes& digest, const Bytes& sig) {
  if (digest.size() != kDigestLen || sig.size() != kSigLen) return false;
  if (!in_scalar_range(scalar_at(sig, 0)) || !in_scalar_range(scalar_at(sig, 32))) return false;
  if (!has_compressed_prefix(pub)) return false;
  // No S check: high-S is accepted.
  return backend::verify_prehashed(pub, digest, sig);
}

Bytes der_to_raw(const Bytes& der) {
  Bytes raw = backend::der_to_raw(der);
  if (!in_scalar_range(scalar_at(raw, 0)) || !in_scalar_range(scalar_at(raw, 32))) {
    throw CryptoError("signature scalar out of range");
  }
  return raw;
}

Bytes raw_to_der(const Bytes& raw) {
  if (raw.size() != kSigLen) throw CryptoError("raw signature must be 64 bytes");
  return backend::raw_to_der(raw);
}

bool is_low_s(const Bytes& raw) {
  if (raw.size() != kSigLen) throw CryptoError("raw signature must be 64 bytes");
  return compare(scalar_at(raw, 32), kHalfOrder) <= 0;
}

Bytes normalize_low_s(const Bytes& raw) {
  if (is_low_s(raw)) return raw;
  Scalar low = subtract(kOrder, scalar_at(raw, 32));
  Bytes out(raw.begin(), raw.begin() + 32);
  out.insert(out.end(), low.begin(), low.end());
  return out;
}

}  // namespace stormcash
