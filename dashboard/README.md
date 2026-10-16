# dashboard/

React + Vite + TypeScript + Tailwind dashboard (WS3, reviewer B): Accounts, Cases, Town and Evals tabs, plus the public `/proof/:caseId` page.

- **Spec:** §18
- **Done when:** the full core demo runs with only dashboard clicks + phones, and every tab survives a page reload.
- **Built so far:** header (Demo mode, connection dot, Reset demo, clock) and the Accounts tab (live Nessie balances that animate on change, Nessie call log, Ledger balanced ✓, Nessie queued counter, simulated town totals). Cases, Town and Evals come in later issues.

## Run

The server must be running (see `server/README.md`). In dev, Vite proxies `/v1` to it (default `http://localhost:8000`, override with `STORMCASH_API`):

```bash
cd dashboard && npm ci && npm run dev
```

Open http://localhost:5173. The tab lives in the URL hash (`#accounts`), so a reload stays put.

For a build served from somewhere else, point it at the API:

```bash
VITE_API_BASE=https://<cloudflared>.trycloudflare.com npm run build
```

## How it stays live

One `EventSource` on `GET /v1/stream` (§12.3). The Accounts tab refetches `GET /v1/accounts` (debounced) on `nessie_call`, `accounts`, `payment` and `upload` events, and prepends `nessie_call` rows to the call log.
