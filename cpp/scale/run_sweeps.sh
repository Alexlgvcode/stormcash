#!/usr/bin/env bash
# Reproduces every Scale Lab result in cpp/scale/results/ (all SIMULATED).
#
#   cpp/scale/run_sweeps.sh [path/to/stormcash-scale]
#
# Base seed 1 everywhere, so a re-run on the same machine gives the same
# numbers (wall times aside). The validation's Python side is separate:
# cpp/scale/validation/run_python_engine.py (needs Postgres).
set -euo pipefail

BIN=${1:-cpp/build/scale/stormcash-scale}
OUT=cpp/scale/results
mkdir -p "$OUT/validation"

# Validation: the §16 town with its 6 organic double spenders, T0 at local midnight.
"$BIN" run --set cheaters=6 --replicates 200 --seed 1 \
  --label "validation: the §16 town, 6 organic double spenders, T0 local midnight" \
  --out "$OUT/validation/scale_lab.json"
"$BIN" run --set cheaters=6 --set policy_on_every_uplink=0 --replicates 200 --seed 1 \
  --label "validation ablation: POLICY only refreshed when a PAY is uploaded (first version)" \
  --out "$OUT/validation/scale_lab_policy_on_pay_only.json"

# City size at the town's density (400 residents per 40x24 tile), defaults otherwise.
"$BIN" sweep --axis residents=400,2000,10000,50000,100000 --replicates 40 --seed 1 \
  --label "city size" --out "$OUT/sweep_residents.json"

# A million residents: fewer replicates, 4 threads (~1 GB of memory each).
"$BIN" run --residents 1000000 --replicates 8 --threads 4 --seed 1 \
  --label "one million residents" --out "$OUT/run_1m.json"

# One parameter at a time, 10,000 residents (25 tiles).
"$BIN" sweep --residents 10000 --axis adoption=0.2,0.4,0.6,0.8,1.0 --replicates 40 --seed 1 \
  --label "adoption, 10k residents" --out "$OUT/sweep_adoption_10k.json"
"$BIN" sweep --residents 10000 --axis p_link=0.05,0.1,0.3,0.6,0.9 --replicates 40 --seed 1 \
  --label "p_link, 10k residents" --out "$OUT/sweep_p_link_10k.json"
"$BIN" sweep --residents 10000 --axis p_uplink=0.003,0.01,0.03,0.1,0.3 --replicates 40 --seed 1 \
  --label "p_uplink, 10k residents" --out "$OUT/sweep_p_uplink_10k.json"
"$BIN" sweep --residents 10000 --axis trip_radius=10,20,50 --replicates 40 --seed 1 \
  --label "trip radius (modelling choice), 10k residents" --out "$OUT/sweep_trip_radius_10k.json"

# Runtime of a single replicate on one thread with the machine otherwise idle
# (in the sweeps above, replicates share the CPU's memory bandwidth).
"$BIN" sweep --axis residents=400,10000,100000,1000000 --replicates 1 --threads 1 --seed 1 \
  --label "timing: one replicate, one thread" --out "$OUT/timing_single_thread.json"
