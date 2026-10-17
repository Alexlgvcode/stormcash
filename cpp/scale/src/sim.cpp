#include "scale/sim.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <utility>

#include "scale/city.hpp"
#include "scale/rng.hpp"

namespace scale {
namespace {

// Constants from sim/stormcash_sim/engine.py.
constexpr int kCapCents = 2000;       // always-on cap
constexpr int kStormCapCents = 5000;  // Storm Mode cap
constexpr int kMinPaymentCents = 300;
constexpr double kContactRange = 2.0;  // phones within 2 cells of each other meet
constexpr int kDayStartMin = 7 * 60;   // trips between 07:00 and 21:00 local
constexpr int kDayEndMin = 21 * 60;

// prev links of special tags. Payment ids are ≥ 0, so neither ever equals one.
constexpr std::int64_t kGenesis = -1;   // counter 1 links to GENESIS(cert_id)
constexpr std::int64_t kFakePrev = -2;  // a "skip" re-spend links to nothing real

// A spend tag without cryptography (§7.4 TAG): what the rules look at.
struct Tag {
  std::int32_t cert;  // resident index; each adopter has one cert
  std::int32_t counter;
  std::int64_t prev;  // id of the payment this tag links to, or kGenesis / kFakePrev
  std::int32_t amount;
  std::int32_t cum;
  std::uint64_t order;  // random; stands in for tag_hash where the spec breaks ties by it
};

struct Payment {
  Tag tag;
  std::int32_t shop;
  std::int32_t tick;  // when the shop ran its checks
  bool accepted;
  bool cheater;  // on a double spender's cert: the only certs whose tags can conflict
  std::int32_t server_tick = -1;
  bool in_case = false;  // the server opened a case naming this tag
};

// R1–R3 (§8.3) on two tags of payments `xi` and `yi`; the pair is ordered so
// a.counter ≤ b.counter, ties by `order`. Any rule firing is a conflict.
bool equivocates(const Tag& x, std::int64_t xi, const Tag& y, std::int64_t yi) {
  if (x.cert != y.cert || xi == yi) return false;
  bool x_first = x.counter < y.counter || (x.counter == y.counter && x.order <= y.order);
  const Tag& a = x_first ? x : y;
  const Tag& b = x_first ? y : x;
  const std::int64_t a_id = x_first ? xi : yi;
  if (a.counter == b.counter) return true;                             // R1 SAME_COUNTER
  if (b.counter == a.counter + 1 && b.prev != a_id) return true;       // R2 BROKEN_LINK
  if (b.counter > a.counter && b.cum - b.amount < a.cum) return true;  // R3 TOTAL_BACKWARDS
  return false;
}

// An item a phone carries. Every item that matters here is a PAY: see README
// ("What the model leaves out") for why TAG copies, DLOG entries and PROOF
// items can't change any metric.
struct Carried {
  std::uint32_t payment;
  std::uint16_t hops;  // carriers after the shop: len(path) − 1 at upload (§10.2)
};

struct Device {
  std::vector<Carried> carry;  // sorted by payment id
  int policy_ver = 0;          // highest POLICY version this phone has (0 = none)
  double p_uplink_minute = 0.0;
  bool gossip = true;
};

struct Shop {
  Device dev;
  int x = 0, y = 0;
  std::vector<int> neighbors;  // shops within 2 cells, itself included, by index
  std::vector<int> present;    // residents here now, in arrival order
  // Stored tags for C6, kept apart from what the shop carries to relay. Only
  // double spenders' certs: an honest chain can't fail C6 (§8.2).
  std::unordered_map<int, std::vector<std::uint32_t>> cheater_tags;
};

struct Wallet {
  std::int32_t counter = 0;
  std::int64_t head = kGenesis;
  std::int32_t cum = 0;
};

struct Armed {  // a planned re-spend (engine.py: Resident.armed)
  Wallet snapshot;
  int countdown;
  std::int32_t amount;
};

struct Resident {
  Device dev;
  int x = 0, y = 0;  // home: every trip starts here
  bool storm = false;
  int cap = kCapCents;
  bool cheater = false;
  bool reuse = true;  // re-spend mode: reuse the counter (R1) or skip one (R3)
  int cheats_left = 0;
  Wallet wallet;
  std::optional<Armed> armed;
  int at_shop = -1;
  std::vector<std::pair<int, int>> recent;  // (partner device, tick) of syncs this resident started
};

enum class EventKind : std::uint8_t { kTrip, kArrive, kLeave };
struct Event {
  EventKind kind;
  std::int32_t resident;
  std::int32_t shop;
};

struct Attempt {
  std::uint32_t payment;
  bool reuse;
  std::string refused;  // failed check, or empty if the shop accepted it
};

class Sim {
 public:
  Sim(const Params& p, std::uint64_t seed) : p_(p), seed_(seed), rng_(derive_seed(seed, 1)) {}

