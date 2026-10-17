#include "stormcash/encoding.hpp"

#include <utf8proc.h>

#include <algorithm>
#include <stdexcept>
#include <vector>

#include "stormcash/crypto.hpp"

namespace stormcash {
namespace {

// Unicode NFC, the way utf8proc_NFC() does it (decompose with STABLE |
// COMPOSE, then reencode, which composes), with two differences:
// - an explicit length, so an embedded NUL can't silently truncate the string;
// - a buffer sized here. utf8proc_map() sizes its buffer with a first pass
//   over a NULL pointer, which is pointer arithmetic on NULL (undefined
//   behaviour that UBSan reports). A canonical decomposition is at most 4 code
//   points per code point and a code point is at least one byte, so 4 code
//   points per input byte, plus one for the NUL reencode writes, always fits.
std::string nfc(std::string_view value) {
  const auto options = static_cast<utf8proc_option_t>(UTF8PROC_STABLE | UTF8PROC_COMPOSE);
  std::vector<utf8proc_int32_t> buffer(4 * value.size() + 1);
  utf8proc_ssize_t n = utf8proc_decompose(reinterpret_cast<const utf8proc_uint8_t*>(value.data()),
                                          static_cast<utf8proc_ssize_t>(value.size()), buffer.data(),
                                          static_cast<utf8proc_ssize_t>(buffer.size()), options);
  if (n < 0) throw EncodingError(std::string("string is not valid UTF-8: ") + utf8proc_errmsg(n));
  if (static_cast<std::size_t>(n) >= buffer.size()) throw std::logic_error("NFC buffer bound broken");
  // Composes, then writes UTF-8 (and a NUL) over the same buffer.
  utf8proc_ssize_t bytes = utf8proc_reencode(buffer.data(), n, options);
  if (bytes < 0) throw EncodingError(std::string("string can't be normalized: ") + utf8proc_errmsg(bytes));
  return std::string(reinterpret_cast<const char*>(buffer.data()), static_cast<std::size_t>(bytes));
}

bool is_token(std::string_view s) {
  if (s.empty() || s[0] < 'A' || s[0] > 'Z') return false;
  return std::all_of(s.begin() + 1, s.end(),
                     [](char c) { return (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_'; });
}

}  // namespace

std::size_t count_code_points(std::string_view utf8) {
  // Every code point has exactly one byte that isn't a continuation byte (10xxxxxx).
  return static_cast<std::size_t>(
      std::count_if(utf8.begin(), utf8.end(), [](char c) { return (static_cast<unsigned char>(c) & 0xC0) != 0x80; }));
}

std::string render_int(std::int64_t value) {
  if (value < 0) throw EncodingError("negative integers are invalid");
  if (value > kMaxInt) throw EncodingError("integer exceeds 2^53 - 1");
  return std::to_string(value);
}

std::string render_bytes(const Bytes& value, std::size_t size) {
  if (size != 0 && value.size() != size) {
    throw EncodingError("expected " + std::to_string(size) + " bytes, got " + std::to_string(value.size()));
  }
  return to_hex(value);
}

std::string normalize_string(std::string_view value) {
  std::string normalized = nfc(value);
  for (char forbidden : {'|', ',', '\n'}) {
    if (normalized.find(forbidden) != std::string::npos) {
      throw EncodingError("string contains a forbidden character ('|', ',' or newline)");
    }
  }
  if (count_code_points(normalized) > kMaxStringChars) {
    throw EncodingError("string longer than 48 code points after NFC");
  }
  return normalized;
}

std::string render_enum(std::string_view value, std::span<const std::string_view> allowed) {
  if (!is_token(value)) throw EncodingError("invalid enum token '" + std::string(value) + "'");
  if (!allowed.empty() && std::find(allowed.begin(), allowed.end(), value) == allowed.end()) {
    throw EncodingError("enum token '" + std::string(value) + "' not allowed here");
  }
  return std::string(value);
}

std::string render_bytes_list(const std::vector<Bytes>& values, std::size_t size) {
  std::vector<std::string> rendered;
  rendered.reserve(values.size());
  for (const Bytes& v : values) rendered.push_back(render_bytes(v, size));
  // Lowercase hex of equal-length values sorts in the same order as the bytes.
  std::sort(rendered.begin(), rendered.end());
  std::string out;
  for (std::size_t i = 0; i < rendered.size(); ++i) {
    if (i) out.push_back(',');
    out += rendered[i];
  }
  return out;
}

std::string render_string_list(const std::vector<std::string>& values) {
  std::vector<std::string> rendered;
  rendered.reserve(values.size());
  for (const std::string& v : values) rendered.push_back(render_string(v));
  // Sort by UTF-8 bytes, compared as unsigned (= code point order). Spelled out
  // rather than relying on std::string's char_traits.
  std::sort(rendered.begin(), rendered.end(), [](const std::string& a, const std::string& b) {
    return std::lexicographical_compare(a.begin(), a.end(), b.begin(), b.end(), [](char x, char y) {
      return static_cast<unsigned char>(x) < static_cast<unsigned char>(y);
    });
  });
  std::string out;
  for (std::size_t i = 0; i < rendered.size(); ++i) {
    if (i) out.push_back(',');
    out += rendered[i];
  }
  return out;
}

std::string canonical(std::string_view type, const std::vector<std::string>& fields) {
  render_enum(type);
  std::string out(kCanonicalPrefix);
  out.push_back('|');
  out += type;
  for (const std::string& f : fields) {
    out.push_back('|');
    out += f;
  }
  return out;
}

Bytes digest(std::string_view canonical_string) { return sha256(to_bytes(canonical_string)); }

}  // namespace stormcash
