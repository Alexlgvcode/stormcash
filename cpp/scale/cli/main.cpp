// stormcash-scale: the Scale Lab, a city-scale simulation of StormCash gossip.
//
//   stormcash-scale run   [options] [--out FILE]
//   stormcash-scale sweep --axis NAME=V1,V2,... [options] [--out FILE]
//
// Everything it prints or writes is SIMULATED.
#include <sys/utsname.h>

#include <chrono>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef __APPLE__
#include <sys/sysctl.h>
#endif

#include "scale/params.hpp"
#include "scale/runner.hpp"
#include "scale/stats.hpp"

namespace {

constexpr const char* kUsage =
    R"(stormcash-scale: Scale Lab, a city-scale StormCash gossip simulator (results are SIMULATED)

usage:
  stormcash-scale run   [options]
  stormcash-scale sweep --axis NAME=V1,V2,... [options]

options:
  --residents N      city size: about N/400 town tiles (40x24 cells, 38 shops each)
  --towns X Y        explicit tiles (with --residents for the head count)
  --set NAME=VALUE   any parameter (repeatable): adoption, p_link, p_uplink, cheaters,
                     cheater_share, hours, shelter_uplink, trip_radius, start_local_minute, ...
  --replicates R     Monte Carlo replicates per point (default 20)
  --threads T        worker threads (default: all cores)
  --seed S           base seed (default 1); replicate i uses derive_seed(S, i)
  --label TEXT       stored in the output
  --out FILE         write JSON here (default: stdout summary only)
)";

std::string machine_cpu() {
#ifdef __APPLE__
  char buf[256] = {};
  std::size_t len = sizeof(buf);
  if (sysctlbyname("machdep.cpu.brand_string", buf, &len, nullptr, 0) == 0) return buf;
#else
  std::ifstream in("/proc/cpuinfo");
  std::string line;
  while (std::getline(in, line)) {
    if (line.rfind("model name", 0) == 0) return line.substr(line.find(':') + 2);
  }
#endif
  return "unknown";
}

scale::Json machine_json() {
  utsname u{};
  uname(&u);
  return {{"cpu", machine_cpu()},
          {"logical_cpus", std::thread::hardware_concurrency()},
          {"os", std::string(u.sysname) + " " + u.release + " " + u.machine}};
}

struct Options {
  scale::Params base;
  int residents = -1;
  int towns_x = -1, towns_y = -1;
  int replicates = 20;
  unsigned threads = std::thread::hardware_concurrency();
  std::uint64_t seed = 1;
  std::string label;
  std::string out;
  std::string axis_name;
  std::vector<std::string> axis_values;
};

std::vector<std::string> split(const std::string& s, char sep) {
  std::vector<std::string> out;
  std::stringstream in(s);
  std::string item;
  while (std::getline(in, item, sep)) out.push_back(item);
  return out;
}

Options parse(const std::vector<std::string>& args, bool sweep) {
  Options o;
  for (std::size_t i = 0; i < args.size(); ++i) {
    auto need = [&](std::size_t n) {
      if (i + n >= args.size()) throw std::invalid_argument(args[i] + " needs a value");
    };
    const std::string& a = args[i];
    if (a == "--residents") {
      need(1);
      o.residents = std::stoi(args[++i]);
    } else if (a == "--towns") {
      need(2);
      o.towns_x = std::stoi(args[++i]);
      o.towns_y = std::stoi(args[++i]);
    } else if (a == "--set") {
      need(1);
      auto kv = split(args[++i], '=');
      if (kv.size() != 2) throw std::invalid_argument("--set wants NAME=VALUE");
      scale::set_param(o.base, kv[0], kv[1]);
    } else if (a == "--replicates") {
      need(1);
      o.replicates = std::stoi(args[++i]);
    } else if (a == "--threads") {
      need(1);
      o.threads = static_cast<unsigned>(std::stoul(args[++i]));
    } else if (a == "--seed") {
      need(1);
      o.seed = std::stoull(args[++i]);
    } else if (a == "--label") {
      need(1);
      o.label = args[++i];
    } else if (a == "--out") {
      need(1);
      o.out = args[++i];
    } else if (a == "--axis" && sweep) {
      need(1);
      auto kv = split(args[++i], '=');
      if (kv.size() != 2) throw std::invalid_argument("--axis wants NAME=V1,V2,...");
      o.axis_name = kv[0];
      o.axis_values = split(kv[1], ',');
    } else {
      throw std::invalid_argument("unknown option " + a);
    }
  }
  if (o.towns_x > 0) {
    o.base.towns_x = o.towns_x;
    o.base.towns_y = o.towns_y;
    o.base.residents = o.residents > 0 ? o.residents : 400 * o.base.towns();
  } else if (o.residents > 0) {
    scale::size_city_for(o.base, o.residents);
  }
  if (sweep && o.axis_values.empty()) throw std::invalid_argument("sweep needs --axis NAME=V1,V2,...");
  if (o.replicates < 1) throw std::invalid_argument("--replicates must be at least 1");
  return o;
}

