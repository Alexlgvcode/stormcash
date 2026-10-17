// Canonical encoding (spec §7.2): the exact string that gets hashed and signed.
//
//   canonical(TYPE, f1, ..., fn) = "SC1|" + TYPE + "|" + f1 + "|" + ... + "|" + fn
//   digest = SHA-256(UTF-8(canonical))
//
// Every renderer throws EncodingError on a value the spec does not allow, so
// an invalid field can never be verified as if it were valid. This mirrors
// server/stormcash/protocol/encoding.py rule for rule.
#pragma once

#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "stormcash/bytes.hpp"

namespace stormcash {

inline constexpr std::string_view kCanonicalPrefix = "SC1";
inline constexpr std::size_t kMaxStringChars = 48;  // Unicode code points, after NFC
// Largest integer JavaScript represents exactly (Number.MAX_SAFE_INTEGER).
inline constexpr std::int64_t kMaxInt = (std::int64_t{1} << 53) - 1;

// integer: base-10 ASCII, no sign, no leading zeros; 0 ≤ value ≤ 2^53 − 1.
std::string render_int(std::int64_t value);

// bytes: lowercase hex. `size` is the required length in bytes (0 = any).
std::string render_bytes(const Bytes& value, std::size_t size = 0);

// NFC-normalize a string field and check it: no '|', ',' or '\n', at most 48
// code points after NFC. Invalid UTF-8 is rejected.
std::string normalize_string(std::string_view value);
inline std::string render_string(std::string_view value) { return normalize_string(value); }

// enum: an uppercase token matching [A-Z][A-Z0-9_]*, and one of `allowed`
// when that list is non-empty.
std::string render_enum(std::string_view value, std::span<const std::string_view> allowed = {});

// list of bytes: each rendered as hex, sorted ascending, joined with ','.
std::string render_bytes_list(const std::vector<Bytes>& values, std::size_t size = 0);

// list of strings: each rendered as a string, sorted by UTF-8 bytes (not by
// UTF-16 code units), joined with ','.
std::string render_string_list(const std::vector<std::string>& values);

// "SC1|TYPE|f1|...|fn". TYPE must itself be a valid enum token.
std::string canonical(std::string_view type, const std::vector<std::string>& fields);

// SHA-256 of the canonical string's UTF-8 bytes.
Bytes digest(std::string_view canonical_string);

// Number of Unicode code points in a valid UTF-8 string.
std::size_t count_code_points(std::string_view utf8);

}  // namespace stormcash
