# sim/

Town simulator, 40 shops (WS4, reviewer B). Imports `server/stormcash/protocol` and calls `settlement.ingest_items()` directly, so the town is checked by exactly the same code as the phones: real P-256 keys and signatures, the real C1–C6 merchant checks, and the real server ingest. Every row is `simulated=true` and money is ledger-only (Nessie is forced off).

- **Spec:** §16
- **Done when:** `seed-town 42` produces the planted cases plus candidates for all three soft kinds, and `stats.json` has all metrics.
- Output goes to `sim/out/<seed>/` (gitignored).

## Run

Install next to the server (same venv):

```bash
pip install -e ./sim
```

Run a 72 h storm into the database from `server/.env` (or `--database-url`). A seed refuses to run twice into one database:

```bash
python -m stormcash_sim --seed 42 --hours 72
```

Options (spec §16.3 defaults): `--residents 400 --adoption 0.6 --storm-share 0.7 --storm-at-h 2 --p-link 0.6 --p-uplink 0.03 --shelter-uplink 0.5 --start <unix T0>`.

It prints a summary (payments, contacts, uploads, median minutes for a payment to reach the server, wall time). A 72 h storm takes about 9 s against a local Postgres.

## Model (v1, #21)

- 38 simulated shops in clusters per region (Corner Store and the Downtown Shelter with good uplink are downtown); the real Pharmacy and Gas Station are real phones, not created here.
- ~400 residents, 60% adopt: each gets a cert ($20), and 70% raise Storm Mode ($50) at T+2 h.
- Residents make trips by day (07:00–21:00 local) to shops weighted by distance and pay $3–$45 (log-normal) by QR; the shop runs C1–C6 and logs ACCEPT / REFUSE.
- Phones within 2 cells at a shop sync with probability `p_link` (once per pair per hour): items exchange, both sides log CONTACT. Shops don't link to each other directly.
- Each phone gets internet with probability `p_uplink` per hour (Shelter 0.5/h) and uploads through `ingest_items`.

Scenarios, labels and stats come with #25.

## Tests

```bash
cd sim && pytest
```

Uses `TEST_DATABASE_URL` like the server tests (see `server/README.md`).
