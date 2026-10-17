// Protocol objects (spec §7.4, §9.2, §10.2) and their two JSON codecs.
//
// Each object type is a table of fields in canonical order, copied from the
// spec tables (objects.cpp). One generic Object handles every type:
//
// - vector form (`from_fields` / `to_fields`): long field names, bytes as
//   lowercase hex, as used in spec/vectors.json (§20);
// - transport JSON (`from_json` / `to_json`): short keys, bytes as base64url
//   without padding, signature in `sig` (§7.3). Decoders reject missing or
//   unknown keys.
//
// An Object is validated when it is built: if it exists, it has a canonical
// string. Typed views (Cert, Tag, Dlog, ...) wrap an Object for the rules.
#pragma once

#include <array>
#include <cstdint>
#include <nlohmann/json.hpp>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

#include "stormcash/bytes.hpp"

namespace stormcash {

// Keeps keys in the order they were written, so transport JSON can be
// compared with the vectors key for key.
using Json = nlohmann::ordered_json;

inline constexpr std::array<std::string_view, 3> kDlogKinds = {"ACCEPT", "REFUSE", "CONTACT"};
inline constexpr std::array<std::string_view, 6> kChecks = {"C1", "C2", "C3", "C4", "C5", "C6"};
inline constexpr std::size_t kContactIdsCap = 200;  // CONTACT sent_ids / recv_ids (§9.2)
inline constexpr std::size_t kId8Len = 8;

// k-prefixed so the enumerators can't shadow the Bytes type (GCC -Wshadow).
enum class FieldKind { kInt, kBytes, kString, kEnum, kBytesList, kStringList };

struct Field {
  std::string_view name;  // long name: spec tables and vectors
  std::string_view key;   // short transport key (§7.3)
  FieldKind kind;
  std::size_t size = 0;                            // byte length of Bytes / BytesList items (0 = any)
  std::span<const std::string_view> allowed = {};  // Enum tokens (empty = any token)
};
using FieldList = std::vector<Field>;

// The fields of an object type in canonical order. For DLOG the body depends
// on `dlog_kind` (§9.2); an unknown type or kind throws EncodingError.
const FieldList& fields_for(std::string_view type, std::string_view dlog_kind = {});
bool is_object_type(std::string_view type);
bool is_signed_type(std::string_view type);  // DET is the only unsigned object

using Value = std::variant<std::int64_t, Bytes, std::string, std::vector<Bytes>, std::vector<std::string>>;

class Object {
 public:
  // Vector form: {long name: value}, bytes as hex; `sig` is null or hex.
  static Object from_fields(std::string_view type, const Json& fields, const Json& sig);
  // A vector entry {type, fields, sig}.
  static Object from_vector(const Json& entry);
  // Transport JSON: {short key: value}, bytes as base64url, optional `sig`.
  static Object from_json(std::string_view type, const Json& data);

  const std::string& type() const { return type_; }
  const FieldList& fields() const { return *fields_; }
  const std::optional<Bytes>& sig() const { return sig_; }

  std::string canonical() const;
  Bytes digest() const;  // SHA-256 of canonical(); never includes the signature
  // False when there is no signature, or it isn't valid for digest() under pub.
  bool verify(const Bytes& pub) const;

  Json to_fields() const;
  Json to_json() const;

  // Field access by long name. Asking for a field the type doesn't have, or
  // with the wrong kind, is a programming error (std::logic_error).
  bool has(std::string_view name) const;
  std::int64_t integer(std::string_view name) const;
  const Bytes& bytes(std::string_view name) const;
  const std::string& text(std::string_view name) const;  // String or Enum
  const std::vector<Bytes>& bytes_list(std::string_view name) const;
  const std::vector<std::string>& string_list(std::string_view name) const;

  friend bool operator==(const Object& a, const Object& b);

 private:
  Object(std::string type, const FieldList* fields, std::vector<Value> values, std::optional<Bytes> sig);
  void validate() const;
  const Value& value(std::string_view name, FieldKind a, FieldKind b) const;