  ReplicateResult run() {
    auto started = std::chrono::steady_clock::now();
    setup();
    for (int t = 0; t < ticks_; ++t) {
      if (t == storm_tick_) storm();
      // Events first (trips, arrivals, departures), then meetings, then
      // uploads: the same phases, in the same order, as engine.py's loop.
      for (std::size_t i = 0; i < events_[static_cast<std::size_t>(t)].size(); ++i) {
        handle(events_[static_cast<std::size_t>(t)][i], t);
      }
      events_[static_cast<std::size_t>(t)].clear();
      events_[static_cast<std::size_t>(t)].shrink_to_fit();
      meet(t);
      uplinks(t);
    }
    ReplicateResult r = summarize();
    r.wall_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    return r;
  }

 private:
  // Setup ---------------------------------------------------------------------------

  void setup() {
    ticks_ = p_.hours * 60;
    storm_tick_ = static_cast<int>(p_.storm_at_h * 60);
    events_.assign(static_cast<std::size_t>(ticks_), {});
    uplink_due_.assign(static_cast<std::size_t>(ticks_), {});

    Rng layout(derive_seed(seed_, 0));
    City city = build_city(p_, layout);
    width_ = city.width;
    height_ = city.height;

    for (const ShopSpec& spec : city.shops) {
      Shop s;
      s.x = spec.x;
      s.y = spec.y;
      s.dev.p_uplink_minute = per_minute(spec.uplink_per_hour);
      shops_.push_back(std::move(s));
    }
    index_shops();

    for (const ResidentSpec& spec : city.residents) {
      if (!rng_.chance(p_.adoption)) continue;  // only adopters are modelled (§16.2)
      Resident r;
      r.x = spec.x;
      r.y = spec.y;
      r.storm = rng_.chance(p_.storm_share);
      r.dev.p_uplink_minute = per_minute(p_.p_uplink);
      residents_.push_back(std::move(r));
    }
    plant_cheaters();

    for (std::size_t i = 0; i < residents_.size(); ++i) {
      push(next_trip(0), {EventKind::kTrip, static_cast<std::int32_t>(i), -1});
    }
    for (int d = 0; d < device_count(); ++d) schedule_uplink(d, -1);
    payments_.reserve(residents_.size() * 6);
  }

  static double per_minute(double per_hour) { return 1.0 - std::pow(1.0 - per_hour, 1.0 / 60.0); }

  // Neighbour lists (shops within 2 cells) and a coarse grid for trip choice.
  void index_shops() {
    std::unordered_map<long long, int> at;
    for (std::size_t i = 0; i < shops_.size(); ++i) at[cell(shops_[i].x, shops_[i].y)] = static_cast<int>(i);
    for (Shop& s : shops_) {
      for (int dy = -2; dy <= 2; ++dy) {
        for (int dx = -2; dx <= 2; ++dx) {
          auto it = at.find(cell(s.x + dx, s.y + dy));
          if (it != at.end() && distance(s.x, s.y, s.x + dx, s.y + dy) <= kContactRange) {
            s.neighbors.push_back(it->second);
          }
        }
      }
      std::sort(s.neighbors.begin(), s.neighbors.end());
    }
    blocks_x_ = (width_ + kBlock - 1) / kBlock;
    blocks_y_ = (height_ + kBlock - 1) / kBlock;
    blocks_.assign(static_cast<std::size_t>(blocks_x_ * blocks_y_), {});
    for (std::size_t i = 0; i < shops_.size(); ++i) {
      blocks_[static_cast<std::size_t>((shops_[i].y / kBlock) * blocks_x_ + shops_[i].x / kBlock)].push_back(
          static_cast<int>(i));
    }
  }

  // Key of cell (x, y). The row stride is padded by 8 so the neighbour lookup's
  // off-grid cells (x from -2 to width + 1) can never alias a real cell.
  long long cell(int x, int y) const { return static_cast<long long>(y) * (width_ + 8) + x; }