std::string fmt(const scale::Json& j) { return j.is_null() ? "n/a" : j.dump(); }

void print_point(const scale::Params& p, const scale::Json& summary, double wall) {
  const auto& s = summary;
  std::printf(
      "SIMULATED  towns %dx%d, %d residents (%.0f%% adopt), p_link %.2f, p_uplink %.3f/h: %d replicates, %.1f s\n",
      p.towns_x, p.towns_y, p.residents, p.adoption * 100, p.p_link, p.p_uplink, static_cast<int>(s["replicates"]),
      wall);
  std::printf("  double spends: %s attempts by %s cheaters\n", fmt(s["totals"]["double_spend_attempts"]).c_str(),
              fmt(s["totals"]["cheaters"]).c_str());
  std::printf("  refused offline       %s  (replicate mean %s)\n", fmt(s["share_refused_offline"]["pooled"]).c_str(),
              fmt(s["share_refused_offline"]["replicate_mean"]).c_str());
  std::printf("  caught at settlement  %s  (replicate mean %s)\n",
              fmt(s["share_caught_at_settlement"]["pooled"]).c_str(),
              fmt(s["share_caught_at_settlement"]["replicate_mean"]).c_str());
  std::printf("  loss per cheater      %s cents (replicate mean %s)\n",
              fmt(s["mean_loss_per_cheater_cents"]["pooled"]).c_str(),
              fmt(s["mean_loss_per_cheater_cents"]["replicate_mean"]).c_str());
  std::printf("  median h to settle    %s\n", fmt(s["median_hours_to_settlement"]["replicate_mean"]).c_str());
}

int run(const std::vector<std::string>& args, bool sweep) {
  Options o = parse(args, sweep);
  std::vector<scale::Params> points;
  if (sweep) {
    for (const auto& v : o.axis_values) {
      scale::Params p = o.base;
      if (o.axis_name == "residents") {
        scale::size_city_for(p, std::stoi(v));
      } else {
        scale::set_param(p, o.axis_name, v);
      }
      points.push_back(p);
    }
  } else {
    points.push_back(o.base);
  }

  scale::ThreadPool pool(o.threads);
  auto started = std::chrono::steady_clock::now();
  scale::Json runs = scale::Json::array();
  for (const auto& p : points) {
    auto t0 = std::chrono::steady_clock::now();
    auto reps = scale::run_replicates(p, o.seed, o.replicates, pool);
    double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    scale::Json summary = scale::summary_json(reps);
    print_point(p, summary, wall);
    scale::Json detail = scale::Json::array();
    for (const auto& r : reps) detail.push_back(scale::replicate_json(r));
    runs.push_back({{"params", scale::to_json(p)},
                    {"base_seed", o.seed},
                    {"wall_seconds", std::nearbyint(wall * 100) / 100},
                    {"summary", summary},
                    {"replicates", detail}});
  }
  double total = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();

  if (!o.out.empty()) {
    scale::Json doc = {
        {"simulated", true},
        {"label", o.label},
        {"note",
         "SIMULATED by stormcash-scale (cpp/scale): the §16 town's rules on a grid of town tiles, with abstract "
         "tags (no keys or signatures). Not measurements of real phones."},
        {"tool", "stormcash-scale"},
        {"command", sweep ? "sweep" : "run"},
        {"axis", sweep ? scale::Json(o.axis_name) : scale::Json(nullptr)},
        {"machine", machine_json()},
        {"threads", pool.size()},
        {"wall_seconds", std::nearbyint(total * 100) / 100},
        {"runs", runs},
    };
    std::ofstream f(o.out);
    if (!f) throw std::runtime_error("can't write " + o.out);
    f << doc.dump(1) << "\n";
    std::printf("wrote %s (%.1f s on %u threads)\n", o.out.c_str(), total, static_cast<unsigned>(pool.size()));
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  std::vector<std::string> args(argv + 1, argv + argc);
  if (args.empty() || args[0] == "-h" || args[0] == "--help") {
    std::cout << kUsage;
    return args.empty() ? 2 : 0;
  }
  std::string command = args[0];
  args.erase(args.begin());
  try {
    if (command == "run") return run(args, false);
    if (command == "sweep") return run(args, true);
  } catch (const std::exception& e) {
    std::cerr << "stormcash-scale " << command << ": " << e.what() << "\n" << kUsage;
    return 2;
  }
  std::cerr << kUsage;
  return 2;
}
