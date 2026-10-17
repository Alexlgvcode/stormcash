#include "stormcash/proof_check.hpp"

#include <algorithm>
#include <cctype>
#include <set>
#include <sstream>

#include "stormcash/crypto.hpp"
#include "stormcash/rules.hpp"

namespace stormcash {
namespace {

// Keys of the /v1/proof document (server/stormcash/routes/cases.py: get_proof).
const std::vector<std::string> kProofKeys = {"case_id", "rule",  "server_pub", "cert",
                                             "tag_a",   "tag_b", "holder_pub", "log_entries"};
// Keys of each displayed object (routes/cases.py: _signed).
const std::set<std::string> kDisplayedKeys = {"type", "json", "fields", "canonical", "digest"};

std::string short_hex(const Bytes& b) {
  std::string h = to_hex(b);
  return h.size() > 16 ? h.substr(0, 16) + "..." : h;
}

std::string dollars(std::int64_t cents) {
  std::ostringstream out;
  out << "$" << cents / 100 << "." << (cents % 100 < 10 ? "0" : "") << cents % 100;
  return out.str();
}

std::string tag_summary(const Tag& t) {
  return "counter " + std::to_string(t.counter()) + ", " + dollars(t.amount_cents()) + " (running total " +
         dollars(t.cum_cents()) + "), tag_hash " + short_hex(t.tag_hash());
}

class Checks {
 public:
  explicit Checks(ProofVerdict& v) : v_(v) {}
  bool line(bool ok, std::string text) {
    v_.lines.push_back({ok, std::move(text)});
    return ok;
  }
  void note(std::string text) { v_.notes.push_back(std::move(text)); }
  bool all_ok() const {
    return std::all_of(v_.lines.begin(), v_.lines.end(), [](const ProofLine& l) { return l.ok; });
  }

