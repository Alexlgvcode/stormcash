// Runs spec/vectors.json (spec §20) against this library.
//
// For every vector it reproduces each canonical string and digest byte for
// byte, checks the transport JSON key for key, verifies every valid signature,
// rejects every invalid one, and compares every rule outcome. Nothing is
// skipped silently: a section, vector key or constant this runner doesn't
// know is reported, and counts as a skip.
#pragma once

#include <string>
#include <vector>

#include "stormcash/objects.hpp"

namespace stormcash {

inline constexpr std::string_view kVectorsFormat = "stormcash-vectors/1";

struct SectionResult {
  std::string name;
  int vectors = 0;                    // entries in the section
  int passed = 0;                     // every check matched
  int failed = 0;                     // at least one check differed (or threw)
  int skipped = 0;                    // no checker for this section
  int checks = 0;                     // individual comparisons made
  std::vector<std::string> failures;  // "<vector>: <what differed>"
  std::vector<std::string> notes;     // vector keys that weren't checked
};

struct VectorReport {
  std::string path;
  std::string format;
  std::vector<std::string> preamble;  // constants and keys checked, one line each
  std::vector<std::string> problems;  // file-level mismatches (format, constants)
  std::vector<std::string> unknown;   // file-level things not checked (unknown sections, constants)
  std::vector<SectionResult> sections;

  int vectors() const;
  int passed() const;
  int failed() const;
  int skipped() const;
  int checks() const;
  // Mismatches anywhere. Strict mode also fails on anything not checked.
  bool ok(bool strict) const;
};

VectorReport run_vectors(const Json& root);

// The table printed by `stormcash-verify vectors`.
std::string format_report(const VectorReport& report);

}  // namespace stormcash
