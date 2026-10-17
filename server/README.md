# server/

FastAPI server: settlement, ledger, Nessie, policy, detectors, SSE, plus StormDesk (`stormcash/stormdesk/`, WS5) and Photon (`stormcash/photon/`, WS7).

- **Workstreams:** WS2 server core (reviewer B), WS5 StormDesk (B), WS7 Photon (A)
- **Spec:** §6.3 env, §11 schema/settlement/ledger/Nessie, §12 API, §13 detectors, §14 StormDesk, §17 Photon
- **Rule:** WS2 owns `stormcash/db.py`, `schema.sql` and `app.py`; other workstreams add routers in their own module.

## Setup

```bash
cd server && python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

```bash
cp .env.example .env
```

A new database gets the whole schema:

```bash
psql "$DATABASE_URL" -f schema.sql
```

A database created from an older schema.sql (the hosted demo DB) needs the migrations; each is safe to run twice:

```bash
psql "$DATABASE_URL" -f migrations/001_nessie_moves.sql
```

```bash
psql "$DATABASE_URL" -f migrations/002_stormdesk_runs.sql
```

```bash
psql "$DATABASE_URL" -f migrations/003_payouts_held.sql
```

```bash
psql "$DATABASE_URL" -f migrations/004_resident_freeze.sql
```

## Run

```bash
uvicorn --factory stormcash.app:create_app --host 0.0.0.0 --port 8000
```

Fallback switches in `.env` (spec §22.4): `NESSIE_DISABLED=1` keeps money ledger-only, `API_SIG_REQUIRED=0` accepts unsigned phone writes.

## Demo dry run

`stormcash/dryrun.py` (spec §21.6) is a pre-flight check for the judge demo. It plays the server side of the 2:30 script against a running server, about 15 s against the hosted database:

```bash
python -m stormcash.dryrun --base-url http://localhost:8000
```

It reads `server/.env` (or the environment):

- `DATABASE_URL`, to check the schema and what the API stored. It writes nothing there itself; everything goes through the API.
- `NESSIE_API_KEY`, to read Nessie directly and see what the bank recorded.
- `SERVER_PUB_HEX`, the key the phones pin. Override it with `--server-pub`; without either, it uses `mobile/src/config.ts`.

Its identities are "Dry-run Maya", "Dry-run Pharmacy" and "Dry-run Gas Station", with fresh keys each run. They register real Nessie accounts and act as the phones with the protocol library: requests and payments as QR payloads, C1–C6 as the merchant's phone runs them, judge mode's two rollbacks, sync sessions that carry items with their `path`, and the gas station's upload.

- **No Factory credits.** StormDesk's worker never queues a case or candidate whose resident or shop name starts with `Dry-run `. Before writing anything, the dry run asks `GET /v1/demo/dry-run` and refuses a server that can't answer. Step 9 fails if any StormDesk run touches dry-run data.
- **Cleanup.** It ends with `POST /v1/demo/reset`, which removes every dry-run identity first (`demo.clear_dry_run`: their certificates, payments, payouts, Nessie moves and call-log lines, cases, logs, ledger transactions). Register Maya's phone again afterwards, as after any reset. `--keep` skips the cleanup; the next reset removes what it left.
- **C++ check.** Step 7 also runs `cpp/build/verify/stormcash-verify proof` when it's built (`--verify-bin` to point elsewhere) and says it skipped otherwise.

Exit code 0 only when every step passed.

## Tests

Protocol tests need nothing. DB tests create their own `stormcash_test` database on the Postgres at `TEST_DATABASE_URL` (default `postgresql://postgres:postgres@localhost:5432/postgres`, the CI service) and never touch `DATABASE_URL`. Without a reachable Postgres they are skipped locally (and fail in CI). Without Docker, `pip install pgserver` gives a local Postgres:

```bash
export TEST_DATABASE_URL=$(python -c "import pgserver; print(pgserver.get_server('/tmp/sc-pg', cleanup_mode=None).get_uri())")
```

```bash
pytest
```

Nessie is faked in tests (`tests/conftest.py: FakeNessie`); nothing calls the real API.

## Dashboard on the same origin

If `dashboard/dist` exists (`cd dashboard && npm run build`), the server also serves the dashboard at `/` and the public proof page at `/proof/<case_id>`. A single cloudflared tunnel to port 8000 then serves the API and the HTTPS proof link judges open from the QR code (set `PUBLIC_BASE_URL` to the tunnel URL).

## StormDesk

`stormcash/stormdesk/` (spec §14). The worker runs StormDesk on every new hard case and candidate. `STORMDESK_RUNNER=auto` uses Factory's Droid when `FACTORY_API_KEY` is set and the `droid` CLI is installed, and otherwise a deterministic **fake runner** that applies the rules-only baseline; its output says "Fake runner" everywhere. Run one job by hand:

```bash
curl -X POST localhost:8000/v1/stormdesk/run -H 'X-SC-Operator: alex' -H 'content-type: application/json' -d '{"case_id": 1}'
```
