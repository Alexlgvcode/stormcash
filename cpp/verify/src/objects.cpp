#include "stormcash/objects.hpp"

#include <algorithm>
#include <set>
#include <stdexcept>

#include "stormcash/crypto.hpp"
#include "stormcash/encoding.hpp"

namespace stormcash {
namespace {

using K = FieldKind;

// Field tables, copied from the spec. Row order IS the canonical order.
// Function-local statics so no other translation unit can see them half-built.

const FieldList& cert_fields() {  // §7.4 CERT
  static const FieldList f = {
      {"cert_id", "ci", K::kBytes, 16}, {"cert_ver", "cv", K::kInt},  {"holder_pub", "hp", K::kBytes, 33},
      {"cap_cents", "cap", K::kInt},    {"issued_at", "ia", K::kInt}, {"expires_at", "ea", K::kInt},
      {"escrow_ref", "er", K::kString},
  };
  return f;
}

const FieldList& mcert_fields() {  // §7.4 MCERT
  static const FieldList f = {
      {"merchant_id", "mi", K::kBytes, 16}, {"merchant_ver", "mv", K::kInt}, {"merchant_pub", "mp", K::kBytes, 33},
      {"display_name", "dn", K::kString},   {"region_id", "rg", K::kString}, {"expires_at", "ea", K::kInt},
  };
  return f;
}

const FieldList& req_fields() {  // §7.4 REQ
  static const FieldList f = {
      {"merchant_id", "mi", K::kBytes, 16},
      {"amount_cents", "amt", K::kInt},
      {"nonce", "n", K::kBytes, 16},
      {"req_expires_at", "rx", K::kInt},
  };
  return f;
}

const FieldList& det_fields() {  // §7.4 DET
  static const FieldList f = {
      {"merchant_pub", "mp", K::kBytes, 33},
      {"nonce", "n", K::kBytes, 16},
      {"ts", "ts", K::kInt},
  };
  return f;
}

const FieldList& tag_fields() {  // §7.4 TAG
  static const FieldList f = {
      {"cert_id", "ci", K::kBytes, 16}, {"counter", "k", K::kInt},     {"prev_hash", "ph", K::kBytes, 32},
      {"amount_cents", "amt", K::kInt}, {"cum_cents", "cum", K::kInt}, {"details_hash", "dh", K::kBytes, 32},
  };
  return f;
}

const FieldList& policy_fields() {  // §7.4 POLICY
  static const FieldList f = {
      {"policy_ver", "pv", K::kInt},
      {"issued_at", "ia", K::kInt},
      {"frozen_certs", "fc", K::kBytesList, 16},
      {"merchant_limits", "ml", K::kStringList},
  };
  return f;
}

const FieldList& renew_fields() {  // §7.4 RENEW
  static const FieldList f = {
      {"cert_id", "ci", K::kBytes, 16},
      {"chain_head", "ch", K::kBytes, 32},
      {"counter", "k", K::kInt},
      {"ts", "ts", K::kInt},
  };
  return f;
}

const FieldList& rcpt_fields() {  // §7.4 RCPT
  static const FieldList f = {
      {"ts", "ts", K::kInt},
      {"item_ids", "ids", K::kBytesList, 32},
  };
  return f;
}

// §9.2 DLOG: a common header, then a body per kind.
FieldList dlog_header() {
  return {
      {"device_pub", "dp", K::kBytes, 33},
      {"seq", "q", K::kInt},
      {"prev_hash", "ph", K::kBytes, 32},
      {"ts", "ts", K::kInt},
      {.name = "kind", .key = "kd", .kind = K::kEnum, .allowed = kDlogKinds},
  };
}

FieldList with_body(FieldList header, const FieldList& body) {
  header.insert(header.end(), body.begin(), body.end());
  return header;
}

const FieldList& dlog_accept_fields() {
  static const FieldList f = with_body(dlog_header(), {
                                                          {"tag_hash", "th", K::kBytes, 32},
                                                          {"cert_id", "ci", K::kBytes, 16},
                                                          {"held_ids", "hi", K::kBytesList, 32},
                                                      });
  return f;
}

const FieldList& dlog_refuse_fields() {
  static const FieldList f =
      with_body(dlog_header(), {
                                   {"tag_hash", "th", K::kBytes, 32},
                                   {"cert_id", "ci", K::kBytes, 16},
                                   {.name = "check", .key = "ck", .kind = K::kEnum, .allowed = kChecks},
                               });
  return f;
}

const FieldList& dlog_contact_fields() {
  static const FieldList f = with_body(dlog_header(), {
                                                          {"contact_id", "cid", K::kBytes, 32},
                                                          {"peer_pub", "pp", K::kBytes, 33},
                                                          {"sent_ids", "si", K::kBytesList, kId8Len},
                                                          {"recv_ids", "ri", K::kBytesList, kId8Len},
                                                          {"sent_overflow", "so", K::kInt},
                                                          {"recv_overflow", "ro", K::kInt},
                                                      });
  return f;
}

constexpr std::array<std::string_view, 9> kObjectTypes = {"CERT",   "MCERT", "REQ",  "DET", "TAG",
                                                          "POLICY", "RENEW", "RCPT", "DLOG"};

// JSON helpers -----------------------------------------------------------------

std::int64_t int_from_json(const Json& j, std::string_view name) {
  // Booleans are their own JSON type in nlohmann, so `true` is not an integer here.
  if (!j.is_number_integer()) throw EncodingError(std::string(name) + ": integer expected");
  if (j.is_number_unsigned()) {
    auto u = j.get<std::uint64_t>();
    if (u > static_cast<std::uint64_t>(kMaxInt)) throw EncodingError("integer exceeds 2^53 - 1");
    return static_cast<std::int64_t>(u);
  }
  return j.get<std::int64_t>();  // a negative value is rejected by render_int in validate()
}

const std::string& string_from_json(const Json& j, std::string_view name) {
  if (!j.is_string()) throw EncodingError(std::string(name) + ": string expected");
  return j.get_ref<const std::string&>();
}

const Json& array_from_json(const Json& j, std::string_view name) {
  if (!j.is_array()) throw EncodingError(std::string(name) + ": list expected");
  return j;
}

using BytesDecoder = Bytes (*)(std::string_view);
using BytesEncoder = std::string (*)(const Bytes&);

Value decode_value(const Field& f, const Json& j, BytesDecoder decode) {
  switch (f.kind) {
    case K::kInt:
      return int_from_json(j, f.name);
    case K::kBytes:
      return decode(string_from_json(j, f.name));
    case K::kString:
    case K::kEnum:
      return string_from_json(j, f.name);
    case K::kBytesList: {
      std::vector<Bytes> out;
      for (const Json& item : array_from_json(j, f.name)) out.push_back(decode(string_from_json(item, f.name)));
      return out;
    }
    case K::kStringList: {
      std::vector<std::string> out;
      for (const Json& item : array_from_json(j, f.name)) out.push_back(string_from_json(item, f.name));
      return out;
    }
  }
  throw std::logic_error("unhandled field kind");
}

Json encode_value(const Field& f, const Value& v, BytesEncoder encode) {
  switch (f.kind) {
    case K::kInt:
      return std::get<std::int64_t>(v);
    case K::kBytes:
      return encode(std::get<Bytes>(v));
    case K::kString:
    case K::kEnum:
      return std::get<std::string>(v);
    case K::kBytesList: {
      Json out = Json::array();
      for (const Bytes& b : std::get<std::vector<Bytes>>(v)) out.push_back(encode(b));
      return out;
    }
    case K::kStringList: {
      Json out = Json::array();
      for (const std::string& s : std::get<std::vector<std::string>>(v)) out.push_back(s);
      return out;
    }
  }
  throw std::logic_error("unhandled field kind");
}

std::string render_value(const Field& f, const Value& v) {
  switch (f.kind) {
    case K::kInt:
      return render_int(std::get<std::int64_t>(v));
    case K::kBytes:
      return render_bytes(std::get<Bytes>(v), f.size);
    case K::kString:
      return render_string(std::get<std::string>(v));
    case K::kEnum:
      return render_enum(std::get<std::string>(v), f.allowed);
    case K::kBytesList:
      return render_bytes_list(std::get<std::vector<Bytes>>(v), f.size);
    case K::kStringList:
      return render_string_list(std::get<std::vector<std::string>>(v));
  }
  throw std::logic_error("unhandled field kind");
}

// Rejects missing and unknown keys (§7.3), naming them in the error.
void check_keys(const Json& data, const std::set<std::string>& allowed, const std::set<std::string>& required,
                std::string_view what) {
  if (!data.is_object()) throw EncodingError(std::string(what) + ": object expected");
  std::string problems;
  for (const auto& key : required) {
    if (!data.contains(key)) problems += " missing '" + key + "'";
  }
  for (const auto& item : data.items()) {
    if (!allowed.count(item.key())) problems += " unknown '" + item.key() + "'";
  }
  if (!problems.empty()) throw EncodingError(std::string(what) + ":" + problems);
}

// The DLOG body is chosen by the `kind` value, so read it before the field list.
std::string dlog_kind_of(const Json& data, const char* key) {
  if (!data.is_object()) return {};
  auto it = data.find(key);
  if (it == data.end() || !it->is_string()) return {};
  return it->get<std::string>();
}

// Strict parse of "<merchant_id_hex>:<cents>" (POLICY merchant_limits, §7.4):
// 32 lowercase hex digits, ':', then 0 or a number without leading zeros.
std::optional<std::pair<std::string, std::int64_t>> parse_merchant_limit(const std::string& entry) {
  if (entry.size() < 34 || entry[32] != ':') return std::nullopt;
  std::string id = entry.substr(0, 32);
  if (!std::all_of(id.begin(), id.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); })) {
    return std::nullopt;
  }
  std::string digits = entry.substr(33);
  if (!std::all_of(digits.begin(), digits.end(), [](char c) { return c >= '0' && c <= '9'; })) return std::nullopt;
  if (digits.size() > 1 && digits[0] == '0') return std::nullopt;
  if (digits.size() > 16) throw EncodingError("merchant limit exceeds 2^53 - 1");  // 2^53 has 16 digits
  std::int64_t cents = std::stoll(digits);
  render_int(cents);  // ≤ 2^53 − 1
  return std::make_pair(id, cents);
}

}  // namespace

