// Byte strings, hex and base64url (spec §7.2, §7.3).
//
// The protocol renders bytes as lowercase hex inside canonical strings and in
// spec/vectors.json, and as base64url without padding in transport JSON. Both
// decoders here are strict: they accept exactly one spelling of each value.
#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace stormcash {

using Bytes = std::vector<std::uint8_t>;

// A value the protocol has no canonical form for: a negative integer, a
// string with a forbidden character, padded base64url, a missing JSON key...
class EncodingError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

// Lowercase hex.
std::string to_hex(const Bytes& data);

// Lowercase hex only, even length. Uppercase is rejected because the protocol
// never produces it, so accepting it would give one value two spellings.
Bytes from_hex(std::string_view text);

// base64url without padding (RFC 4648 §5).
std::string b64u_encode(const Bytes& data);

// Strict base64url: only [A-Za-z0-9_-], no '=' padding, and the canonical
// spelling only (the unused low bits of the last character must be zero), so
// every byte string has exactly one accepted encoding.
Bytes b64u_decode(std::string_view text);

// The bytes of a string (canonical strings are hashed as UTF-8 bytes).
inline Bytes to_bytes(std::string_view text) { return Bytes(text.begin(), text.end()); }

// First n bytes (id8 and device short ids).
Bytes prefix(const Bytes& data, std::size_t n);

}  // namespace stormcash
