// Offline verdict on a case proof, the JSON from GET /v1/proof/{case_id}
// (server/stormcash/routes/cases.py: get_proof):
//
//   {case_id, rule, server_pub, cert, tag_a, tag_b, holder_pub, log_entries}
//
// where cert, tag_a, tag_b and each log entry are {type, json, fields,
// canonical, digest}. Nothing in the file is trusted: every object is decoded
// from its transport `json` with the strict codec, its canonical string is
// rebuilt here (and must equal the `fields`, `canonical` and `digest` the
// server displays), every signature is checked, and the rule is re-derived
// from the signed fields. The same checks the public proof page runs in a
// browser (spec §18.6), with no network access at all.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "stormcash/objects.hpp"

namespace stormcash {

enum class ProofStatus {
  Proven,      // every check passed and the file proves the whole claim
  Incomplete,  // every check passed, but part of the claim isn't in the file
  Invalid,     // a check failed
};

struct ProofLine {
  bool ok;
  std::string text;
};

struct ProofVerdict {
  std::int64_t case_id = 0;
  std::string rule;
  ProofStatus status = ProofStatus::Invalid;
  std::vector<ProofLine> lines;    // each check, in order
  std::vector<std::string> notes;  // what the file can't show
  std::string verdict;             // one-sentence summary
};

// How the caller pins the server key, in the verdict's words. The defaults are
// the CLI's; the WebAssembly build on the proof page says where its key came
// from instead.
struct KeyWording {
  std::string pinned = "pinned with --server-pub";
  std::string how_to_pin = "pass --server-pub to pin StormCash's key";
};

// `pinned_server_pub` is StormCash's server key as the caller knows it. Without
// it the key printed in the file is used, and the verdict says so.
// Throws EncodingError for a file that isn't a /v1/proof document.
ProofVerdict check_proof(const Json& doc, const std::optional<Bytes>& pinned_server_pub,
                         const KeyWording& wording = {});

std::string format_proof(const ProofVerdict& verdict);

// A server key given as 66 hex digits or as base64url (33 bytes either way).
Bytes parse_public_key_arg(const std::string& text);

}  // namespace stormcash