// Schema lookup ------------------------------------------------------------------

bool is_object_type(std::string_view type) {
  return std::find(kObjectTypes.begin(), kObjectTypes.end(), type) != kObjectTypes.end();
}

bool is_signed_type(std::string_view type) { return type != "DET"; }

const FieldList& fields_for(std::string_view type, std::string_view dlog_kind) {
  if (type == "CERT") return cert_fields();
  if (type == "MCERT") return mcert_fields();
  if (type == "REQ") return req_fields();
  if (type == "DET") return det_fields();
  if (type == "TAG") return tag_fields();
  if (type == "POLICY") return policy_fields();
  if (type == "RENEW") return renew_fields();
  if (type == "RCPT") return rcpt_fields();
  if (type == "DLOG") {
    if (dlog_kind == "ACCEPT") return dlog_accept_fields();
    if (dlog_kind == "REFUSE") return dlog_refuse_fields();
    if (dlog_kind == "CONTACT") return dlog_contact_fields();
    throw EncodingError("unknown DLOG kind '" + std::string(dlog_kind) + "'");
  }
  throw EncodingError("unknown object type '" + std::string(type) + "'");
}

// Object -------------------------------------------------------------------------

Object::Object(std::string type, const FieldList* fields, std::vector<Value> values, std::optional<Bytes> sig)
    : type_(std::move(type)), fields_(fields), values_(std::move(values)), sig_(std::move(sig)) {
  validate();
}

