# cpp/scale/: Scale Lab

**Everything in this folder is simulated.** No number here was measured on phones, and none should be presented as if it were.

Scale Lab is a deterministic, minute-by-minute simulator of StormCash's offline gossip. It applies the §16 town's rules to a city of any size: a grid of town tiles, from one town (400 residents) to a million residents. It answers the judges' question "does this work in a real city?" with the same metrics as `sim/out/<seed>/stats.json`:

- the share of double spends refused offline;
- the share caught at settlement;
- the mean guarantee-pool loss per cheater;
- the median hours to settlement;
- a histogram of hops to the server.

It runs Monte Carlo replicates in parallel on a thread pool.

Payments are **abstract tags**: each is (cert, counter, prev, amount, cum) plus an id, with no keys, signatures or hashes. The equivocation rules R1–R3 are evaluated on those fields exactly as §8.3 states them, so offline refusal and server-side catches follow the protocol's logic without its cryptography. The cryptography is checked separately, by `stormcash-verify` against the shared vectors.

## Results (simulated)

Every number below comes from a file in [`results/`](results/), produced by [`run_sweeps.sh`](run_sweeps.sh) and [`validation/`](validation/) on an Apple M2 Pro (10 cores: 6 performance and 4 efficiency, 16 GB, macOS 26.6.2). Percentages are pooled over all replicates; the brackets are 95% intervals of the replicate mean.

### 1. Validation against the Python simulator

The model was compared with the Python engine before the scale results below were produced. Earlier large runs were smoke and speed tests only.

**The Python side** is the engine in `sim/`, unmodified ([`validation/run_python_engine.py`](validation/run_python_engine.py)): real P-256 signatures, the real C1–C6 checks and the real `settlement.ingest_items` on Postgres, with a fresh database per seed. It ran at its defaults: 38 shops, 400 residents (239 adopters on average), p_link 0.6, p_uplink 0.03/h, shelter 0.5/h, 72 h, T0 at local midnight. It had the §16.4 organic double spenders only (6 per town), planted by the same lines `scenarios.plant` uses. The scripted scenarios were left out (see "What the model leaves out"). 40 seeds took 443 s, 10.9 s per seed.

**The Scale Lab side** used the same parameters for 200 replicates, which took 0.13 s on 10 threads.

[`validation/compare.py`](validation/compare.py) treats each seed or replicate as one sample. "agree" means the Welch 95% interval of the difference contains 0.

| Metric | Python engine, 40 seeds | Scale Lab, 200 replicates | Scale Lab − Python | |
|---|---|---|---|---|
| share of double spends refused offline | 0.548 [0.491, 0.604] | 0.529 [0.504, 0.554] | −0.019 [−0.080, 0.042] | agree |
| share caught at settlement | 0.452 [0.396, 0.509] | 0.471 [0.446, 0.496] | 0.018 [−0.043, 0.079] | agree |
| mean loss per cheater (¢, pool money) | 553 [426, 680] | 541 [485, 596] | −12 [−150, 126] | agree |
| median hours to settlement | 2.26 [2.16, 2.35] | 2.23 [2.18, 2.27] | −0.03 [−0.14, 0.07] | agree |
| mean hops to the server | 2.45 [2.38, 2.52] | 2.41 [2.38, 2.44] | −0.04 [−0.12, 0.03] | agree |
| double-spend attempts per town | 7.80 [7.40, 8.20] | 7.90 [7.75, 8.05] | 0.10 [−0.32, 0.52] | agree |
| payments per town | 825 [812, 838] | 821 [816, 826] | −4 [−18, 10] | agree |
| refused payments per town | 15.6 [14.3, 16.9] | 16.0 [15.5, 16.6] | 0.4 [−1.0, 1.8] | agree |
| out-of-money visits per town | 1,898 [1,874, 1,923] | 1,887 [1,875, 1,900] | −11 [−38, 16] | agree |
| sync sessions per town | 6,452 [6,221, 6,682] | 6,394 [6,275, 6,513] | −58 [−316, 200] | agree |

The hops to the server (share of PAYs that reached it) also match:

| Hops | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9+ |
|---|---|---|---|---|---|---|---|---|---|---|
| Python engine | 0.098 | 0.254 | 0.215 | 0.191 | 0.117 | 0.068 | 0.030 | 0.016 | 0.007 | 0.004 |
| Scale Lab | 0.101 | 0.258 | 0.219 | 0.190 | 0.114 | 0.063 | 0.031 | 0.014 | 0.006 | 0.004 |

So does how shops refuse:

