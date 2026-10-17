#include "stormcash/vectors.hpp"

#include <functional>
#include <iomanip>
#include <set>
#include <sstream>

#include "stormcash/crypto.hpp"
#include "stormcash/encoding.hpp"
#include "stormcash/rules.hpp"

namespace stormcash {
namespace {

// Records the checks made on one vector. A failed check doesn't stop the
// vector: every difference is reported.
class Expect {
 public:
  explicit Expect(std::string vector_name) : name_(std::move(vector_name)) {}

  void equal(const std::string& what, const std::string& got, const std::string& want) {
    ++checks_;
    if (got != want) failures_.push_back(name_ + ": " + what + ": got " + got + ", want " + want);
  }
  void equal(const std::string& what, const Bytes& got, const std::string& want_hex) {
    equal(what, to_hex(got), want_hex);
  }
  // JSON is compared as a value (key order ignored), the same equality the
  // Python and TypeScript vector tests use.
  void equal(const std::string& what, const Json& got, const Json& want) {
    ++checks_;
    if (nlohmann::json::parse(got.dump()) != nlohmann::json::parse(want.dump())) {
      failures_.push_back(name_ + ": " + what + ": got " + got.dump() + ", want " + want.dump());
    }
  }
  void equal(const std::string& what, bool got, bool want) {
    equal(what, std::string(got ? "true" : "false"), std::string(want ? "true" : "false"));
  }
  void that(const std::string& what, bool ok) {
    ++checks_;
    if (!ok) failures_.push_back(name_ + ": " + what);
  }
  // A check that must throw EncodingError (a value with no canonical form).
  void rejects(const std::string& what, const std::function<void()>& fn) {
    ++checks_;
    try {
      fn();
      failures_.push_back(name_ + ": " + what + ": accepted, want EncodingError");
    } catch (const EncodingError&) {
    }
  }
  void unexpected(const std::string& message) { failures_.push_back(name_ + ": threw: " + message); }

  int checks() const { return checks_; }
  const std::vector<std::string>& failures() const { return failures_; }