void Object::validate() const {
  canonical();  // renders every field: throws on any value without a canonical form
  if (sig_) render_bytes(*sig_, kSigLen);

  if (type_ == "POLICY") {
    std::set<std::string> seen;
    for (const std::string& entry : string_list("merchant_limits")) {
      auto parsed = parse_merchant_limit(entry);
      if (!parsed) throw EncodingError("invalid merchant limit '" + entry + "'");
      if (!seen.insert(parsed->first).second) throw EncodingError("duplicate merchant limit for " + parsed->first);
    }
  }
  if (type_ == "DLOG") {
    if (text("kind") == "CONTACT" &&
        (bytes_list("sent_ids").size() > kContactIdsCap || bytes_list("recv_ids").size() > kContactIdsCap)) {
      throw EncodingError("CONTACT id lists are capped at 200");
    }
    if (integer("seq") < 1) throw EncodingError("DLOG seq starts at 1");
  }
}

Object Object::from_fields(std::string_view type, const Json& fields, const Json& sig) {
  const FieldList& specs = fields_for(type, type == "DLOG" ? dlog_kind_of(fields, "kind") : "");
  std::set<std::string> names;
  for (const Field& f : specs) names.emplace(f.name);
  check_keys(fields, names, names, type);

  std::vector<Value> values;
  for (const Field& f : specs) values.push_back(decode_value(f, fields.at(std::string(f.name)), &from_hex));

  std::optional<Bytes> signature;
  if (!sig.is_null()) {
    if (!is_signed_type(type)) throw EncodingError(std::string(type) + " is not a signed object");
    signature = from_hex(string_from_json(sig, "sig"));
  }
  return Object(std::string(type), &specs, std::move(values), std::move(signature));
}