- **Refusals by check, over all payments per town:** Python 11.4 C2 and 4.2 C6; Scale Lab 12.1 C2 and 4.0 C6.
- **Re-spends refused because the cert was already frozen (C2):** Python 59 of 171; Scale Lab 313 of 835.

**What "agree" covers.** With 40 Python seeds, the comparison would detect a difference of more than about 6 percentage points on the two shares, about $1.40 on loss per cheater, or about 0.1 h on settlement time. It can't rule out smaller differences. The two simulators use different random streams, so a given seed is a different town in each. Only the distributions are comparable.

**One change came from looking at the Python engine, and it is stated here.** In the first version, a phone got the latest POLICY only when it uploaded a PAY.

- **What prompted it.** Python seed 1 had zero pool loss while Scale Lab averaged about 600¢. I compared the two models' ledgers for one seed and found a mechanism difference: the engine's phones nearly always have their own DLOG entries to upload, so every uplink refreshes their POLICY and a freeze spreads faster.
- **The change.** I added `policy_on_every_uplink`, on by default, before the 40-seed comparison existed.
- **What the comparison showed afterwards.** Seed 1's zero was ordinary variation: the 40-seed mean is 553¢. Both versions agree with Python at this sample size. The first version gives 0.524 refused, 0.475 caught, 587¢ [529, 644] and 2.23 h ([`comparison_policy_on_pay_only.md`](results/validation/comparison_policy_on_pay_only.md)).

The default is the engine-faithful one. The data alone doesn't prefer it. Nothing else was changed after looking at Python numbers.

**Known differences that don't show up in these metrics:**

- **Upload counts.** Python counts 475 uploads per town and Scale Lab 147, because Python phones also upload DLOG-only batches. This isn't a stats.json metric.
- **Same rules, different draws.** The town layout is drawn by the same rules but not the same draws.
- **Leftovers.** The rest is listed under "What the model leaves out".

**Speed.** One town takes 10.9 s in Python, with real signatures and Postgres writes, against 4 ms in Scale Lab (one thread, setup included). That is not a like-for-like comparison: the Python engine checks real cryptography and writes a real ledger.

### 2. A city, not a town

This is `results/sweep_residents.json` and `results/run_1m.json`: the town's density (400 residents per 40×24 tile) and defaults, with 2.5% of adopters double spending.

| Residents | Adopters | Shops | Double spends | Refused offline | Caught at settlement | Loss per cheater | Median h to settle |
|---:|---:|---:|---:|---|---|---|---|
| 400 (1 town) | 238 | 38 | 324 | 50.9% [45.0, 56.6] | 48.8% [43.1, 54.7] | $5.52 [4.08, 7.01] | 2.21 [2.12, 2.31] |
| 2,000 | 1,202 | 190 | 1,594 | 47.0% [44.8, 49.0] | 52.9% [51.0, 55.2] | $7.02 [6.47, 7.56] | 2.23 [2.18, 2.28] |
| 10,000 | 5,995 | 950 | 7,986 | 37.2% [36.3, 38.1] | 62.7% [61.9, 63.7] | $8.50 [8.18, 8.83] | 2.24 [2.23, 2.25] |
| 50,000 | 29,996 | 4,750 | 39,976 | 36.2% [35.8, 36.6] | 63.8% [63.4, 64.1] | $8.55 [8.39, 8.71] | 2.26 [2.25, 2.27] |
| 100,000 | 59,980 | 9,500 | 79,889 | 35.5% [35.2, 35.8] | 64.5% [64.2, 64.7] | $8.59 [8.50, 8.68] | 2.26 [2.25, 2.27] |
| 1,000,000 | 599,828 | 95,000 | 159,963 | 34.5% [34.2, 34.8] | 65.5% [65.2, 65.7] | $8.82 [8.74, 8.89] | 2.27 [2.26, 2.28] |

40 replicates per row, 8 for a million.

What the simulation says:

- **Double spends are caught.** At every size, refused offline plus caught at settlement covers 99.7% to 100% of double spends within the 72 hours. At most 0.31% of them (in one town; 0.03% or less in the cities) hadn't reached the server by the end.
- **Fewer are stopped at the counter in a city than in one town.** The share refused offline falls from 51% to about 35%, and pool money per cheater rises from $5.52 to about $8.60 against a $50 cap. Settlement time doesn't change. Above 10,000 residents the numbers barely move, so a bigger city isn't worse than a medium one.
- **The town's edges are the reason, and the radius sweep shows it.** A town resident can only shop inside the town. In a city, people have shops in every direction, so a rolled-back wallet more often reaches a shop that hasn't heard of its first payment.

