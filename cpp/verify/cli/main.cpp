// stormcash-verify: an independent C++ verifier for the StormCash protocol.
//
//   stormcash-verify vectors <path> [--strict]
//   stormcash-verify proof <file|-> [--server-pub <hex|base64url>]
//
// Exit codes: 0 verified; 1 a mismatch or a failed check; 2 bad usage or
// unreadable input; 3 (proof) every check passed but the file can't prove the
// whole claim.
#include <fstream>
#include <iostream>
#include <iterator>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#include "stormcash/proof_check.hpp"
#include "stormcash/vectors.hpp"

namespace {

constexpr const char* kUsage = R"(stormcash-verify: independent C++ verifier for the StormCash protocol (spec §7-§10)

usage:
  stormcash-verify vectors <path/to/spec/vectors.json> [--strict]
      Run the shared test vectors: canonical strings, digests, transport JSON,
      signatures and every rule outcome. --strict also fails if anything in
      the file has no checker (sections, keys, constants).

  stormcash-verify proof <file|-> [--server-pub <hex|base64url>]
      Verify the JSON from GET /v1/proof/{case_id} offline. --server-pub pins
      the StormCash server key; without it the key printed in the file is used.

exit codes: 0 verified, 1 mismatch or failed check, 2 bad usage or input,
            3 proof checks passed but the file can't prove the whole claim
)";

std::string read_input(const std::string& path) {
  if (path == "-") {
    return std::string(std::istreambuf_iterator<char>(std::cin), std::istreambuf_iterator<char>());
  }
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("can't read " + path);
  std::ostringstream buf;
  buf << in.rdbuf();
  return buf.str();
}

int run_vectors(const std::vector<std::string>& args) {
  std::string path;
  bool strict = false;
  for (const auto& a : args) {
    if (a == "--strict") {
      strict = true;
    } else if (path.empty() && a.rfind("--", 0) != 0) {
      path = a;
    } else {
      std::cerr << kUsage;
      return 2;
    }
  }
  if (path.empty()) {
    std::cerr << kUsage;
    return 2;
  }
  auto report = stormcash::run_vectors(stormcash::Json::parse(read_input(path)));
  report.path = path;
  std::cout << stormcash::format_report(report);
  return report.ok(strict) ? 0 : 1;
}

int run_proof(const std::vector<std::string>& args) {
  std::string path;
  std::optional<stormcash::Bytes> server_pub;
  for (std::size_t i = 0; i < args.size(); ++i) {
    if (args[i] == "--server-pub" && i + 1 < args.size()) {
      server_pub = stormcash::parse_public_key_arg(args[++i]);
    } else if (path.empty() && (args[i] == "-" || args[i].rfind("--", 0) != 0)) {
      path = args[i];
    } else {
      std::cerr << kUsage;
      return 2;
    }
  }
  if (path.empty()) {
    std::cerr << kUsage;
    return 2;
  }
  auto verdict = stormcash::check_proof(stormcash::Json::parse(read_input(path)), server_pub);
  std::cout << stormcash::format_proof(verdict);
  switch (verdict.status) {
    case stormcash::ProofStatus::Proven:
      return 0;
    case stormcash::ProofStatus::Incomplete:
      return 3;
    case stormcash::ProofStatus::Invalid:
      return 1;
  }
  return 1;
}

}  // namespace

int main(int argc, char** argv) {
  std::vector<std::string> args(argv + 1, argv + argc);
  if (args.empty() || args[0] == "-h" || args[0] == "--help" || args[0] == "help") {
    std::cout << kUsage;
    return args.empty() ? 2 : 0;
  }
  std::string command = args[0];
  args.erase(args.begin());
  try {
    if (command == "vectors") return run_vectors(args);
    if (command == "proof") return run_proof(args);
  } catch (const std::exception& e) {
    std::cerr << "stormcash-verify " << command << ": " << e.what() << "\n";
    return 2;
  }
  std::cerr << kUsage;
  return 2;
}