Object Object::from_vector(const Json& entry) {
  check_keys(entry, {"type", "fields", "sig"}, {"type", "fields", "sig"}, "vector object");
  return from_fields(string_from_json(entry.at("type"), "type"), entry.at("fields"), entry.at("sig"));
}

Object Object::from_json(std::string_view type, const Json& data) {
  const FieldList& specs = fields_for(type, type == "DLOG" ? dlog_kind_of(data, "kd") : "");
  std::set<std::string> required;
  for (const Field& f : specs) required.emplace(f.key);
  std::set<std::string> allowed = required;
  if (is_signed_type(type)) allowed.emplace("sig");
  check_keys(data, allowed, required, type);

  std::vector<Value> values;
  for (const Field& f : specs) values.push_back(decode_value(f, data.at(std::string(f.key)), &b64u_decode));

  std::optional<Bytes> signature;
  if (data.contains("sig")) signature = b64u_decode(string_from_json(data.at("sig"), "sig"));
  return Object(std::string(type), &specs, std::move(values), std::move(signature));
}

std::string Object::canonical() const {
  std::vector<std::string> rendered;
  rendered.reserve(values_.size());
  for (std::size_t i = 0; i < values_.size(); ++i) rendered.push_back(render_value((*fields_)[i], values_[i]));
  return stormcash::canonical(type_, rendered);
}

Bytes Object::digest() const { return stormcash::digest(canonical()); }

bool Object::verify(const Bytes& pub) const { return sig_ && verify_digest(pub, digest(), *sig_); }

Json Object::to_fields() const {
  Json out = Json::object();
  for (std::size_t i = 0; i < values_.size(); ++i) {
    const Field& f = (*fields_)[i];
    out[std::string(f.name)] = encode_value(f, values_[i], &to_hex);
  }
  return out;
}

Json Object::to_json() const {
  Json out = Json::object();
  for (std::size_t i = 0; i < values_.size(); ++i) {
    const Field& f = (*fields_)[i];
    out[std::string(f.key)] = encode_value(f, values_[i], &b64u_encode);
  }
  if (sig_) out["sig"] = b64u_encode(*sig_);
  return out;
}

