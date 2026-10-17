// Offline checks and hard fraud rules (spec §8.2, §8.3, §9.4, §9.5).
//
// Pure functions over already-decoded objects: no clock, no I/O. Callers pass
// `now` explicitly. Inputs other than the PAY under test (stored tags, policy,
// device logs) are assumed to be verified already, as on a phone or server.
// Written from the spec; server/stormcash/protocol/rules.py is the reference
// the vectors were generated with.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "stormcash/objects.hpp"

namespace stormcash {

inline constexpr std::int64_t kClockToleranceS = 600;

// Single-tag validity (§8.3): counter ≥ 1, amount > 0, cum ≥ amount, and a
// counter-1 tag starts the chain (prev_hash = GENESIS(cert_id), cum = amount).
bool tag_valid(const Tag& tag);

// Every equivocation rule the pair breaks, in rule order R1, R2, R3. The pair
// is ordered so a.counter ≤ b.counter (ties by tag_hash), so the argument
// order doesn't matter. Tags of different certs never equivocate.
std::vector<Rule> rules_fired(const Tag& x, const Tag& y);

// The lowest-numbered rule the pair breaks (R2 and R3 can both hold), if any.
std::optional<Rule> equivocation(const Tag& x, const Tag& y);

// A PROOF for the pair, ordered as builders must order it, or none.
std::optional<Proof> make_proof(const Tag& x, const Tag& y);

// A PROOF is valid when both tags verify under holder_pub and break the named
// rule (in either order). Different cert_ids never break a rule.
bool verify_proof(const Proof& proof, const Bytes& holder_pub);

// C1–C6 (§8.2) ---------------------------------------------------------------

struct CheckResult {
  bool ok = true;
  std::string check;            // "C1".."C6" on failure
  std::string reason;           // machine token, e.g. "BAD_TAG_SIG", "SAME_COUNTER"
  std::optional<Rule> rule;     // when C6 found an equivocation
  std::optional<Tag> conflict;  // the stored tag it conflicts with
};

// Run C1–C6 in order on a scanned PAY; the first failure wins. `merchant` is
// this shop's own MCERT, `req` the open request it showed, `policy` the
// highest verified POLICY (or null), `stored_tags` every verified tag held.
CheckResult merchant_check(const Pay& pay, const Bytes& server_pub, const Mcert& merchant, const Req& req,
                           const Policy* policy, const std::vector<Tag>& stored_tags, std::int64_t now);

// R4 OVER_CAP (server) ----------------------------------------------------------

// The highest settled cum exceeds the highest cap of any issued version.
// `caps` must not be empty (std::invalid_argument).
bool over_cap(const std::vector<Tag>& settled_tags, const std::vector<std::int64_t>& caps);

// R5 MERCHANT_KNEW (server, §9.4) -------------------------------------------------

struct MerchantKnew {
  std::string clause;               // "HELD_IDS" (a) or "PAIRED_CONTACT" (b)
  Bytes conflict;                   // tag_hash of the conflicting tag x
  std::optional<Bytes> contact_id;  // for clause (b)
};

// Did merchant M (merchant_pub) knowingly accept tag z at t_accept?
// `cert_tags` are the tags held for z's cert; `logs` are verified DLOG entries
// from any devices. Clause (a) is checked before (b); conflicting tags are
// taken in (counter, tag_hash) order. A contact counts only when it is paired
// (both sides logged the same contact_id naming each other) and is dated by
// M's own CONTACT entry.
std::optional<MerchantKnew> merchant_knew(const Tag& z, const Bytes& merchant_pub, std::int64_t t_accept,
                                          const std::vector<Tag>& cert_tags, const std::vector<Dlog>& logs);

// R6 LOG_TAMPER (server, §9.5) ------------------------------------------------------

struct LogTamper {
  std::string kind;  // "FORK" or "BROKEN_LINK"
  std::int64_t seq;
};

// The first fork or broken link in one device's entries, by ascending seq.
// A missing seq is not tampering: a link is checked only where the previous
// entry is known (seq 1 against DGEN). Entries from more than one device
// throw std::invalid_argument.
std::optional<LogTamper> log_tamper(const std::vector<Dlog>& entries);

}  // namespace stormcash
