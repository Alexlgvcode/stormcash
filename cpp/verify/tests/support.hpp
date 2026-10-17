// Shared helpers for the unit tests: the vectors file, read once.
#pragma once

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

#include "stormcash/objects.hpp"

namespace stormcash::test {

inline std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("can't read " + path);
  std::ostringstream buf;
  buf << in.rdbuf();
  return buf.str();
}

inline const Json& vectors() {
  static const Json root = Json::parse(read_file(STORMCASH_VECTORS_PATH));
  return root;
}

// The entry called `name` in a section of spec/vectors.json. Returned by value:
// returning a reference trips GCC 13's -Wdangling-reference heuristic at every
// call with string literal arguments, and the copies are small.
inline Json vector(const std::string& section, const std::string& name) {
  for (const Json& v : vectors().at(section)) {
    if (v.at("name") == name) return v;
  }
  throw std::runtime_error("no vector " + section + "/" + name);
}

// A JSON string value (the vectors keep bytes as hex strings).
inline std::string str(const Json& j) { return j.get<std::string>(); }

inline Bytes hex(const Json& j) { return from_hex(str(j)); }

inline Bytes vector_pub(const std::string& who) { return hex(vectors().at("keys").at(who).at("pub")); }

}  // namespace stormcash::test
