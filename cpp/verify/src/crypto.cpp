#include "stormcash/crypto.hpp"

#include <openssl/core_names.h>
#include <openssl/ec.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/params.h>

#include <array>
#include <memory>

namespace stormcash {
namespace {

// 256-bit big-endian scalars. r and s are compared with the group order n and
// S is normalized with plain byte arithmetic, so the range rules are visible
// here instead of hidden inside a bignum library.
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

// RAII for the OpenSSL objects used here.
struct OpenSslFree {
  void operator()(EVP_PKEY* p) const { EVP_PKEY_free(p); }
  void operator()(EVP_PKEY_CTX* p) const { EVP_PKEY_CTX_free(p); }
  void operator()(ECDSA_SIG* p) const { ECDSA_SIG_free(p); }
  void operator()(BIGNUM* p) const { BN_free(p); }
};
template <typename T>
using Owned = std::unique_ptr<T, OpenSslFree>;

// OpenSSL reports failures on a per-thread error queue. A failed check here is
// an expected answer ("not valid"), so drop the queued errors with it.
struct ClearErrorsOnExit {
  ~ClearErrorsOnExit() { ERR_clear_error(); }
};

// A P-256 public key from 33 SEC1 compressed bytes, or null if the bytes are
// not a point on the curve.
Owned<EVP_PKEY> load_public_key(const Bytes& pub) {
  if (pub.size() != kPubLen || (pub[0] != 0x02 && pub[0] != 0x03)) return nullptr;
  Owned<EVP_PKEY_CTX> ctx(EVP_PKEY_CTX_new_from_name(nullptr, "EC", nullptr));
  if (!ctx || EVP_PKEY_fromdata_init(ctx.get()) != 1) return nullptr;

  char group[] = "prime256v1";  // OSSL_PARAM wants a mutable buffer
  Bytes point = pub;
  OSSL_PARAM params[] = {
      OSSL_PARAM_construct_utf8_string(OSSL_PKEY_PARAM_GROUP_NAME, group, 0),
      OSSL_PARAM_construct_octet_string(OSSL_PKEY_PARAM_PUB_KEY, point.data(), point.size()),
      OSSL_PARAM_construct_end(),
  };
  EVP_PKEY* raw_key = nullptr;
  if (EVP_PKEY_fromdata(ctx.get(), &raw_key, EVP_PKEY_PUBLIC_KEY, params) != 1) return nullptr;
  Owned<EVP_PKEY> key(raw_key);

  // Decompression already fails for an x with no point on the curve; check
  // the point explicitly anyway rather than rely on that.
  Owned<EVP_PKEY_CTX> check(EVP_PKEY_CTX_new_from_pkey(nullptr, key.get(), nullptr));
  if (!check || EVP_PKEY_public_check(check.get()) != 1) return nullptr;
  return key;
}

Owned<ECDSA_SIG> sig_from_raw(const Bytes& raw) {
  Owned<ECDSA_SIG> sig(ECDSA_SIG_new());
  Owned<BIGNUM> r(BN_bin2bn(raw.data(), 32, nullptr));
  Owned<BIGNUM> s(BN_bin2bn(raw.data() + 32, 32, nullptr));
  if (!sig || !r || !s || ECDSA_SIG_set0(sig.get(), r.get(), s.get()) != 1) {
    throw CryptoError("out of memory building a signature");
  }
  r.release();  // now owned by sig
  s.release();
  return sig;
}

Bytes der_from_sig(const ECDSA_SIG* sig) {
  int len = i2d_ECDSA_SIG(sig, nullptr);
  if (len <= 0) throw CryptoError("could not DER-encode a signature");
  Bytes der(static_cast<std::size_t>(len));
  unsigned char* p = der.data();
  i2d_ECDSA_SIG(sig, &p);
  return der;
}

}  // namespace

Bytes sha256(const Bytes& data) {
  Bytes out(kDigestLen);
  unsigned int len = 0;
  if (EVP_Digest(data.data(), data.size(), out.data(), &len, EVP_sha256(), nullptr) != 1 || len != kDigestLen) {
    ERR_clear_error();
    throw CryptoError("SHA-256 failed");
  }
  return out;
}

bool is_valid_public_key(const Bytes& pub) {
  ClearErrorsOnExit clear;
  return load_public_key(pub) != nullptr;
}

bool verify_digest(const Bytes& pub, const Bytes& digest, const Bytes& sig) {
  ClearErrorsOnExit clear;
  if (digest.size() != kDigestLen || sig.size() != kSigLen) return false;
  if (!in_scalar_range(scalar_at(sig, 0)) || !in_scalar_range(scalar_at(sig, 32))) return false;
  Owned<EVP_PKEY> key = load_public_key(pub);
  if (!key) return false;

  // OpenSSL verifies DER, so re-encode (r, s). No S check: high-S is accepted.
  Bytes der = der_from_sig(sig_from_raw(sig).get());
  Owned<EVP_PKEY_CTX> ctx(EVP_PKEY_CTX_new_from_pkey(nullptr, key.get(), nullptr));
  if (!ctx || EVP_PKEY_verify_init(ctx.get()) != 1) return false;
  // No signature digest is set on ctx, so `digest` is used as the already
  // hashed message (prehashed ECDSA, spec §7.1).
  return EVP_PKEY_verify(ctx.get(), der.data(), der.size(), digest.data(), digest.size()) == 1;
}

Bytes der_to_raw(const Bytes& der) {
  ClearErrorsOnExit clear;
  const unsigned char* p = der.data();
  Owned<ECDSA_SIG> sig(d2i_ECDSA_SIG(nullptr, &p, static_cast<long>(der.size())));
  if (!sig || p != der.data() + der.size()) throw CryptoError("invalid DER signature");
  // Strict DER: re-encoding must reproduce the input exactly (rejects
  // non-minimal lengths and integers that BER would tolerate).
  if (der_from_sig(sig.get()) != der) throw CryptoError("signature is not strict DER");

  const BIGNUM* r = nullptr;
  const BIGNUM* s = nullptr;
  ECDSA_SIG_get0(sig.get(), &r, &s);
  if (BN_is_negative(r) || BN_is_negative(s) || BN_num_bytes(r) > 32 || BN_num_bytes(s) > 32) {
    throw CryptoError("signature scalar out of range");
  }
  Bytes raw(kSigLen);
  BN_bn2binpad(r, raw.data(), 32);
  BN_bn2binpad(s, raw.data() + 32, 32);
  if (!in_scalar_range(scalar_at(raw, 0)) || !in_scalar_range(scalar_at(raw, 32))) {
    throw CryptoError("signature scalar out of range");
  }
  return raw;
}

Bytes raw_to_der(const Bytes& raw) {
  if (raw.size() != kSigLen) throw CryptoError("raw signature must be 64 bytes");
  return der_from_sig(sig_from_raw(raw).get());
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