 private:
  ProofVerdict& v_;
};

// Decode one displayed object from its transport JSON and check that what
// the server shows next to it (fields, canonical text, digest) is exactly
// what is signed, so a page can't show one thing and sign another.
Object decode_displayed(const Json& entry, std::string_view type, const std::string& label, Checks& c) {
  if (!entry.is_object()) throw EncodingError(label + ": object expected");
  for (const auto& key : kDisplayedKeys) {
    if (!entry.contains(key)) throw EncodingError(label + ": missing '" + key + "'");
  }
  if (entry.at("type") != std::string(type)) throw EncodingError(label + ": expected a " + std::string(type));
  Object o = Object::from_json(type, entry.at("json"));
  // Field order isn't part of the claim, so compare `fields` as plain JSON.
  bool same_fields = nlohmann::json::parse(o.to_fields().dump()) == nlohmann::json::parse(entry.at("fields").dump());
  bool same_text = entry.at("canonical") == o.canonical() && entry.at("digest") == to_hex(o.digest());
  c.line(same_fields && same_text,
         label + ": the fields and signed text shown match the signed object (canonical string rebuilt here)");
  return o;
}

}  // namespace

Bytes parse_public_key_arg(const std::string& text) {
  bool is_hex = text.size() == 2 * kPubLen && std::all_of(text.begin(), text.end(), [](char ch) {
                  return std::isxdigit(static_cast<unsigned char>(ch));
                });
  Bytes pub = is_hex ? from_hex(text) : b64u_decode(text);
  if (!is_valid_public_key(pub)) throw EncodingError("not a 33-byte compressed P-256 public key: " + text);
  return pub;
}

ProofVerdict check_proof(const Json& doc, const std::optional<Bytes>& pinned_server_pub) {
  if (!doc.is_object()) throw EncodingError("a /v1/proof document is a JSON object");
  for (const auto& key : kProofKeys) {
    if (!doc.contains(key)) throw EncodingError("not a /v1/proof document: missing '" + key + "'");
  }
  ProofVerdict v;
  Checks c(v);
  for (const auto& item : doc.items()) {
    if (std::find(kProofKeys.begin(), kProofKeys.end(), item.key()) == kProofKeys.end()) {
      c.note("key '" + item.key() + "' is not checked");
    }
  }
  if (!doc.at("case_id").is_number_integer() || !doc.at("rule").is_string()) {
    throw EncodingError("case_id must be an integer and rule a string");
  }
  v.case_id = doc.at("case_id").get<std::int64_t>();
  v.rule = doc.at("rule").get<std::string>();

  // Which server key the certificate is checked against.
  Bytes file_server_pub = b64u_decode(doc.at("server_pub").get<std::string>());
  Bytes server_pub = pinned_server_pub.value_or(file_server_pub);
  std::string key_source = pinned_server_pub ? "pinned with --server-pub" : "taken from this file, not pinned";
  if (!pinned_server_pub) {
    c.note("the server key comes from the file being checked; pass --server-pub to pin StormCash's key");
  } else if (file_server_pub != *pinned_server_pub) {
    c.note("the file names a different server key (" + to_hex(file_server_pub) + "); the pinned key is used");
  }

  if (doc.at("cert").is_null() || doc.at("tag_a").is_null() || doc.at("tag_b").is_null()) {
    c.line(false, "the file has a certificate and both tags");
    v.status = ProofStatus::Invalid;
    v.verdict = "NOT VERIFIED: the file is missing the certificate or a tag.";
    return v;
  }
  Cert cert(decode_displayed(doc.at("cert"), "CERT", "CERT", c));
  Tag a(decode_displayed(doc.at("tag_a"), "TAG", "TAG A", c));
  Tag b(decode_displayed(doc.at("tag_b"), "TAG", "TAG B", c));
  const Bytes& holder = cert.holder_pub();

  // 1. The certificate binds holder_pub to this cert_id, signed by StormCash.
  c.line(cert.verify(server_pub), "CERT " + short_hex(cert.cert_id()) + " v" + std::to_string(cert.cert_ver()) +
                                      " (cap " + dollars(cert.cap_cents()) + "): signature valid under server key " +
                                      to_hex(server_pub) + " (" + key_source + ")");
  if (!doc.at("holder_pub").is_null()) {
    c.line(b64u_decode(doc.at("holder_pub").get<std::string>()) == holder,
           "holder_pub shown matches the certificate's holder key");
  }

  // 2. Both tags are signed by that holder key and spend that certificate.
  c.line(a.verify(holder), "TAG A " + tag_summary(a) + ": signature valid under holder key " + to_hex(holder));
  c.line(b.verify(holder), "TAG B " + tag_summary(b) + ": signature valid under holder key " + to_hex(holder));
  c.line(a.cert_id() == cert.cert_id() && b.cert_id() == cert.cert_id(),
         "both tags spend certificate " + to_hex(cert.cert_id()));

  // 3. The rule, re-derived from the signed fields.
  std::vector<Rule> fired = rules_fired(a, b);
  auto fired_text = [&] {
    std::string s;
    for (Rule r : fired) s += (s.empty() ? "" : ", ") + std::string(rule_name(r));
    return s.empty() ? std::string("none") : s;
  };
  bool incomplete = false;
  std::string claim;
  if (auto rule = parse_rule(v.rule)) {
    bool holds = std::find(fired.begin(), fired.end(), *rule) != fired.end();
    c.line(holds, v.rule + " holds for the signed fields (rules the pair breaks: " + fired_text() + ")");
    if (holds && fired.front() != *rule) {
      c.note("the pair also breaks " + std::string(rule_name(fired.front())) +
             ", a lower-numbered rule; proof builders name the lowest one (§7.4 PROOF)");
    }
    claim = "double spend";
  } else if (v.rule == "MERCHANT_KNEW") {
    // tag_a is the conflicting tag x, tag_b the payment z the merchant accepted (cases.py).
    c.line(!fired.empty(), "TAG A and TAG B are a double spend (rules the pair breaks: " + fired_text() + ")");
    bool held = false;
    std::size_t index = 0;
    for (const Json& entry : doc.at("log_entries")) {
      Dlog d(decode_displayed(entry, "DLOG", "log entry " + std::to_string(++index), c));
      c.line(d.verify_self(), "log entry " + std::to_string(index) + " (" + d.kind() + ", seq " +
                                  std::to_string(d.seq()) + "): signature valid under device key " +
                                  to_hex(d.device_pub()));
      if (d.kind() == "ACCEPT" && d.tag_hash() == b.tag_hash()) {
        bool lists_a = std::find(d.held_ids().begin(), d.held_ids().end(), a.tag_hash()) != d.held_ids().end();
        if (lists_a) {
          c.line(true,
                 "that device's ACCEPT entry for payment B lists payment A in held_ids: it already held the "
                 "conflicting payment when it accepted (§9.4 clause a)");
          held = true;
        }
      }
    }
    if (!held) {
      incomplete = true;
      c.note(
          "no ACCEPT entry in the file lists payment A in held_ids, so the case rests on clause (b), a paired "
          "CONTACT before acceptance; /v1/proof doesn't include those CONTACT entries, so only the double spend "
          "is verified here");
    }
    c.note(
        "the ACCEPT entry is checked against its own device key; the file has no MCERT tying that key to the "
        "shop");
    claim = held ? "merchant knew" : "double spend";
  } else {
    c.line(false, "rule " + v.rule + " can't be checked from a pair of tags");
  }

  // Verdict.
  std::string key_words = pinned_server_pub
                              ? "signed by StormCash (server key " + short_hex(server_pub) + ", pinned)"
                              : "signed by the server key in this file (" + short_hex(server_pub) + ", not pinned)";
  if (!c.all_ok()) {
    v.status = ProofStatus::Invalid;
    for (const auto& line : v.lines) {
      if (!line.ok) {
        v.verdict = "NOT VERIFIED: " + line.text;
        break;
      }
    }
    return v;
  }
  v.status = incomplete ? ProofStatus::Incomplete : ProofStatus::Proven;
  if (v.rule == "MERCHANT_KNEW") {
    v.verdict = std::string("MERCHANT_KNEW: double spend (") + std::string(rule_name(fired.front())) +
                ") proven by two signatures under holder key " + short_hex(holder) + "; certificate " + key_words +
                (incomplete ? "; that the merchant knew is NOT shown by this file (see notes)."
                            : "; the merchant's own signed log shows it already held payment A.");
  } else {
    v.verdict = v.rule + ": both signatures valid under holder key " + short_hex(holder) + "; certificate " +
                key_words + ". That is a self-proving " + claim + ".";
  }
  return v;
}

std::string format_proof(const ProofVerdict& v) {
  std::ostringstream out;
  out << "Case " << v.case_id << ": " << v.rule << "\n";
  for (const auto& line : v.lines) out << "  " << (line.ok ? "ok    " : "FAIL  ") << line.text << "\n";
  for (const auto& note : v.notes) out << "  note  " << note << "\n";
  out << "\n" << v.verdict << "\n";
  return out.str();
}

}  // namespace stormcash