  // §16.4 double_spender (organic): chosen at random among adopters, always
  // in Storm Mode, phone relays nothing, rolls back up to `cheats_per_cheater`
  // times; half reuse a counter, half skip one.
  void plant_cheaters() {
    int n = static_cast<int>(residents_.size());
    int k = p_.cheaters >= 0 ? std::min(p_.cheaters, n) : static_cast<int>(std::lround(p_.cheater_share * n));
    Rng pick(derive_seed(seed_, 2));
    std::vector<int> order(static_cast<std::size_t>(n));
    for (int i = 0; i < n; ++i) order[static_cast<std::size_t>(i)] = i;
    for (int i = 0; i < k; ++i) {  // partial Fisher-Yates
      int j = i + static_cast<int>(pick.below(static_cast<std::uint64_t>(n - i)));
      std::swap(order[static_cast<std::size_t>(i)], order[static_cast<std::size_t>(j)]);
      Resident& r = residents_[static_cast<std::size_t>(order[static_cast<std::size_t>(i)])];
      r.cheater = true;
      r.storm = true;
      r.dev.gossip = false;
      r.cheats_left = p_.cheats_per_cheater;
      r.reuse = order[static_cast<std::size_t>(i)] % 2 == 0;
    }
    cheaters_ = k;
  }

  // Devices are numbered like engine.py's: shops first, then residents.
  int device_count() const { return static_cast<int>(shops_.size() + residents_.size()); }
  Device& device(int d) {
    return d < static_cast<int>(shops_.size()) ? shops_[static_cast<std::size_t>(d)].dev
                                               : residents_[static_cast<std::size_t>(d) - shops_.size()].dev;
  }
  Shop* shop_of(int d) { return d < static_cast<int>(shops_.size()) ? &shops_[static_cast<std::size_t>(d)] : nullptr; }
  int resident_device(int r) const { return static_cast<int>(shops_.size()) + r; }

  // Events -----------------------------------------------------------------------------

  void push(int tick, Event e) {
    if (tick < ticks_) events_[static_cast<std::size_t>(tick)].push_back(e);
  }

  int next_trip(int tick) {
    int t = tick + std::max(1, static_cast<int>(rng_.exponential(p_.trip_every_min)));
    int minute = (p_.start_local_minute + t) % 1440;
    if (minute < kDayStartMin) {
      t += kDayStartMin - minute + static_cast<int>(rng_.below(120));
    } else if (minute >= kDayEndMin) {
      t += 1440 - minute + kDayStartMin + static_cast<int>(rng_.below(120));
    }
    return t;
  }

  void storm() {
    for (Resident& r : residents_) {
      if (r.storm) r.cap = kStormCapCents;
    }
  }

  void handle(const Event& e, int t) {
    Resident& r = residents_[static_cast<std::size_t>(e.resident)];
    switch (e.kind) {
      case EventKind::kTrip: {
        int shop = choose_shop(r);
        const Shop& s = shops_[static_cast<std::size_t>(shop)];
        int travel = std::max(2, static_cast<int>(std::ceil(distance(r.x, r.y, s.x, s.y) / 0.5)));
        r.at_shop = -1;
        push(t + travel, {EventKind::kArrive, e.resident, shop});
        break;
      }
      case EventKind::kArrive: {
        r.at_shop = e.shop;
        shops_[static_cast<std::size_t>(e.shop)].present.push_back(e.resident);
        visit(e.resident, e.shop, t);
        push(t + static_cast<int>(rng_.randint(5, 12)), {EventKind::kLeave, e.resident, e.shop});
        break;
      }
      case EventKind::kLeave: {
        auto& here = shops_[static_cast<std::size_t>(r.at_shop)].present;
        here.erase(std::find(here.begin(), here.end(), e.resident));
        r.at_shop = -1;
        push(next_trip(t), {EventKind::kTrip, e.resident, -1});
        break;
      }
    }
  }