  std::string type_;
  const FieldList* fields_;
  std::vector<Value> values_;  // same order as *fields_
  std::optional<Bytes> sig_;
};

// Typed views ----------------------------------------------------------------

// A validated Object of one known type.
class TypedObject {
 public:
  const Object& object() const { return obj_; }
  Bytes digest() const { return obj_.digest(); }
  bool verify(const Bytes& pub) const { return obj_.verify(pub); }
  Json to_json() const { return obj_.to_json(); }

 protected:
  TypedObject(Object obj, std::string_view type);
  Object obj_;
};

// CERT: resident certificate, signed by the server.
class Cert : public TypedObject {
 public:
  explicit Cert(Object obj) : TypedObject(std::move(obj), "CERT") {}
  const Bytes& cert_id() const { return obj_.bytes("cert_id"); }
  std::int64_t cert_ver() const { return obj_.integer("cert_ver"); }
  const Bytes& holder_pub() const { return obj_.bytes("holder_pub"); }
  std::int64_t cap_cents() const { return obj_.integer("cap_cents"); }
  std::int64_t issued_at() const { return obj_.integer("issued_at"); }
  std::int64_t expires_at() const { return obj_.integer("expires_at"); }
  const std::string& escrow_ref() const { return obj_.text("escrow_ref"); }
};

// MCERT: merchant certificate, signed by the server.
class Mcert : public TypedObject {
 public:
  explicit Mcert(Object obj) : TypedObject(std::move(obj), "MCERT") {}
  const Bytes& merchant_id() const { return obj_.bytes("merchant_id"); }
  const Bytes& merchant_pub() const { return obj_.bytes("merchant_pub"); }
  const std::string& display_name() const { return obj_.text("display_name"); }
  std::int64_t expires_at() const { return obj_.integer("expires_at"); }
};

// REQ: payment request, signed by the merchant.
class Req : public TypedObject {
 public:
  explicit Req(Object obj) : TypedObject(std::move(obj), "REQ") {}
  const Bytes& merchant_id() const { return obj_.bytes("merchant_id"); }
  std::int64_t amount_cents() const { return obj_.integer("amount_cents"); }
  const Bytes& nonce() const { return obj_.bytes("nonce"); }
  std::int64_t req_expires_at() const { return obj_.integer("req_expires_at"); }
};

// DET: payment details. Unsigned; its digest is the tag's details_hash.
class Det : public TypedObject {
 public:
  explicit Det(Object obj) : TypedObject(std::move(obj), "DET") {}
  const Bytes& merchant_pub() const { return obj_.bytes("merchant_pub"); }
  const Bytes& nonce() const { return obj_.bytes("nonce"); }
  std::int64_t ts() const { return obj_.integer("ts"); }
};

// TAG: spend tag, signed by the holder. Its digest is the tag_hash (= payment id).
class Tag : public TypedObject {
 public:
  explicit Tag(Object obj);
  const Bytes& cert_id() const { return obj_.bytes("cert_id"); }
  std::int64_t counter() const { return obj_.integer("counter"); }
  const Bytes& prev_hash() const { return obj_.bytes("prev_hash"); }
  std::int64_t amount_cents() const { return obj_.integer("amount_cents"); }
  std::int64_t cum_cents() const { return obj_.integer("cum_cents"); }
  const Bytes& details_hash() const { return obj_.bytes("details_hash"); }
  const Bytes& tag_hash() const { return tag_hash_; }