 private:
  std::string name_;
  int checks_ = 0;
  std::vector<std::string> failures_;
};

// Helpers to read vector JSON --------------------------------------------------------

Bytes hex(const Json& j) { return from_hex(j.get<std::string>()); }

// A JSON value that is null or a string, shown the same way for got and want.
std::string nullable(const Json& j) { return j.is_null() ? "null" : j.get<std::string>(); }
std::string nullable(const std::optional<std::string>& s) { return s ? *s : "null"; }

Tag tag_of(const Json& j) { return Tag(Object::from_vector(j)); }
Dlog dlog_of(const Json& j) { return Dlog(Object::from_vector(j)); }

std::vector<Tag> tags_of(const Json& list) {
  std::vector<Tag> out;
  for (const Json& j : list) out.push_back(tag_of(j));
  return out;
}

std::vector<Dlog> dlogs_of(const Json& list) {
  std::vector<Dlog> out;
  for (const Json& j : list) out.push_back(dlog_of(j));
  return out;
}

Json rule_names(const std::vector<Rule>& rules) {
  Json out = Json::array();
  for (Rule r : rules) out.push_back(std::string(rule_name(r)));
  return out;
}

std::optional<std::string> rule_or_null(std::optional<Rule> rule) {
  if (!rule) return std::nullopt;
  return std::string(rule_name(*rule));
}

// Section checkers. Each mirrors server/tests/test_vectors.py for its section.

void check_encoding(const Json& v, Expect& e) {
  const std::string kind = v.at("kind").get<std::string>();
  const Json& value = v.at("value");
  std::size_t size = v.contains("size") ? v.at("size").get<std::size_t>() : 0;
  std::vector<std::string> allowed_storage;
  std::vector<std::string_view> allowed;
  if (v.contains("allowed")) {
    allowed_storage = v.at("allowed").get<std::vector<std::string>>();
    allowed.assign(allowed_storage.begin(), allowed_storage.end());
  }

  std::function<std::string()> render;
  if (kind == "int") {
    render = [&] {
      // Out-of-range JSON numbers must be rejected too, not wrapped.
      if (value.is_number_unsigned() && value.get<std::uint64_t>() > static_cast<std::uint64_t>(kMaxInt)) {
        throw EncodingError("integer exceeds 2^53 - 1");
      }
      return render_int(value.get<std::int64_t>());
    };
  } else if (kind == "bytes") {
    render = [&] { return render_bytes(hex(value), size); };
  } else if (kind == "string") {
    render = [&] { return render_string(value.get<std::string>()); };
  } else if (kind == "enum") {
    render = [&] { return render_enum(value.get<std::string>(), allowed); };
  } else if (kind == "bytes_list") {
    render = [&] {
      std::vector<Bytes> list;
      for (const Json& item : value) list.push_back(hex(item));
      return render_bytes_list(list, size);
    };
  } else if (kind == "string_list") {
    render = [&] { return render_string_list(value.get<std::vector<std::string>>()); };
  } else {
    e.that("unknown encoding kind '" + kind + "'", false);
    return;
  }

  if (v.value("error", false)) {
    e.rejects("render " + kind, [&] { render(); });
  } else {
    e.equal("rendered", render(), v.at("rendered").get<std::string>());
  }
}

void check_object(const Json& v, Expect& e) {
  const std::string type = v.at("type").get<std::string>();
  const std::string canonical_text = v.at("canonical").get<std::string>();
  // The digest is SHA-256 of the UTF-8 canonical string, computed independently.
  e.equal("sha256(canonical)", sha256(to_bytes(canonical_text)), v.at("digest").get<std::string>());

  if (type == "GEN") {
    e.equal("GEN canonical", gen_canonical(hex(v.at("fields").at("cert_id"))), canonical_text);
    return;
  }
  if (type == "DGEN") {
    e.equal("DGEN canonical", dgen_canonical(hex(v.at("fields").at("device_pub"))), canonical_text);
    return;
  }

  Object o = Object::from_fields(type, v.at("fields"), v.at("sig"));
  e.equal("canonical", o.canonical(), canonical_text);
  e.equal("digest", o.digest(), v.at("digest").get<std::string>());
  e.equal("fields round trip", o.to_fields(), v.at("fields"));

  // Transport JSON: exact (key order included) and a lossless round trip.
  e.equal("transport json", o.to_json(), v.at("json"));
  e.that("transport json decodes to the same object", Object::from_json(type, v.at("json")) == o);

  bool valid = v.at("valid").get<bool>();
  if (is_signed_type(type)) {
    e.equal("signature valid", o.verify(hex(v.at("pub"))), valid);
    if (valid) e.that("valid signature is low-S", is_low_s(*o.sig()));
  } else {
    e.that("unsigned object has valid=true and no sig", valid && v.at("sig").is_null());
  }

  if (v.contains("item_kind")) {
    Bytes full = item_id(v.at("item_kind").get<std::string>(), o);
    e.equal("item_id", full, v.at("item_id").get<std::string>());
    e.equal("id8", id8(full), v.at("id8").get<std::string>());
  }
}

void check_pay(const Json& v, Expect& e) {
  Pay p = Pay::from_vector(v);
  e.equal("transport json", p.to_json(), v.at("json"));
  e.that("transport json decodes to the same PAY", Pay::from_json(v.at("json")) == p);
  e.equal("item_id", item_id(p), v.at("item_id").get<std::string>());
  e.equal("item_id is the tag_hash", item_id(p), to_hex(p.tag.tag_hash()));
  e.that("PAY and TAG share an item id", item_id("TAG", p.tag.object()) == item_id(p));
  e.equal("id8", id8(item_id(p)), v.at("id8").get<std::string>());
  e.that("details_hash = SHA-256(canonical DET)", p.tag.details_hash() == p.det.digest());
}

void check_signature(const Json& v, Expect& e) {
  Bytes sig = hex(v.at("sig"));
  bool valid = v.at("valid").get<bool>();
  e.equal("verify", verify_digest(hex(v.at("pub")), hex(v.at("digest")), sig), valid);
  if (valid) e.equal("low_s", is_low_s(sig), v.at("low_s").get<bool>());
}

void check_der(const Json& v, Expect& e) {
  Bytes raw = der_to_raw(hex(v.at("der")));
  Bytes pub = hex(v.at("pub"));
  Bytes dig = hex(v.at("digest"));
  e.equal("der -> raw", raw, v.at("raw").get<std::string>());
  e.equal("normalize_low_s(raw)", normalize_low_s(raw), v.at("raw_low_s").get<std::string>());
  e.equal("raw -> der", raw_to_der(raw), v.at("der").get<std::string>());
  e.that("raw verifies", verify_digest(pub, dig, raw));
  e.that("raw_low_s verifies", verify_digest(pub, dig, hex(v.at("raw_low_s"))));
}

void check_contact_id(const Json& v, Expect& e) {
  const Json& a = v.at("a");
  const Json& b = v.at("b");
  Bytes pa = hex(a.at("pub")), na = hex(a.at("nonce")), pb = hex(b.at("pub")), nb = hex(b.at("nonce"));
  std::string want = v.at("contact_id").get<std::string>();
  e.equal("contact_id from a's side", contact_id(pa, na, pb, nb), want);
  e.equal("contact_id from b's side", contact_id(pb, nb, pa, na), want);
  e.equal("canonical", contact_canonical(pa, na, pb, nb), v.at("canonical").get<std::string>());
}

void check_single_tag(const Json& v, Expect& e) {
  e.equal("tag_valid", tag_valid(tag_of(v.at("tag"))), v.at("valid").get<bool>());
}

void check_equivocation(const Json& v, Expect& e) {
  Tag a = tag_of(v.at("a"));
  Tag b = tag_of(v.at("b"));
  e.equal("rules_fired(a, b)", rule_names(rules_fired(a, b)), v.at("rules_fired"));
  e.equal("rules_fired(b, a)", rule_names(rules_fired(b, a)), v.at("rules_fired"));
  e.equal("equivocation", nullable(rule_or_null(equivocation(a, b))), nullable(v.at("rule")));
  auto proof = make_proof(a, b);
  e.equal("make_proof rule", nullable(rule_or_null(proof ? std::optional(proof->rule) : std::nullopt)),
          nullable(v.at("rule")));
}

void check_proof(const Json& v, Expect& e) {
  auto rule = parse_rule(v.at("rule").get<std::string>());
  if (!rule) {
    e.that("known proof rule", false);
    return;
  }
  Proof proof{tag_of(v.at("a")), tag_of(v.at("b")), *rule};
  e.equal("transport json", proof.to_json(), v.at("json"));
  e.that("transport json decodes to the same PROOF", Proof::from_json(v.at("json")) == proof);
  e.equal("verify_proof", verify_proof(proof, hex(v.at("holder_pub"))), v.at("valid").get<bool>());
  e.equal("PRF canonical", proof_canonical(proof.a.tag_hash(), proof.b.tag_hash()),
          v.at("canonical").get<std::string>());
  e.equal("item_id", item_id(proof), v.at("item_id").get<std::string>());
}

void check_merchant(const Json& v, Expect& e) {
  std::optional<Policy> policy;
  if (!v.at("policy").is_null()) policy.emplace(Object::from_vector(v.at("policy")));
  CheckResult r =
      merchant_check(Pay::from_vector(v.at("pay")), hex(v.at("server_pub")),
                     Mcert(Object::from_vector(v.at("merchant"))), Req(Object::from_vector(v.at("req"))),
                     policy ? &*policy : nullptr, tags_of(v.at("stored_tags")), v.at("now").get<std::int64_t>());
  const Json& want = v.at("expect");
  e.equal("ok", r.ok, want.at("ok").get<bool>());
  e.equal("check", r.ok ? "null" : r.check, nullable(want.at("check")));
  e.equal("reason", r.ok ? "null" : r.reason, nullable(want.at("reason")));
  e.equal("rule", nullable(rule_or_null(r.rule)), nullable(want.at("rule")));
  e.equal("conflict", r.conflict ? to_hex(r.conflict->tag_hash()) : "null", nullable(want.at("conflict")));
}

void check_over_cap(const Json& v, Expect& e) {
  auto caps = v.at("caps").get<std::vector<std::int64_t>>();
  std::vector<Tag> settled;
  int step = 0;
  for (const Json& s : v.at("steps")) {
    settled.push_back(tag_of(s.at("tag")));
    e.equal("over_cap after step " + std::to_string(++step), over_cap(settled, caps), s.at("over_cap").get<bool>());
  }
}

void check_log_tamper(const Json& v, Expect& e) {
  std::vector<Dlog> entries = dlogs_of(v.at("entries"));
  for (const Dlog& d : entries)
    e.that("entry seq " + std::to_string(d.seq()) + " signed by its device", d.verify_self());
  auto got = log_tamper(entries);
  Json got_json = got ? Json{{"kind", got->kind}, {"seq", got->seq}} : Json(nullptr);
  e.equal("log_tamper", got_json, v.at("expect"));
}

void check_merchant_knew(const Json& v, Expect& e) {
  std::vector<Dlog> logs = dlogs_of(v.at("logs"));
  for (const Dlog& d : logs) e.that("log entry signed by its device", d.verify_self());
  auto got = merchant_knew(tag_of(v.at("z")), hex(v.at("merchant_pub")), v.at("t_accept").get<std::int64_t>(),
                           tags_of(v.at("cert_tags")), logs);
  const Json& want = v.at("expect");
  e.equal("fired", got.has_value(), want.at("fired").get<bool>());
  e.equal("clause", got ? got->clause : "null", nullable(want.at("clause")));
  e.equal("conflict", got ? to_hex(got->conflict) : "null", nullable(want.at("conflict")));
  e.equal("contact_id", got && got->contact_id ? to_hex(*got->contact_id) : "null", nullable(want.at("contact_id")));
}

struct Section {
  std::string_view name;
  void (*check)(const Json&, Expect&);
  std::set<std::string> keys;  // every key a vector of this section may have; anything else is reported
};

const std::vector<Section>& sections() {
  static const std::vector<Section> all = {
      {"encoding", check_encoding, {"name", "kind", "value", "size", "allowed", "rendered", "error"}},
      {"objects",
       check_object,
       {"name", "type", "fields", "canonical", "digest", "pub", "sig", "valid", "json", "item_kind", "item_id", "id8"}},
      {"pays", check_pay, {"name", "c", "t", "d", "json", "item_id", "id8"}},
      {"signatures", check_signature, {"name", "pub", "digest", "sig", "valid", "low_s"}},
      {"der", check_der, {"name", "pub", "digest", "der", "raw", "raw_low_s"}},
      {"contact_ids", check_contact_id, {"name", "a", "b", "canonical", "contact_id"}},
      {"single_tag", check_single_tag, {"name", "tag", "valid"}},
      {"equivocation", check_equivocation, {"name", "a", "b", "rules_fired", "rule"}},
      {"proofs", check_proof, {"name", "holder_pub", "a", "b", "rule", "json", "canonical", "item_id", "valid"}},
      {"merchant_checks",
       check_merchant,
       {"name", "now", "server_pub", "merchant", "req", "pay", "policy", "stored_tags", "expect"}},
      {"over_cap", check_over_cap, {"name", "caps", "steps"}},
      {"log_tamper", check_log_tamper, {"name", "entries", "expect"}},
      {"merchant_knew", check_merchant_knew, {"name", "merchant_pub", "t_accept", "z", "cert_tags", "logs", "expect"}},
  };
  return all;
}

// Top-level keys that hold metadata rather than vectors.
const std::set<std::string> kMetadataKeys = {"format", "note", "deterministic_signatures", "constants", "keys"};

void check_constants(const Json& constants, VectorReport& report) {
  // The limits this library hard-codes must be the ones the vectors were made with.
  const std::vector<std::pair<std::string, std::int64_t>> expected = {
      {"clock_tolerance_s", kClockToleranceS},
      {"max_string_chars", static_cast<std::int64_t>(kMaxStringChars)},
      {"max_int", kMaxInt},
      {"contact_ids_cap", static_cast<std::int64_t>(kContactIdsCap)},
  };
  int matched = 0;
  for (const auto& [key, mine] : expected) {
    if (!constants.contains(key)) {
      report.problems.push_back("constants." + key + " missing from the file");
    } else if (constants.at(key).get<std::int64_t>() != mine) {
      report.problems.push_back("constants." + key + " is " + constants.at(key).dump() + ", this library uses " +
                                std::to_string(mine));
    } else {
      ++matched;
    }
  }
  std::string unchecked;
  for (const auto& item : constants.items()) {
    if (item.key() == "now") continue;  // each vector that needs a clock carries its own `now`
    bool known = false;
    for (const auto& [key, mine] : expected) known = known || key == item.key();
    if (!known) report.unknown.push_back("constants." + item.key() + " is not checked");
  }
  report.preamble.push_back("constants: " + std::to_string(matched) + "/" + std::to_string(expected.size()) +
                            " limits match this library (clock tolerance, string length, max int, contact ids cap)");
}

void check_keys_section(const Json& keys, VectorReport& report) {
  int valid = 0;
  for (const auto& item : keys.items()) {
    if (is_valid_public_key(from_hex(item.value().at("pub").get<std::string>()))) {
      ++valid;
    } else {
      report.problems.push_back("keys." + item.key() + ".pub is not a valid P-256 key");
    }
  }
  report.preamble.push_back("keys: " + std::to_string(valid) + "/" + std::to_string(keys.size()) +
                            " test public keys are valid compressed P-256 points (private keys unused: this tool only "
                            "verifies)");
}

}  // namespace

int VectorReport::vectors() const {
  int n = 0;
  for (const auto& s : sections) n += s.vectors;
  return n;
}
int VectorReport::passed() const {
  int n = 0;
  for (const auto& s : sections) n += s.passed;
  return n;
}
int VectorReport::failed() const {
  int n = 0;
  for (const auto& s : sections) n += s.failed;
  return n;
}
int VectorReport::skipped() const {
  int n = 0;
  for (const auto& s : sections) n += s.skipped;
  return n;
}
int VectorReport::checks() const {
  int n = 0;
  for (const auto& s : sections) n += s.checks;
  return n;
}

bool VectorReport::ok(bool strict) const {
  if (failed() > 0 || !problems.empty()) return false;
  if (!strict) return true;
  bool notes = false;
  for (const auto& s : sections) notes = notes || !s.notes.empty();
  return skipped() == 0 && unknown.empty() && !notes;
}

VectorReport run_vectors(const Json& root) {
  VectorReport report;
  report.format = root.value("format", "");
  if (report.format != kVectorsFormat) {
    report.problems.push_back("format is '" + report.format + "', this runner reads '" + std::string(kVectorsFormat) +
                              "'");
  }
  if (root.contains("constants")) check_constants(root.at("constants"), report);
  if (root.contains("keys")) check_keys_section(root.at("keys"), report);

  // Every top-level array is a section of vectors; any we don't know is a skip.
  std::set<std::string> known;
  for (const Section& s : sections()) known.emplace(s.name);
  for (const auto& item : root.items()) {
    if (kMetadataKeys.count(item.key()) || known.count(item.key())) continue;
    SectionResult skipped;
    skipped.name = item.key();
    skipped.vectors = item.value().is_array() ? static_cast<int>(item.value().size()) : 0;
    skipped.skipped = skipped.vectors;
    report.unknown.push_back("section '" + item.key() + "' has no checker in this runner");
    report.sections.push_back(std::move(skipped));
  }

  for (const Section& section : sections()) {
    SectionResult result;
    result.name = section.name;
    if (!root.contains(section.name)) {
      report.problems.push_back("section '" + std::string(section.name) + "' is missing from the file");
      report.sections.push_back(std::move(result));
      continue;
    }
    for (const Json& v : root.at(section.name)) {
      ++result.vectors;
      std::string name = v.value("name", "#" + std::to_string(result.vectors));
      for (const auto& item : v.items()) {
        if (!section.keys.count(item.key())) {
          result.notes.push_back(name + ": key '" + item.key() + "' is not checked by this runner");
        }
      }
      Expect e(name);
      try {
        section.check(v, e);
      } catch (const std::exception& ex) {
        e.unexpected(ex.what());
      }
      result.checks += e.checks();
      if (e.failures().empty()) {
        ++result.passed;
      } else {
        ++result.failed;
        result.failures.insert(result.failures.end(), e.failures().begin(), e.failures().end());
      }
    }
    report.sections.push_back(std::move(result));
  }
  return report;
}

std::string format_report(const VectorReport& report) {
  std::ostringstream out;
  out << "spec vectors: " << (report.path.empty() ? "(input)" : report.path) << " (format " << report.format << ")\n";
  out << "  crypto backend: " << crypto_backend() << "\n";
  for (const auto& line : report.preamble) out << "  " << line << "\n";
  out << "\n";
  out << std::left << std::setw(18) << "section" << std::right << std::setw(9) << "vectors" << std::setw(7) << "pass"
      << std::setw(7) << "fail" << std::setw(7) << "skip" << std::setw(9) << "checks" << "\n";
  auto row = [&](const std::string& name, int vectors, int pass, int fail, int skip, int checks) {
    out << std::left << std::setw(18) << name << std::right << std::setw(9) << vectors << std::setw(7) << pass
        << std::setw(7) << fail << std::setw(7) << skip << std::setw(9) << checks << "\n";
  };
  for (const auto& s : report.sections) row(s.name, s.vectors, s.passed, s.failed, s.skipped, s.checks);
  row("total", report.vectors(), report.passed(), report.failed(), report.skipped(), report.checks());

  for (const auto& p : report.problems) out << "\nPROBLEM: " << p;
  for (const auto& u : report.unknown) out << "\nNOT CHECKED: " << u;
  for (const auto& s : report.sections) {
    for (const auto& f : s.failures) out << "\nMISMATCH [" << s.name << "] " << f;
    for (const auto& n : s.notes) out << "\nNOT CHECKED [" << s.name << "] " << n;
  }
  if (!report.problems.empty() || !report.unknown.empty() || report.failed() > 0) out << "\n";
  bool notes = false;
  for (const auto& s : report.sections) notes = notes || !s.notes.empty();
  out << "\n";
  if (report.ok(true)) {
    out << "OK: all " << report.vectors() << " vectors match (" << report.checks()
        << " checks, 0 mismatches, 0 skipped).\n";
  } else if (report.ok(false)) {
    out << "OK with gaps: 0 mismatches, but " << report.skipped() << " vectors skipped"
        << (notes || !report.unknown.empty() ? " and some keys or sections not checked (listed above)" : "") << ".\n";
  } else {
    out << "FAILED: " << report.failed() << " vectors mismatch, " << report.problems.size() << " file problems.\n";
  }
  return out.str();
}

}  // namespace stormcash