  // A shop within trip_radius of home, weighted 1 / (1 + d)^2 (engine.py: trip).
  int choose_shop(const Resident& r) {
    candidates_.clear();
    cumulative_.clear();
    const double radius = p_.trip_radius;
    int bx0 = std::max(0, static_cast<int>((r.x - radius) / kBlock));
    int bx1 = std::min(blocks_x_ - 1, static_cast<int>((r.x + radius) / kBlock));
    int by0 = std::max(0, static_cast<int>((r.y - radius) / kBlock));
    int by1 = std::min(blocks_y_ - 1, static_cast<int>((r.y + radius) / kBlock));
    double total = 0.0;
    for (int by = by0; by <= by1; ++by) {
      for (int bx = bx0; bx <= bx1; ++bx) {
        for (int i : blocks_[static_cast<std::size_t>(by * blocks_x_ + bx)]) {
          const Shop& s = shops_[static_cast<std::size_t>(i)];
          double d = distance(r.x, r.y, s.x, s.y);
          if (d > radius) continue;
          total += 1.0 / ((1.0 + d) * (1.0 + d));
          candidates_.push_back(i);
          cumulative_.push_back(total);
        }
      }
    }
    // With a small radius, a home at the city's edge can have no shop in
    // reach: then the resident goes to the nearest shop (no draw needed).
    if (candidates_.empty()) return nearest_shop(r);
    double u = rng_.uniform() * total;
    auto it = std::upper_bound(cumulative_.begin(), cumulative_.end(), u);
    if (it == cumulative_.end()) --it;  // u == total after rounding
    return candidates_[static_cast<std::size_t>(it - cumulative_.begin())];
  }

  int nearest_shop(const Resident& r) const {
    int best = 0;
    double best_d = std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < shops_.size(); ++i) {
      double d = distance(r.x, r.y, shops_[i].x, shops_[i].y);
      if (d < best_d) {
        best_d = d;
        best = static_cast<int>(i);
      }
    }
    return best;
  }

  // Payments ---------------------------------------------------------------------------

  // A resident at a shop pays; an armed double spender re-spends instead
  // (engine.py: visit). Arming needs a payment made under the Storm Mode cap.
  void visit(int ri, int shop, int t) {
    Resident& r = residents_[static_cast<std::size_t>(ri)];
    if (r.armed) {
      if (--r.armed->countdown <= 0) {
        Armed armed = *r.armed;
        r.armed.reset();
        respend(ri, shop, t, armed);
        return;
      }
    }
    Wallet before = r.wallet;
    auto paid = pay(ri, shop, t);
    // As in engine.py, this doesn't check for a plan already pending: a
    // payment made while armed re-arms (replacing the plan) if cheats are left.
    if (paid && r.cheats_left > 0 && r.cap == kStormCapCents) {
      --r.cheats_left;
      r.armed = Armed{before, static_cast<int>(rng_.randint(1, 3)), payments_[*paid].tag.amount};
    }
  }

  std::optional<std::uint32_t> pay(int ri, int shop, int t) {
    Resident& r = residents_[static_cast<std::size_t>(ri)];
    // $3–$45, log-normal around $12; round() in Python rounds half to even, as nearbyint does.
    double dollars = std::min(45.0, std::max(3.0, rng_.lognormal(std::log(12.0), 0.6)));
    int amount = std::min(static_cast<int>(std::nearbyint(dollars * 100)), r.cap - r.wallet.cum);
    if (amount < kMinPaymentCents) {
      ++out_of_money_;
      return std::nullopt;
    }
    Tag tag{ri, r.wallet.counter + 1, r.wallet.head, amount, r.wallet.cum + amount, rng_.next()};
    std::uint32_t id = new_payment(tag, shop, t, r.cheater);
    r.wallet = {tag.counter, id, tag.cum};  // the wallet moves on whether or not the shop accepts
    shop_checks(id);
    return id;
  }

  // Spend money a rolled-back wallet already spent (engine.py: respend).
  // reuse: the snapshot's next counter again, so R1 with the first payment.
  // skip: two counters past the current one with the old total, so R3.
  void respend(int ri, int shop, int t, const Armed& armed) {
    Resident& r = residents_[static_cast<std::size_t>(ri)];
    const Wallet& snap = armed.snapshot;
    Tag tag = r.reuse ? Tag{ri, snap.counter + 1, snap.head, armed.amount, snap.cum + armed.amount, rng_.next()}
                      : Tag{ri, r.wallet.counter + 2, kFakePrev, armed.amount, snap.cum + armed.amount, rng_.next()};
    std::uint32_t id = new_payment(tag, shop, t, r.cheater);
    r.wallet = {tag.counter, id, tag.cum};  // the rolled-back wallet carries on from here
    std::string refused = shop_checks(id);
    attempts_.push_back({id, r.reuse, refused});
  }