| `trip_radius` (10k residents) | Refused offline | Caught at settlement | Loss per cheater | Median h |
|---:|---|---|---|---|
| 10 cells | 64.6% [63.6, 65.5] | 35.4% [34.5, 36.4] | $4.49 [4.24, 4.74] | 2.23 |
| 20 cells | 48.4% [47.4, 49.3] | 51.6% [50.6, 52.5] | $6.94 [6.66, 7.22] | 2.17 |
| 50 cells (default) | 37.2% [36.3, 38.1] | 62.7% [61.9, 63.7] | $8.50 [8.18, 8.83] | 2.24 |

How far people range in a storm is a modelling choice, not data. These results say offline refusal depends on it; settlement doesn't.

### 3. What moves the numbers (10,000 residents)

This is `results/sweep_*_10k.json`, 40 replicates per point, one parameter at a time, with the others at the town's defaults.

| Adoption | Refused offline | Loss per cheater | Median h to settle |
|---:|---|---|---|
| 20% | 30.1% [28.4, 31.6] | $11.25 [10.65, 11.85] | 3.33 [3.30, 3.37] |
| 40% | 35.5% [34.1, 36.8] | $9.23 [8.93, 9.53] | 2.62 [2.60, 2.64] |
| 60% | 37.2% [36.3, 38.1] | $8.50 [8.18, 8.83] | 2.24 [2.23, 2.25] |
| 80% | 38.1% [37.2, 39.0] | $7.82 [7.59, 8.05] | 2.01 [2.00, 2.02] |
| 100% | 40.0% [39.3, 40.8] | $7.14 [6.92, 7.37] | 1.83 [1.82, 1.84] |

| `p_link` | Refused offline | Loss per cheater | Median h to settle |
|---:|---|---|---|
| 0.05 | 28.1% [27.3, 28.9] | $11.88 [11.55, 12.22] | 4.08 [4.05, 4.10] |
| 0.1 | 33.1% [32.1, 34.1] | $9.86 [9.53, 10.19] | 2.93 [2.91, 2.95] |
| 0.3 | 36.8% [35.7, 37.7] | $8.60 [8.31, 8.89] | 2.32 [2.30, 2.33] |
| 0.6 | 37.2% [36.3, 38.1] | $8.50 [8.18, 8.83] | 2.24 [2.23, 2.25] |
| 0.9 | 38.0% [37.0, 39.0] | $8.22 [7.94, 8.50] | 2.26 [2.24, 2.27] |

| `p_uplink` (per hour) | Refused offline | Loss per cheater | Median h to settle |
|---:|---|---|---|
| 0.003 | 39.7% [38.8, 40.6] | $9.94 [9.60, 10.27] | 4.63 [4.58, 4.67] |
| 0.01 | 38.2% [37.4, 39.1] | $9.31 [9.01, 9.61] | 3.48 [3.45, 3.51] |
| 0.03 | 37.2% [36.3, 38.1] | $8.50 [8.18, 8.83] | 2.24 [2.23, 2.25] |
| 0.1 | 37.1% [36.1, 38.0] | $6.88 [6.57, 7.19] | 1.14 [1.13, 1.15] |
| 0.3 | 36.3% [35.2, 37.2] | $5.97 [5.73, 6.21] | 0.49 [0.49, 0.50] |

- **Adoption and foot traffic (`p_link`) decide what is caught offline.** More phones relaying means more shops have heard of the first payment. Below `p_link` 0.3, refusals fall off quickly.
- **Uplink decides how fast money settles and how much the pool pays.** Offline refusal barely moves with it.
- **Each town's shelter carries settlement.** Even at 0.003/h per phone (one connection every two weeks), the shelter's 0.5/h keeps the median under 5 hours, and only 0.08% of double spends weren't caught by the end.

### 4. Runtime

On the M2 Pro: `results/timing_single_thread.json` for wall time (one replicate, one thread, machine otherwise idle) and `results/peak_memory.txt` for peak RSS (`/usr/bin/time -l`).

| Residents | Shops | One 72 h replicate, one thread | Peak memory |
|---:|---:|---:|---:|
| 400 | 38 | 0.004 s | |
| 10,000 | 950 | 0.18 s | 13 MB |
| 100,000 | 9,500 | 2.7 s | 116 MB |
| 1,000,000 | 95,000 | 45 s | 970 MB |

In parallel, 40 replicates of 100,000 residents took 22.5 s on 10 threads. 8 replicates of a million took 227 s on 4 threads, kept to 4 to hold memory to about 4 GB. Replicates running side by side are each slower than one alone (5.4 s instead of 2.7 s at 100,000), because they share memory bandwidth. The whole of `run_sweeps.sh` took 5 min 33 s.

