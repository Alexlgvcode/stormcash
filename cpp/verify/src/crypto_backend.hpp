// The math behind crypto.hpp, from one of two backends chosen when the library
// is configured (STORMCASH_CRYPTO, see cpp/README.md):
//
//   openssl   crypto_openssl.cpp   OpenSSL 3; the native default
//   portable  crypto_portable.cpp  p256-m and a SHA-256 written here; no
//                                  system library, so it also builds to
//                                  WebAssembly
//
// crypto.cpp holds what the two share: it checks lengths, the 0x02/0x03 prefix
// and 0 < r, s < n before calling in here, and does the low-S arithmetic
// itself, so a backend only has to get the curve and the hash right. Both run
// the same tests and the same vectors.
#pragma once

#include "stormcash/bytes.hpp"

namespace stormcash::backend {

// Shown by `stormcash-verify` and in the WebAssembly verdict.
extern const char* const kName;

Bytes sha256(const Bytes& data);

// `pub` is 33 bytes starting with 0x02 or 0x03. True iff x < p and it
// decompresses to a point on P-256.
bool public_key_on_curve(const Bytes& pub);

// `pub` as above, a 32-byte `digest` (verified as-is, never hashed again) and
// a 64-byte raw r || s with 0 < r, s < n, high-S allowed. False for a key that
// isn't on the curve.
bool verify_prehashed(const Bytes& pub, const Bytes& digest, const Bytes& sig);

// Strict DER ECDSA-Sig-Value to 64 bytes r || s, each left-padded to 32 bytes.
// Throws CryptoError for anything that isn't strict DER, has trailing bytes,
// or holds a negative or longer-than-32-byte integer. The caller checks the
// range against n.
Bytes der_to_raw(const Bytes& der);

// 64 bytes r || s to DER (minimal integers).
Bytes raw_to_der(const Bytes& raw);

}  // namespace stormcash::backend