  std::uint32_t new_payment(const Tag& tag, int shop, int t, bool cheater) {
    payments_.push_back(Payment{tag, shop, t, false, cheater});
    return static_cast<std::uint32_t>(payments_.size() - 1);
  }

  // The checks that can fail for these payments (§8.2): C2 when the shop has a
  // POLICY freezing the cert, C6 against the shop's stored tags of the cert.
  // C1, C3, C4 and C5 always pass for well-formed payments in this model.
  // Returns the failed check, or "" if the shop accepts. Either way the shop
  // keeps the PAY (refused ones as evidence) and stores its tag.
  std::string shop_checks(std::uint32_t id) {
    Payment& pm = payments_[id];
    Shop& s = shops_[static_cast<std::size_t>(pm.shop)];
    std::string refused;
    int frozen_at = freeze_ver_.count(pm.tag.cert) ? freeze_ver_[pm.tag.cert] : 0;
    if (frozen_at > 0 && frozen_at <= s.dev.policy_ver) {
      refused = "C2";
    } else if (pm.cheater) {
      int highest = 0;
      for (std::uint32_t x : s.cheater_tags[pm.tag.cert]) {
        const Tag& stored = payments_[x].tag;
        if (equivocates(stored, x, pm.tag, id)) refused = "C6";
        highest = std::max(highest, stored.counter);
      }
      if (refused.empty() && highest > 0 && pm.tag.counter <= highest) refused = "C6";  // COUNTER_NOT_NEW
    }
    ++payments_checked_;
    pm.accepted = refused.empty();
    if (pm.accepted) {
      ++accepted_;
    } else {
      ++refused_;
      ++refused_by_check_[refused];
    }
    s.dev.carry.push_back({id, 0});  // the newest payment: push_back keeps carry sorted
    learn(s, id);
    return refused;
  }

  void learn(Shop& s, std::uint32_t id) {
    const Payment& pm = payments_[id];
    if (!pm.cheater) return;
    auto& tags = s.cheater_tags[pm.tag.cert];
    if (std::find(tags.begin(), tags.end(), id) == tags.end()) tags.push_back(id);
  }

  // Gossip ------------------------------------------------------------------------------

  // Phones within 2 cells at the same minute may sync: each resident at a
  // shop with every shop within 2 cells and every resident at those shops,
  // at most once an hour per pair, with probability p_link (engine.py: meet).
  void meet(int t) {
    for (std::size_t si = 0; si < shops_.size(); ++si) {
      const Shop& s = shops_[si];
      if (s.present.empty()) continue;
      nearby_.clear();
      for (int n : s.neighbors) {
        const auto& there = shops_[static_cast<std::size_t>(n)].present;
        nearby_.insert(nearby_.end(), there.begin(), there.end());
      }
      here_.assign(s.present.begin(), s.present.end());
      for (int r : here_) {
        if (!residents_[static_cast<std::size_t>(r)].dev.gossip) continue;  // a cheater's phone relays nothing
        for (int n : s.neighbors) try_sync(r, n, t);
        for (int o : nearby_) {
          // Each resident pair once per minute, from the lower-numbered side.
          if (o > r && residents_[static_cast<std::size_t>(o)].dev.gossip) try_sync(r, resident_device(o), t);
        }
      }
    }
  }

  void try_sync(int r, int partner, int t) {
    auto& recent = residents_[static_cast<std::size_t>(r)].recent;
    std::erase_if(recent, [&](const auto& e) { return t - e.second >= p_.pair_cooldown_min; });
    for (const auto& e : recent) {
      if (e.first == partner) return;
    }
    if (!rng_.chance(p_.p_link)) return;
    recent.emplace_back(partner, t);
    sync(resident_device(r), partner, t);
  }