## A "Scale" panel for the dashboard (not built)

The dashboard is out of scope here, but the data is ready for one. A panel would:

- **Read** `cpp/scale/results/sweep_*.json`, and for each run (one per swept value) take `params`, the four `summary` metrics, and `summary.hops_histogram`. Each metric has a `pooled` value and a `replicate_mean` with its `ci95`.
- **Plot** each metric against the swept value with its interval band, next to the Town tab's 40-shop numbers.
- **Label** everything "simulated".

It should load these files rather than run Scale Lab live: a 100,000-resident replicate takes seconds, not the Town tab's under-3-second budget. The one exception would be a small `stormcash-scale run --residents 10000 --replicates 8` behind a button.

## Run it

Build with the rest of `cpp/` (see [`../README.md`](../README.md)), then:

```bash
cpp/build/scale/stormcash-scale run --residents 100000 --replicates 20 --out city.json
```

```bash
cpp/build/scale/stormcash-scale sweep --residents 10000 --axis p_uplink=0.01,0.03,0.1 --replicates 40 --out sweep.json
```

The options:

- `--residents N` sizes the city at the town's density: N / 400 tiles of 40×24 cells, each with 38 shops.
- `--set NAME=VALUE` sets any parameter in `include/scale/params.hpp` (`adoption`, `p_link`, `p_uplink`, `cheaters`, `cheater_share`, `trip_radius`, `hours`, ...).
- `--axis` sweeps one parameter; `--axis residents=...` sweeps the city size.
- `--seed S` sets the base seed. Replicate `i` runs with `derive_seed(S, i)`, so a run is reproducible and doesn't depend on `--threads`. A test checks that 1 and 4 threads give identical output.
- **Across platforms.** The random draws are written out by hand (`rng.hpp`), but `log`, `exp` and `cos` come from the platform's libm, so bit-identical results across platforms aren't guaranteed. In practice, `run --residents 10000 --replicates 4` gave identical output on macOS (Apple clang, arm64) and Ubuntu 24.04 (GCC 13, glibc, arm64).

The output JSON holds the parameters, the machine, the wall time, a summary per parameter point (pooled values, and replicate means with 95% Student-t intervals), and one `stats.json`-shaped record per replicate.

## The model

One replicate is one 72-hour storm, one tick per simulated minute. It follows `sim/stormcash_sim/engine.py` rule for rule, with no database and no cryptography:

