// stormcash-verify in the browser: the proof check (proof_check.hpp) behind
// one C function, built to WebAssembly with Emscripten (build.sh). The public
// proof page (dashboard/src/cppverify.ts) calls it with the JSON it fetched
// from GET /v1/proof/{case_id}, as a second check next to WebCrypto.
//
// The result is a JSON verdict, the same one `stormcash-verify proof` prints:
//
//   {"status": "proven" | "incomplete" | "invalid" | "error",
//    "case_id", "rule", "lines": [{"ok", "text"}], "notes": [...],
//    "verdict": one sentence, "report": the CLI's text output,
//    "crypto": the crypto backend, "error": only with status "error"}
//
// "error" means the input couldn't be checked at all (not JSON, not a /v1/proof
// document, a malformed key), never that a signature failed: that is "invalid".
#include <emscripten/emscripten.h>

#include <cstdlib>
#include <cstring>
#include <exception>
#include <optional>
#include <string>

#include "stormcash/crypto.hpp"
#include "stormcash/proof_check.hpp"

namespace {

const char* status_name(stormcash::ProofStatus status) {
  switch (status) {
    case stormcash::ProofStatus::Proven:
      return "proven";
    case stormcash::ProofStatus::Incomplete:
      return "incomplete";
    case stormcash::ProofStatus::Invalid:
      return "invalid";
  }
  return "invalid";
}

std::string verify(const char* proof_json, const char* server_pub) {
  stormcash::Json out = {{"crypto", stormcash::crypto_backend()}};
  try {
    std::optional<stormcash::Bytes> pinned;
    if (server_pub != nullptr && *server_pub != '\0') pinned = stormcash::parse_public_key_arg(server_pub);
    stormcash::KeyWording wording{"built into this page",
                                  "a page built with VITE_SERVER_PUB pins StormCash's key"};
    auto verdict = stormcash::check_proof(stormcash::Json::parse(proof_json), pinned, wording);
    stormcash::Json lines = stormcash::Json::array();
    for (const auto& line : verdict.lines) lines.push_back({{"ok", line.ok}, {"text", line.text}});
    out["status"] = status_name(verdict.status);
    out["case_id"] = verdict.case_id;
    out["rule"] = verdict.rule;
    out["lines"] = lines;
    out["notes"] = verdict.notes;
    out["verdict"] = verdict.verdict;
    out["report"] = stormcash::format_proof(verdict);
  } catch (const std::exception& e) {
    out["status"] = "error";
    out["error"] = e.what();
  }
  // Text from the input can be invalid UTF-8; replace it rather than throw.
  return out.dump(-1, ' ', false, stormcash::Json::error_handler_t::replace);
}

}  // namespace

extern "C" {

// `proof_json`: the body of GET /v1/proof/{case_id}. `server_pub`: StormCash's
// server key (66 hex digits or base64url) to pin, or "" to use the one in the
// file. Returns a NUL-terminated JSON verdict that the caller frees with
// stormcash_free().
EMSCRIPTEN_KEEPALIVE char* stormcash_verify_proof(const char* proof_json, const char* server_pub) {
  std::string result = verify(proof_json, server_pub);
  char* out = static_cast<char*>(std::malloc(result.size() + 1));
  if (out != nullptr) std::memcpy(out, result.c_str(), result.size() + 1);
  return out;
}

EMSCRIPTEN_KEEPALIVE void stormcash_free(char* p) { std::free(p); }

}  // extern "C"
