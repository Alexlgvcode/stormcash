#include "stormcash/rules.hpp"

#include <algorithm>
#include <map>
#include <stdexcept>
#include <utility>

namespace stormcash {
namespace {

// (counter, tag_hash): the order the spec uses for pairs and stored tags.
bool tag_order(const Tag& x, const Tag& y) {
  if (x.counter() != y.counter()) return x.counter() < y.counter();
  return x.tag_hash() < y.tag_hash();
}

// The pair ordered so a.counter ≤ b.counter, ties by tag_hash.
std::pair<const Tag&, const Tag&> ordered(const Tag& x, const Tag& y) {
  if (tag_order(y, x)) return {y, x};
  return {x, y};
}

bool contains(const std::vector<Bytes>& list, const Bytes& value) {
  return std::find(list.begin(), list.end(), value) != list.end();
}

CheckResult fail(std::string check, std::string reason) {
  CheckResult r;
  r.ok = false;
  r.check = std::move(check);
  r.reason = std::move(reason);
  return r;
}

}  // namespace

bool tag_valid(const Tag& tag) {
  if (tag.counter() < 1 || tag.amount_cents() <= 0 || tag.cum_cents() < tag.amount_cents()) return false;
  if (tag.counter() == 1) {
    return tag.prev_hash() == genesis(tag.cert_id()) && tag.cum_cents() == tag.amount_cents();
  }
  return true;
}

std::vector<Rule> rules_fired(const Tag& x, const Tag& y) {
  std::vector<Rule> fired;
  if (x.cert_id() != y.cert_id()) return fired;
  auto [a, b] = ordered(x, y);
  // R1 SAME_COUNTER: one counter signed for two different tags.
  if (a.counter() == b.counter() && a.tag_hash() != b.tag_hash()) fired.push_back(Rule::SameCounter);
  // R2 BROKEN_LINK: the next counter doesn't point back at this tag.
  if (b.counter() == a.counter() + 1 && b.prev_hash() != a.tag_hash()) fired.push_back(Rule::BrokenLink);
  // R3 TOTAL_BACKWARDS: the later tag's total before it is below the earlier total.
  if (b.counter() > a.counter() && b.cum_cents() - b.amount_cents() < a.cum_cents()) {
    fired.push_back(Rule::TotalBackwards);
  }
  return fired;
}

std::optional<Rule> equivocation(const Tag& x, const Tag& y) {
  auto fired = rules_fired(x, y);
  if (fired.empty()) return std::nullopt;
  return fired.front();
}

std::optional<Proof> make_proof(const Tag& x, const Tag& y) {
  auto rule = equivocation(x, y);
  if (!rule) return std::nullopt;
  auto [a, b] = ordered(x, y);
  return Proof{a, b, *rule};
}

bool verify_proof(const Proof& proof, const Bytes& holder_pub) {
  if (!proof.a.verify(holder_pub) || !proof.b.verify(holder_pub)) return false;
  auto fired = rules_fired(proof.a, proof.b);
  return std::find(fired.begin(), fired.end(), proof.rule) != fired.end();
}

CheckResult merchant_check(const Pay& pay, const Bytes& server_pub, const Mcert& merchant, const Req& req,
                           const Policy* policy, const std::vector<Tag>& stored_tags, std::int64_t now) {
  const Cert& cert = pay.cert;
  const Tag& tag = pay.tag;
  const Det& det = pay.det;

  // C1: certificate issued by StormCash.
  if (!cert.verify(server_pub)) return fail("C1", "BAD_CERT_SIG");

  // C2: not expired (10-minute clock tolerance) and not frozen.
  if (now > cert.expires_at() + kClockToleranceS) return fail("C2", "EXPIRED");
  if (policy != nullptr && policy->is_frozen(cert.cert_id())) return fail("C2", "FROZEN");

  // C3: the tag is for this certificate and signed by its holder.
  if (tag.cert_id() != cert.cert_id()) return fail("C3", "WRONG_CERT");
  if (!tag.verify(cert.holder_pub())) return fail("C3", "BAD_TAG_SIG");

  // C4: the payment answers this shop's open request (merchant's clock, no tolerance).
  if (tag.details_hash() != det.digest()) return fail("C4", "DETAILS_MISMATCH");
  if (det.merchant_pub() != merchant.merchant_pub()) return fail("C4", "WRONG_MERCHANT");
  if (det.nonce() != req.nonce()) return fail("C4", "WRONG_NONCE");
  if (tag.amount_cents() != req.amount_cents()) return fail("C4", "WRONG_AMOUNT");
  if (now > req.req_expires_at()) return fail("C4", "REQ_EXPIRED");

  // C5: amounts.
  if (tag.amount_cents() <= 0 || tag.cum_cents() < tag.amount_cents()) return fail("C5", "BAD_AMOUNT");
  if (tag.cum_cents() > cert.cap_cents()) return fail("C5", "OVER_CAP");
  if (policy != nullptr) {
    auto limit = policy->merchant_limit(merchant.merchant_id());
    if (limit && tag.amount_cents() > *limit) return fail("C5", "OVER_LIMIT");
  }

  // C6: chain checks against every stored tag for this cert.
  if (!tag_valid(tag)) return fail("C6", "INVALID_TAG");
  std::vector<Tag> same_cert;
  for (const Tag& s : stored_tags) {
    if (s.cert_id() == tag.cert_id()) same_cert.push_back(s);
  }
  std::sort(same_cert.begin(), same_cert.end(), tag_order);
  for (const Tag& stored : same_cert) {
    if (auto rule = equivocation(stored, tag)) {
      CheckResult r = fail("C6", std::string(rule_name(*rule)));
      r.rule = rule;
      r.conflict = stored;
      return r;
    }
  }
  // Not a conflict, but not new either (e.g. the same payment replayed).
  if (!same_cert.empty() && tag.counter() <= same_cert.back().counter()) return fail("C6", "COUNTER_NOT_NEW");

  return CheckResult{};
}

bool over_cap(const std::vector<Tag>& settled_tags, const std::vector<std::int64_t>& caps) {
  if (caps.empty()) throw std::invalid_argument("over_cap needs the caps of the issued versions");
  if (settled_tags.empty()) return false;
  std::int64_t top_cum = 0;
  for (const Tag& t : settled_tags) top_cum = std::max(top_cum, t.cum_cents());
  return top_cum > *std::max_element(caps.begin(), caps.end());
}

std::optional<MerchantKnew> merchant_knew(const Tag& z, const Bytes& merchant_pub, std::int64_t t_accept,
                                          const std::vector<Tag>& cert_tags, const std::vector<Dlog>& logs) {
  const Bytes& zh = z.tag_hash();
  std::vector<Tag> conflicts;
  for (const Tag& x : cert_tags) {
    if (x.cert_id() == z.cert_id() && x.tag_hash() != zh && equivocation(x, z)) conflicts.push_back(x);
  }
  if (conflicts.empty()) return std::nullopt;
  std::sort(conflicts.begin(), conflicts.end(), tag_order);

  // (a) M's own ACCEPT entry for z lists x in held_ids.
  for (const Tag& x : conflicts) {
    for (const Dlog& e : logs) {
      if (e.device_pub() == merchant_pub && e.kind() == "ACCEPT" && e.tag_hash() == zh &&
          contains(e.held_ids(), x.tag_hash())) {
        return MerchantKnew{"HELD_IDS", x.tag_hash(), std::nullopt};
      }
    }
  }

  // (b) a paired contact before t_accept in which x reached M.
  // M's own CONTACT entries by contact_id (a later entry with the same id wins).
  std::map<Bytes, const Dlog*> mine;
  for (const Dlog& e : logs) {
    if (e.device_pub() == merchant_pub && e.kind() == "CONTACT") mine[e.contact_id()] = &e;
  }
  // (own, peer): the peer logged a contact naming M, M logged the same
  // contact_id naming the peer, and M's entry is dated before t_accept.
  std::vector<std::pair<const Dlog*, const Dlog*>> pairs;
  for (const Dlog& peer : logs) {
    if (peer.kind() != "CONTACT" || peer.peer_pub() != merchant_pub) continue;
    auto it = mine.find(peer.contact_id());
    if (it == mine.end()) continue;
    const Dlog* own = it->second;
    if (own->peer_pub() != peer.device_pub() || own->ts() >= t_accept) continue;
    pairs.emplace_back(own, &peer);
  }
  // Earliest contact first (M's clock), ties by contact_id; stable like the reference.
  std::stable_sort(pairs.begin(), pairs.end(), [](const auto& p, const auto& q) {
    if (p.first->ts() != q.first->ts()) return p.first->ts() < q.first->ts();
    return p.first->contact_id() < q.first->contact_id();
  });
  for (const Tag& x : conflicts) {
    Bytes x8 = id8(x.tag_hash());
    for (const auto& [own, peer] : pairs) {
      if (contains(peer->sent_ids(), x8) || contains(own->recv_ids(), x8)) {
        return MerchantKnew{"PAIRED_CONTACT", x.tag_hash(), own->contact_id()};
      }
    }
  }
  return std::nullopt;
}

std::optional<LogTamper> log_tamper(const std::vector<Dlog>& entries) {
  if (entries.empty()) return std::nullopt;
  const Bytes& device_pub = entries.front().device_pub();
  // seq -> entry_hash -> entry; identical copies of one entry collapse.
  std::map<std::int64_t, std::map<Bytes, const Dlog*>> by_seq;
  for (const Dlog& e : entries) {
    if (e.device_pub() != device_pub) throw std::invalid_argument("log_tamper checks one device at a time");
    by_seq[e.seq()][e.entry_hash()] = &e;
  }

  for (const auto& [seq, here] : by_seq) {
    // A fork at a seq is reported before a broken link at it.
    if (here.size() > 1) return LogTamper{"FORK", seq};
    const Dlog& entry = *here.begin()->second;
    if (seq == 1) {
      if (entry.prev_hash() != dlog_genesis(device_pub)) return LogTamper{"BROKEN_LINK", seq};
      continue;
    }
    auto prev = by_seq.find(seq - 1);
    if (prev != by_seq.end() && !prev->second.count(entry.prev_hash())) return LogTamper{"BROKEN_LINK", seq};
  }
  return std::nullopt;
}

}  // namespace stormcash