 private:
  Bytes tag_hash_;  // computed once
};

// POLICY: signed list of frozen certs and per-merchant payment limits.
class Policy : public TypedObject {
 public:
  explicit Policy(Object obj) : TypedObject(std::move(obj), "POLICY") {}
  std::int64_t policy_ver() const { return obj_.integer("policy_ver"); }
  const std::vector<Bytes>& frozen_certs() const { return obj_.bytes_list("frozen_certs"); }
  bool is_frozen(const Bytes& cert_id) const;
  // The "<merchant_id_hex>:<cents>" limit for this merchant, if any.
  std::optional<std::int64_t> merchant_limit(const Bytes& merchant_id) const;
};

// DLOG: device log entry, signed by device_pub. Its digest is the entry_hash.
// Body accessors throw std::logic_error for a field this kind doesn't have.
class Dlog : public TypedObject {
 public:
  explicit Dlog(Object obj);
  const Bytes& device_pub() const { return obj_.bytes("device_pub"); }
  std::int64_t seq() const { return obj_.integer("seq"); }
  const Bytes& prev_hash() const { return obj_.bytes("prev_hash"); }
  std::int64_t ts() const { return obj_.integer("ts"); }
  const std::string& kind() const { return obj_.text("kind"); }
  const Bytes& entry_hash() const { return entry_hash_; }
  // ACCEPT and REFUSE
  const Bytes& tag_hash() const { return obj_.bytes("tag_hash"); }
  const Bytes& cert_id() const { return obj_.bytes("cert_id"); }
  // ACCEPT
  const std::vector<Bytes>& held_ids() const { return obj_.bytes_list("held_ids"); }
  // CONTACT
  const Bytes& contact_id() const { return obj_.bytes("contact_id"); }
  const Bytes& peer_pub() const { return obj_.bytes("peer_pub"); }
  const std::vector<Bytes>& sent_ids() const { return obj_.bytes_list("sent_ids"); }
  const std::vector<Bytes>& recv_ids() const { return obj_.bytes_list("recv_ids"); }
  bool verify_self() const { return obj_.verify(device_pub()); }

 private:
  Bytes entry_hash_;
};

// Composites -----------------------------------------------------------------

// PAY: certificate + tag + details. Transport JSON {c, t, d}.
struct Pay {
  Cert cert;
  Tag tag;
  Det det;

  Json to_json() const;
  static Pay from_json(const Json& data);
  static Pay from_vector(const Json& entry);  // {c, t, d} as vector entries
  friend bool operator==(const Pay& a, const Pay& b);
};

// Equivocation rules R1–R3 (§8.3), numbered in precedence order.
enum class Rule { SameCounter = 1, BrokenLink = 2, TotalBackwards = 3 };
std::string_view rule_name(Rule rule);  // "SAME_COUNTER", "BROKEN_LINK", "TOTAL_BACKWARDS"
std::optional<Rule> parse_rule(std::string_view name);

// PROOF: two tags and the rule they break. No signature of its own: anyone
// with the holder's key can check it.
struct Proof {
  Tag a;
  Tag b;
  Rule rule;

  Json to_json() const;
  static Proof from_json(const Json& data);
  friend bool operator==(const Proof& x, const Proof& y);
};

// Derived hashes and ids ------------------------------------------------------

// GENESIS(cert_id) = SHA-256(canonical(GEN, cert_id)): prev_hash of counter 1 (§7.4).
std::string gen_canonical(const Bytes& cert_id);
Bytes genesis(const Bytes& cert_id);

// prev_hash of a device's DLOG entry with seq 1: SHA-256(canonical(DGEN, device_pub)) (§9.2).
std::string dgen_canonical(const Bytes& device_pub);
Bytes dlog_genesis(const Bytes& device_pub);

// canonical(CONTACT, pub_low, pub_high, nonce_low, nonce_high) (§9.2): each side
// passes its own (pub, HELLO nonce) and the peer's, in either order.
std::string contact_canonical(const Bytes& pub_a, const Bytes& nonce_a, const Bytes& pub_b, const Bytes& nonce_b);
Bytes contact_id(const Bytes& pub_a, const Bytes& nonce_a, const Bytes& pub_b, const Bytes& nonce_b);

// canonical(PRF, tag_hash, tag_hash) with the two hashes sorted (§10.2).
std::string proof_canonical(const Bytes& hash_a, const Bytes& hash_b);

// Item ids (§10.2). PAY and TAG of one payment share the tag_hash on purpose.
Bytes item_id(std::string_view kind, const Object& body);  // POLICY, RCPT, CERT, RENEW, DLOG, TAG
Bytes item_id(const Pay& pay);
Bytes item_id(const Proof& proof);
inline Bytes id8(const Bytes& full_id) { return prefix(full_id, kId8Len); }

}  // namespace stormcash
