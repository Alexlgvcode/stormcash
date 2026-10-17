# chalk/

Chalk feature classes, resolvers and evaluations (WS6, reviewer B).

- **Spec:** §15
- **Done when:** one full Chalk Evaluation run completes and the Evals tab renders its results with the run id.
- Eval results (`evals/results/*.json`) are committed: the Evals tab renders only real runs.

## Features (#28, §15.1–§15.2)

- `features.py`: `Merchant`, `Certificate`, `Region`. Windows end at `as_of` (sim-clock seconds), which defaults to the server's latest sync.
- `resolvers/*.chalk.sql`: SQL resolvers on the `neon_stormcash` PostgreSQL integration (set up in the Chalk dashboard; no credentials in this repo).
- `resolvers/nws.py`: live NWS alerts for the four Buncombe County regions, falling back to replayed `weather_alerts` rows; `alert_source` says which.

```bash
uv sync
uv run pytest
chalk lint
chalk apply
chalk query --in merchant.id=<merchant_id hex> --out merchant.silence_ratio_6h --out merchant.as_of
```

StormDesk reads these through `query_features` (`server/stormcash/chalk_features.py`).
