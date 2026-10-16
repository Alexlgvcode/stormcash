# sim/

Town simulator, 40 shops (WS4, reviewer B). Imports `server/stormcash/protocol` and calls `settlement.ingest_items()` directly, so the town is checked by exactly the same code as the phones.

- **Spec:** §16
- **Done when:** `seed-town 42` produces the planted cases plus candidates for all three soft kinds, and `stats.json` has all metrics.
- Output goes to `sim/out/<seed>/` (gitignored).