bool Object::has(std::string_view name) const {
  return std::any_of(fields_->begin(), fields_->end(), [&](const Field& f) { return f.name == name; });
}

const Value& Object::value(std::string_view name, FieldKind a, FieldKind b) const {
  for (std::size_t i = 0; i < fields_->size(); ++i) {
    const Field& f = (*fields_)[i];
    if (f.name != name) continue;
    if (f.kind != a && f.kind != b) throw std::logic_error(type_ + "." + std::string(name) + " has another kind");
    return values_[i];
  }
  throw std::logic_error(type_ + " has no field " + std::string(name));
}

std::int64_t Object::integer(std::string_view name) const {
  return std::get<std::int64_t>(value(name, K::kInt, K::kInt));
}
const Bytes& Object::bytes(std::string_view name) const { return std::get<Bytes>(value(name, K::kBytes, K::kBytes)); }
const std::string& Object::text(std::string_view name) const {
  return std::get<std::string>(value(name, K::kString, K::kEnum));
}
const std::vector<Bytes>& Object::bytes_list(std::string_view name) const {
  return std::get<std::vector<Bytes>>(value(name, K::kBytesList, K::kBytesList));
}
const std::vector<std::string>& Object::string_list(std::string_view name) const {
  return std::get<std::vector<std::string>>(value(name, K::kStringList, K::kStringList));
}

bool operator==(const Object& a, const Object& b) {
  return a.type_ == b.type_ && a.fields_ == b.fields_ && a.values_ == b.values_ && a.sig_ == b.sig_;
}

// Typed views ----------------------------------------------------------------------

TypedObject::TypedObject(Object obj, std::string_view type) : obj_(std::move(obj)) {
  if (obj_.type() != type) {
    throw EncodingError("expected a " + std::string(type) + ", got a " + obj_.type());
  }
}

Tag::Tag(Object obj) : TypedObject(std::move(obj), "TAG"), tag_hash_(obj_.digest()) {}

Dlog::Dlog(Object obj) : TypedObject(std::move(obj), "DLOG"), entry_hash_(obj_.digest()) {}

bool Policy::is_frozen(const Bytes& cert_id) const {
  const auto& frozen = frozen_certs();
  return std::find(frozen.begin(), frozen.end(), cert_id) != frozen.end();
}

std::optional<std::int64_t> Policy::merchant_limit(const Bytes& merchant_id) const {
  const std::string id = to_hex(merchant_id);
  for (const std::string& entry : obj_.string_list("merchant_limits")) {
    auto parsed = parse_merchant_limit(entry);  // validated when the POLICY was built
    if (parsed && parsed->first == id) return parsed->second;
  }
  return std::nullopt;
}

// Composites -----------------------------------------------------------------------

Json Pay::to_json() const {
  Json out = Json::object();
  out["c"] = cert.to_json();
  out["t"] = tag.to_json();
  out["d"] = det.to_json();
  return out;
}

Pay Pay::from_json(const Json& data) {
  check_keys(data, {"c", "t", "d"}, {"c", "t", "d"}, "PAY");
  return Pay{Cert(Object::from_json("CERT", data.at("c"))), Tag(Object::from_json("TAG", data.at("t"))),
             Det(Object::from_json("DET", data.at("d")))};
}

Pay Pay::from_vector(const Json& entry) {
  return Pay{Cert(Object::from_vector(entry.at("c"))), Tag(Object::from_vector(entry.at("t"))),
             Det(Object::from_vector(entry.at("d")))};
}

bool operator==(const Pay& a, const Pay& b) {
  return a.cert.object() == b.cert.object() && a.tag.object() == b.tag.object() && a.det.object() == b.det.object();
}

std::string_view rule_name(Rule rule) {
  switch (rule) {
    case Rule::SameCounter:
      return "SAME_COUNTER";
    case Rule::BrokenLink:
      return "BROKEN_LINK";
    case Rule::TotalBackwards:
      return "TOTAL_BACKWARDS";
  }
  throw std::logic_error("unhandled rule");
}

