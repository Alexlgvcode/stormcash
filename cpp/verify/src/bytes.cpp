#include "stormcash/bytes.hpp"

#include <array>

namespace stormcash {
namespace {

constexpr std::string_view kHexDigits = "0123456789abcdef";
constexpr std::string_view kB64uAlphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

int hex_value(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;  // uppercase is deliberately not accepted
}

// Reverse lookup for the base64url alphabet; -1 for anything else.
constexpr std::array<int, 256> make_b64u_table() {
  std::array<int, 256> table{};
  for (auto& v : table) v = -1;
  for (std::size_t i = 0; i < kB64uAlphabet.size(); ++i) {
    table[static_cast<unsigned char>(kB64uAlphabet[i])] = static_cast<int>(i);
  }
  return table;
}
constexpr auto kB64uTable = make_b64u_table();

}  // namespace

std::string to_hex(const Bytes& data) {
  std::string out;
  out.reserve(data.size() * 2);
  for (std::uint8_t b : data) {
    out.push_back(kHexDigits[b >> 4]);
    out.push_back(kHexDigits[b & 0x0f]);
  }
  return out;
}

Bytes from_hex(std::string_view text) {
  if (text.size() % 2 != 0) {
    throw EncodingError("hex has an odd number of digits: '" + std::string(text) + "'");
  }
  Bytes out;
  out.reserve(text.size() / 2);
  for (std::size_t i = 0; i < text.size(); i += 2) {
    int hi = hex_value(text[i]);
    int lo = hex_value(text[i + 1]);
    if (hi < 0 || lo < 0) {
      throw EncodingError("lowercase hex expected, got '" + std::string(text) + "'");
    }
    out.push_back(static_cast<std::uint8_t>((hi << 4) | lo));
  }
  return out;
}

std::string b64u_encode(const Bytes& data) {
  std::string out;
  out.reserve((data.size() * 4 + 2) / 3);
  std::size_t i = 0;
  // Whole 3-byte groups become 4 characters.
  for (; i + 3 <= data.size(); i += 3) {
    std::uint32_t n = (std::uint32_t{data[i]} << 16) | (std::uint32_t{data[i + 1]} << 8) | data[i + 2];
    out.push_back(kB64uAlphabet[(n >> 18) & 63]);
    out.push_back(kB64uAlphabet[(n >> 12) & 63]);
    out.push_back(kB64uAlphabet[(n >> 6) & 63]);
    out.push_back(kB64uAlphabet[n & 63]);
  }
  // A 1- or 2-byte tail becomes 2 or 3 characters, with no '=' padding.
  std::size_t rest = data.size() - i;
  if (rest == 1) {
    std::uint32_t n = std::uint32_t{data[i]} << 16;
    out.push_back(kB64uAlphabet[(n >> 18) & 63]);
    out.push_back(kB64uAlphabet[(n >> 12) & 63]);
  } else if (rest == 2) {
    std::uint32_t n = (std::uint32_t{data[i]} << 16) | (std::uint32_t{data[i + 1]} << 8);
    out.push_back(kB64uAlphabet[(n >> 18) & 63]);
    out.push_back(kB64uAlphabet[(n >> 12) & 63]);
    out.push_back(kB64uAlphabet[(n >> 6) & 63]);
  }
  return out;
}

Bytes b64u_decode(std::string_view text) {
  // A length of 1 mod 4 can't come from any byte string.
  if (text.size() % 4 == 1) {
    throw EncodingError("invalid base64url length: '" + std::string(text) + "'");
  }
  Bytes out;
  out.reserve(text.size() * 3 / 4);
  std::uint32_t acc = 0;
  int bits = 0;
  for (char c : text) {
    int v = kB64uTable[static_cast<unsigned char>(c)];
    if (v < 0) {
      // Covers '=', '+', '/', whitespace and anything non-ASCII.
      throw EncodingError("invalid base64url character in '" + std::string(text) + "'");
    }
    acc = (acc << 6) | static_cast<std::uint32_t>(v);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push_back(static_cast<std::uint8_t>((acc >> bits) & 0xff));
    }
  }
  // Same rule as the Python codec: decoding must round-trip, which rejects a
  // last character whose unused low bits aren't zero ("AB" vs "AA").
  if (b64u_encode(out) != text) {
    throw EncodingError("non-canonical base64url: '" + std::string(text) + "'");
  }
  return out;
}

Bytes prefix(const Bytes& data, std::size_t n) {
  if (data.size() < n) throw EncodingError("byte string shorter than its prefix");
  return Bytes(data.begin(), data.begin() + static_cast<std::ptrdiff_t>(n));
}

}  // namespace stormcash