  // One sync session (§10.3): drop what the server has had for an hour, then
  // each side gets every item the other has and it lacks, one hop further.
  void sync(int a_id, int b_id, int t) {
    Device& a = device(a_id);
    Device& b = device(b_id);
    Shop* a_shop = shop_of(a_id);
    Shop* b_shop = shop_of(b_id);
    out_a_.clear();
    out_b_.clear();
    std::size_t i = 0, j = 0;
    auto stale = [&](const Carried& c) {
      int at = payments_[c.payment].server_tick;
      return at >= 0 && t - at >= p_.carry_after_server_min;
    };
    while (i < a.carry.size() || j < b.carry.size()) {
      if (i < a.carry.size() && stale(a.carry[i])) {
        ++i;
      } else if (j < b.carry.size() && stale(b.carry[j])) {
        ++j;
      } else if (j == b.carry.size() || (i < a.carry.size() && a.carry[i].payment < b.carry[j].payment)) {
        out_a_.push_back(a.carry[i]);
        out_b_.push_back({a.carry[i].payment, static_cast<std::uint16_t>(a.carry[i].hops + 1)});
        if (b_shop) learn(*b_shop, a.carry[i].payment);
        ++i;
      } else if (i == a.carry.size() || b.carry[j].payment < a.carry[i].payment) {
        out_b_.push_back(b.carry[j]);
        out_a_.push_back({b.carry[j].payment, static_cast<std::uint16_t>(b.carry[j].hops + 1)});
        if (a_shop) learn(*a_shop, b.carry[j].payment);
        ++j;
      } else {  // both hold it: each keeps its own copy (and path)
        out_a_.push_back(a.carry[i++]);
        out_b_.push_back(b.carry[j++]);
      }
    }
    a.carry.swap(out_a_);
    b.carry.swap(out_b_);
    a.policy_ver = b.policy_ver = std::max(a.policy_ver, b.policy_ver);  // the higher POLICY wins
    ++contacts_;
  }

  // Uplink and settlement ----------------------------------------------------------------

  void schedule_uplink(int d, int after) {
    std::int64_t gap = rng_.geometric(device(d).p_uplink_minute);
    std::int64_t at = static_cast<std::int64_t>(after) + gap;
    if (at < ticks_) uplink_due_[static_cast<std::size_t>(at)].push_back(d);
  }

  // Phones that got internet this minute upload, in device order (engine.py
  // draws for every device every minute; a geometric gap is the same process).
  void uplinks(int t) {
    auto& due = uplink_due_[static_cast<std::size_t>(t)];
    std::sort(due.begin(), due.end());
    for (int d : due) {
      upload(d, t);
      schedule_uplink(d, t);
    }
    due.clear();
    due.shrink_to_fit();
  }

  // POST everything the server hasn't received (§10.5). The uploader drops
  // what it sent; other carriers drop it an hour later, at their next sync.
  void upload(int d, int t) {
    Device& dev = device(d);
    std::size_t sent = 0;
    std::size_t keep = 0;
    for (std::size_t i = 0; i < dev.carry.size(); ++i) {
      if (payments_[dev.carry[i].payment].server_tick < 0) {
        receive(dev.carry[i], t);
        ++sent;
      } else {
        dev.carry[keep++] = dev.carry[i];
      }
    }
    // The response carries the latest POLICY. See Params::policy_on_every_uplink
    // for why a phone with nothing to send still gets it by default.
    if (sent > 0 || p_.policy_on_every_uplink) dev.policy_ver = std::max(dev.policy_ver, policy_ver_);
    if (sent == 0) return;
    dev.carry.resize(keep);
    ++uploads_;
    items_uploaded_ += static_cast<long long>(sent);
  }

  // The server ingests one PAY (settlement.py: handle_pay): store the tag and
  // open a case with the first stored tag it conflicts with (in counter, hash
  // order), freezing the cert; then pay an accepted payment from escrow
  // first and the guarantee pool for the rest.
  void receive(const Carried& c, int t) {
    Payment& pm = payments_[c.payment];
    pm.server_tick = t;
    ++hops_[c.hops];
    if (pm.cheater) {
      auto& stored = server_tags_[pm.tag.cert];
      for (std::uint32_t x : stored) {
        if (equivocates(payments_[x].tag, x, pm.tag, c.payment)) {
          pm.in_case = payments_[x].in_case = true;
          if (!freeze_ver_.count(pm.tag.cert)) freeze_ver_[pm.tag.cert] = ++policy_ver_;
          break;
        }
      }
      auto pos = std::upper_bound(stored.begin(), stored.end(), c.payment, [&](std::uint32_t a, std::uint32_t b) {
        const Tag& ta = payments_[a].tag;
        const Tag& tb = payments_[b].tag;
        return ta.counter != tb.counter ? ta.counter < tb.counter : ta.order < tb.order;
      });
      stored.insert(pos, c.payment);
    }
    if (!pm.accepted) return;  // refused offline, uploaded as evidence: never paid
    ++settled_;
    const Resident& r = residents_[static_cast<std::size_t>(pm.tag.cert)];
    int escrow = (r.storm && t >= storm_tick_) ? kStormCapCents : kCapCents;  // highest cap issued so far
    int& paid = escrow_paid_[pm.tag.cert];
    int from_escrow = std::min(pm.tag.amount, std::max(0, escrow - paid));
    paid += from_escrow;
    if (pm.cheater) pool_loss_ += pm.tag.amount - from_escrow;
  }