std::optional<Rule> parse_rule(std::string_view name) {
  for (Rule r : {Rule::SameCounter, Rule::BrokenLink, Rule::TotalBackwards}) {
    if (rule_name(r) == name) return r;
  }
  return std::nullopt;
}

Json Proof::to_json() const {
  Json out = Json::object();
  out["a"] = a.to_json();
  out["b"] = b.to_json();
  out["rule"] = std::string(rule_name(rule));
  return out;
}

Proof Proof::from_json(const Json& data) {
  check_keys(data, {"a", "b", "rule"}, {"a", "b", "rule"}, "PROOF");
  const std::string& name = string_from_json(data.at("rule"), "rule");
  auto rule = parse_rule(name);
  if (!rule) throw EncodingError("unknown proof rule '" + name + "'");
  return Proof{Tag(Object::from_json("TAG", data.at("a"))), Tag(Object::from_json("TAG", data.at("b"))), *rule};
}

bool operator==(const Proof& x, const Proof& y) {
  return x.a.object() == y.a.object() && x.b.object() == y.b.object() && x.rule == y.rule;
}

// Derived hashes and ids -----------------------------------------------------------------

std::string gen_canonical(const Bytes& cert_id) { return canonical("GEN", {render_bytes(cert_id, 16)}); }
Bytes genesis(const Bytes& cert_id) { return digest(gen_canonical(cert_id)); }

std::string dgen_canonical(const Bytes& device_pub) { return canonical("DGEN", {render_bytes(device_pub, 33)}); }
Bytes dlog_genesis(const Bytes& device_pub) { return digest(dgen_canonical(device_pub)); }

std::string contact_canonical(const Bytes& pub_a, const Bytes& nonce_a, const Bytes& pub_b, const Bytes& nonce_b) {
  if (pub_a == pub_b) throw EncodingError("a contact needs two different devices");
  // Pubs sorted bytewise; each nonce travels with its own pub.
  bool a_low = pub_a < pub_b;
  const Bytes& pub_lo = a_low ? pub_a : pub_b;
  const Bytes& pub_hi = a_low ? pub_b : pub_a;
  const Bytes& nonce_lo = a_low ? nonce_a : nonce_b;
  const Bytes& nonce_hi = a_low ? nonce_b : nonce_a;
  return canonical("CONTACT", {render_bytes(pub_lo, 33), render_bytes(pub_hi, 33), render_bytes(nonce_lo, 16),
                               render_bytes(nonce_hi, 16)});
}

Bytes contact_id(const Bytes& pub_a, const Bytes& nonce_a, const Bytes& pub_b, const Bytes& nonce_b) {
  return digest(contact_canonical(pub_a, nonce_a, pub_b, nonce_b));
}

std::string proof_canonical(const Bytes& hash_a, const Bytes& hash_b) {
  const Bytes& lo = std::min(hash_a, hash_b);
  const Bytes& hi = std::max(hash_a, hash_b);
  return canonical("PRF", {render_bytes(lo, 32), render_bytes(hi, 32)});
}

Bytes item_id(std::string_view kind, const Object& body) {
  static constexpr std::array<std::string_view, 6> kDigestKinds = {"POLICY", "RCPT", "CERT", "RENEW", "DLOG", "TAG"};
  if (std::find(kDigestKinds.begin(), kDigestKinds.end(), kind) == kDigestKinds.end() || body.type() != kind) {
    throw EncodingError("invalid item kind '" + std::string(kind) + "' for a " + body.type());
  }
  return body.digest();
}

Bytes item_id(const Pay& pay) { return pay.tag.tag_hash(); }

Bytes item_id(const Proof& proof) { return digest(proof_canonical(proof.a.tag_hash(), proof.b.tag_hash())); }

}  // namespace stormcash
