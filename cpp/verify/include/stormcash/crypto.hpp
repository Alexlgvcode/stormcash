// SHA-256 and ECDSA P-256 verification (spec §7.1). The math comes from one of
// two backends chosen at configure time: OpenSSL 3 (the native default) or a
// portable one (p256-m and a built-in SHA-256) that also builds to
// WebAssembly. Both pass the same tests and vectors (src/crypto_backend.hpp).
//
// - Signatures are raw 64 bytes r || s, big-endian, 32 bytes each.
// - The signed message is the 32-byte SHA-256 digest of the canonical string
//   (prehashed): the digest is verified as-is, never hashed again.
// - Verifiers accept low-S and high-S (signers normalize to low-S; the Secure
//   Enclave doesn't, and a verifier must not reject its signatures).
// - Public keys are SEC1 compressed, 33 bytes.
//
// This side only verifies. There is no signing code in this toolkit.
#pragma once

#include <cstddef>
#include <stdexcept>

#include "stormcash/bytes.hpp"

namespace stormcash {

inline constexpr std::size_t kPubLen = 33;
inline constexpr std::size_t kSigLen = 64;
inline constexpr std::size_t kDigestLen = 32;

class CryptoError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

// Which backend this build uses, e.g. "OpenSSL 3".
const char* crypto_backend();

Bytes sha256(const Bytes& data);

// True iff `pub` is 33 bytes, starts with 0x02 or 0x03, and decompresses to a
// point on P-256.
bool is_valid_public_key(const Bytes& pub);

// True iff `sig` (raw r || s, low-S or high-S) is a valid ECDSA P-256
// signature of the 32-byte `digest` under `pub`. Any malformed input (wrong
// lengths, r or s outside [1, n-1], a key that isn't on the curve) is simply
// "not valid", never an exception.
bool verify_digest(const Bytes& pub, const Bytes& digest, const Bytes& sig);

// DER (as Python `cryptography` and the Secure Enclave emit it) to raw r || s.
// Strict DER only, nothing trailing, 0 < r, s < n. Does not normalize S.
// Throws CryptoError.
Bytes der_to_raw(const Bytes& der);

// Raw r || s to DER.
Bytes raw_to_der(const Bytes& raw);

// s ≤ n/2.
bool is_low_s(const Bytes& raw);

// (r, s) -> (r, n − s) when s > n/2; otherwise unchanged.
Bytes normalize_low_s(const Bytes& raw);

}  // namespace stormcash