  // Results --------------------------------------------------------------------------------

  ReplicateResult summarize() const {
    ReplicateResult out;
    out.seed = seed_;
    out.shops = static_cast<int>(shops_.size());
    out.adopters = static_cast<int>(residents_.size());
    out.cheaters = cheaters_;
    out.payments = payments_checked_;
    out.accepted = accepted_;
    out.refused = refused_;
    out.refused_by_check = refused_by_check_;
    out.out_of_money = out_of_money_;
    out.contacts = contacts_;
    out.uploads = uploads_;
    out.items_uploaded = items_uploaded_;
    out.attempts = static_cast<int>(attempts_.size());
    for (const Attempt& a : attempts_) {
      ++out.by_mode[a.reuse ? "reuse" : "skip"];
      if (!a.refused.empty()) {
        ++out.refused_offline;
        ++out.refusals_by_check[a.refused];
      } else {
        ++out.accepted_offline;
        if (payments_[a.payment].in_case) ++out.caught_at_settlement;
      }
    }
    out.pool_loss_cents = pool_loss_;
    out.settled = settled_;
    out.hops_histogram = hops_;

    std::vector<double> hours;
    for (const Payment& pm : payments_) {
      if (pm.accepted && pm.server_tick >= 0) hours.push_back((pm.server_tick - pm.tick) / 60.0);
    }
    if (!hours.empty()) {
      std::sort(hours.begin(), hours.end());
      std::size_t n = hours.size();
      out.median_hours_to_settlement = n % 2 ? hours[n / 2] : (hours[n / 2 - 1] + hours[n / 2]) / 2.0;
    }
    return out;
  }

  static constexpr int kBlock = 10;  // cells per side of a trip-choice grid block

  const Params p_;
  const std::uint64_t seed_;
  Rng rng_;
  int ticks_ = 0;
  int storm_tick_ = 0;
  int width_ = 0, height_ = 0;
  int blocks_x_ = 0, blocks_y_ = 0;
  std::vector<std::vector<int>> blocks_;
  std::vector<Shop> shops_;
  std::vector<Resident> residents_;
  int cheaters_ = 0;
  std::vector<std::vector<Event>> events_;    // by tick
  std::vector<std::vector<int>> uplink_due_;  // devices that get internet, by tick
  std::vector<Payment> payments_;             // payment id = index
  std::vector<Attempt> attempts_;

  // Server state.
  std::unordered_map<int, std::vector<std::uint32_t>> server_tags_;  // cheaters' certs, (counter, order) order
  std::unordered_map<int, int> freeze_ver_;                          // cert -> POLICY version that froze it
  std::unordered_map<int, int> escrow_paid_;
  int policy_ver_ = 0;

  long long payments_checked_ = 0, accepted_ = 0, refused_ = 0, out_of_money_ = 0;
  long long contacts_ = 0, uploads_ = 0, items_uploaded_ = 0, settled_ = 0, pool_loss_ = 0;
  std::map<int, long long> hops_;
  std::map<std::string, long long> refused_by_check_;

  // Scratch buffers, reused to avoid allocating every minute.
  std::vector<int> candidates_, nearby_, here_;
  std::vector<double> cumulative_;
  std::vector<Carried> out_a_, out_b_;
};

}  // namespace

std::optional<double> ReplicateResult::share_refused_offline() const {
  if (attempts == 0) return std::nullopt;
  return static_cast<double>(refused_offline) / attempts;
}

std::optional<double> ReplicateResult::share_caught_at_settlement() const {
  if (attempts == 0) return std::nullopt;
  return static_cast<double>(caught_at_settlement) / attempts;
}

std::optional<double> ReplicateResult::mean_loss_per_cheater_cents() const {
  if (cheaters == 0) return std::nullopt;
  return static_cast<double>(pool_loss_cents) / cheaters;
}

ReplicateResult run_replicate(const Params& params, std::uint64_t seed) { return Sim(params, seed).run(); }

}  // namespace scale
