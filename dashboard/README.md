# dashboard/

React + Vite + TypeScript + Tailwind dashboard (WS3, reviewer B): Accounts, Cases, Town and Evals tabs, plus the public `/proof/:caseId` page.

- **Spec:** §18
- **Done when:** the full core demo runs with only dashboard clicks + phones, and every tab survives a page reload.
- **Built so far:** header (Demo mode, connection dot, Reset demo, clock); the Accounts tab (live Nessie balances that animate on change, Nessie call log, Ledger balanced ✓, Nessie queued counter, simulated town totals); the Cases tab and proof page; the Town tab (map, relay paths, and sliders over a quick in-memory re-sim, all labelled simulated). The Evals tab comes later.

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

## Cases tab and the public proof page (#24)

- **Cases tab:** every hard case, live over SSE. Each case shows both tags side by side with the conflicting field in red, a **Verify it yourself** button, the **Proof QR**, the merchant's own ACCEPT entry for "merchant knew" cases, and StormDesk's case file.
- **`/proof/<case_id>`:** the mobile page a judge opens from the QR code. No login.
- **Verify it yourself** runs entirely in the browser (`src/verify.ts`). It rebuilds every signed string from the fields shown, checks the signatures with WebCrypto ECDSA P-256 / SHA-256, and re-checks the rule.
- **Tests:** `npm test` checks the same code against `spec/vectors.json`.

**For the demo:**

- WebCrypto only works over **HTTPS** (or localhost). Build the dashboard and let the server serve it, so one tunnel URL serves both the API and `/proof/…`:

  ```bash
  npm run build
  ```

- Set `PUBLIC_BASE_URL` in `server/.env` to the tunnel URL; the Proof QR uses it.
- Optionally bake the server key into the page. The value is the base64url of `SERVER_PUB_HEX`; without it, the page uses the key the server reports and says so:

  ```bash
  VITE_SERVER_PUB=<base64url> npm run build
  ```