- **City.** A `towns_x × towns_y` grid of 40×24-cell tiles. Each tile is built the way `town.py` builds the town: four regions as vertical stripes, two cluster centres per region, 9 to 11 shops per region scattered ±3 cells around them (38 per tile), and one Downtown Shelter with 0.5/h uplink. Residents are spread evenly over the tiles, homed by the town's regional shares, and 60% adopt; only adopters are modelled, as in the engine.
- **Days.** Trips run between 07:00 and 21:00 local. The gap between trips is exponential with a mean of 240 minutes. The destination shop is weighted 1 / (1 + d)², travel takes 2 minutes per cell, and a visit lasts 5–12 minutes. Storm Mode raises 70% of caps from $20 to $50 at T+2 h. Payments are $3–$45, log-normal around $12, clipped to what is left under the cap.
- **Meetings.** Each minute, every resident at a shop may sync with every shop within 2 cells, and with every resident at those shops. Each pair has probability `p_link` and syncs at most once an hour. Shops never sync with each other directly.
- **Gossip.** A sync drops what the server has had for an hour, then each side gets every item the other has and it lacks, one hop further along its path. POLICY moves as a version number, and the higher one wins.
- **Uplink.** Each phone gets internet with probability `p_uplink` per hour (the shelter 0.5), drawn as a geometric waiting time, which is the same process as the engine's draw every minute. It uploads every PAY the server hasn't received and drops what it sent. It comes back with the latest POLICY.
- **Double spenders.** These are the §16.4 organic kind. A share of adopters (default 2.5%, the town's 6 of about 240) are in Storm Mode and relay nothing. After a payment under the $50 cap, a cheater rolls the wallet back and spends the same amount again 1–3 shop visits later, up to twice. Half reuse the counter (R1 against the first payment); half skip one with the old running total (R3). The wallet then carries on from the re-spend, as a rolled-back phone would. Like the engine, a later payment re-arms the plan while cheats are left.
- **Shops' checks.** C2 refuses a cert frozen by a POLICY version the shop holds. C6 refuses a tag that conflicts with any stored tag of that cert under R1–R3, or that isn't newer than the highest stored counter. A shop stores every tag it has seen, apart from what it carries. Refused payments are kept as evidence and relayed. C1, C3, C4 and C5 can't fail for these payments.
- **Server.** When a PAY arrives, the server stores its tag and opens a case with the first stored tag it conflicts with, in (counter, hash) order. The case freezes the cert in a new POLICY version. An accepted payment is paid from escrow up to the highest cap issued, and from the guarantee pool beyond it. A payment refused offline is never paid.
- **Metrics,** computed as `outputs.py` computes them. Refused offline is the share of re-spends a shop refused. Caught at settlement is the share of re-spends that a shop accepted and that then ended up in a case (both shares are over all re-spends, so they add up to at most 1). Loss per cheater is pool money paid on cheaters' certs, divided by the number of cheaters. Hours to settlement runs from acceptance to the PAY's first upload. Hops are counted over every PAY that reached the server.

### What the model leaves out, and why the metrics don't need it

- **Cryptography.** A tag's id stands in for its hash: a random 64-bit value breaks ties where the spec orders by hash. Signatures can't be forged here, which is the protocol's assumption anyway.
- **TAG copies.** An honest wallet's copy of its own tag is never settled (only the PAY is) and never conflicts, so it changes no metric. A cheater's phone relays nothing. So every item that matters is a PAY.
- **DLOG entries and R5/R6.** The organic double spenders cheat honest shops, and an honest shop that held the conflicting tag would have refused under C6, so R5 can't fire for them. Leaving the entries out has one side effect, which the next point handles.
- **"A phone always has something to upload."** In `engine.py` a phone calls the server only when it has items pending, but it nearly always does: its own DLOG entries. So every uplink brings back the latest POLICY. Scale Lab has no DLOG items, so `policy_on_every_uplink` (default on) gives a phone with internet the latest POLICY even when it has no PAY to send. See "Validation" for how this was found and what it changes.
- **PROOF items.** A shop that refuses under C6 also holds the refused PAY, and the conflicting tag is in its own carry unless the server already has it. So the PROOF's two tags reach the server through PAYs anyway. The PROOF can carry the conflicting tag a little further than that tag's own PAY, after the server has it. That is a second-order effect on C6 knowledge, and it isn't modelled.
- **Scripted scenarios** (colluders, stolen phones, dark and quiet regions, traps). These are hand-placed events for the evals, not town dynamics.
- **A refused PAY is never paid.** The engine marks it `refused_evidence` once the shop's REFUSE log entry is at the server. Both travel together in practice.

### Scaling the town up

A city is many copies of the town generator, with continuous space between tiles: people near a tile edge shop in the next tile. Each resident's trips are limited to `trip_radius` (50 cells) of home, with the same 1 / (1 + d)² weights. 50 cells reaches every shop of a tile from anywhere in it, so a 1-tile city is exactly the Python town. In a big city, though, people far from any edge have several times more shops within reach than a town resident. The sweeps include `trip_radius` so this choice is visible.

## Code

```
include/scale/rng.hpp           xoshiro256** + SplitMix64 seeding, distributions written out (portable draws)
include/scale/params.hpp        every parameter, defaults = the §16 town
include/scale/city.hpp          tiles, regions, shops, residents (town.py's generator)
include/scale/sim.hpp           ReplicateResult: the stats.json metrics of one replicate
src/sim.cpp                     the simulation: events, meetings, gossip, uplinks, server
include/scale/thread_pool.hpp   fixed-size pool; replicates share nothing
include/scale/runner.hpp        replicate i <- derive_seed(base, i), results in replicate order
include/scale/stats.hpp         replicate means, 95% t intervals, pooled values, JSON
cli/main.cpp                    stormcash-scale run / sweep
validation/                     the Python engine harness and the comparison script
results/                        every number in this README, as JSON
```

Performance notes: carry sets are sorted vectors merged in linear time. Shops store tags only for double spenders' certs, because an honest chain can't fail C6. Uplinks are scheduled as geometric waiting times instead of a draw per phone per minute. Trip choice scans a 10×10-cell block grid within the radius. All of it is single-threaded inside a replicate, and parallel across replicates.

## Tests

`ctest` runs the Scale Lab tests with the verifier's:

- **Determinism.** The same seed gives the same output, and 1 and 4 threads give the same results.
- **Bookkeeping.** accepted + refused = payments; refused + accepted re-spends = attempts; caught ≤ accepted; settled ≤ accepted.
- **Limiting cases.** An honest town has no refusals and no pool loss. No internet means nothing settles. Instant internet catches every accepted double spend. With `p_link = 0`, no PAY ever moves a hop.
- **RNG.** Distribution means and range bounds.
- **Statistics.** The Student-t intervals.
