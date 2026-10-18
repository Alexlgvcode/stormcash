# dashboard/

React + Vite + TypeScript + Tailwind dashboard (WS3, reviewer B): an operations command center in five workspaces, plus the public `/proof/:caseId` page.

- **Overview** (`#overview`): the mode (Storm / Normal, derived from Nessie's own escrow top-ups and refunds, since no GET reports it), connectivity, ledger and reconciliation status, weather, and where the money is, state by state, for the real phones (Nessie) and the simulated town (ledger only) side by side, never summed.
- **Network** (`#town`): the seeded town and the real shops as a network of shops linked by relay paths. Select a shop or an area for its panel (a bottom sheet below 1024 px). What-if sliders and the relay table are still there.
- **Cases** (`#cases`): the cryptographic proof (shared certificate, conflicting counter or link, both signatures, Verify it yourself, Proof QR) kept apart from StormDesk's AI reading of it. Owner freezes.
- **Ledger** (`#ledger`): the transaction explorer (filters, copyable tag ids), and #124's Balances, Reconciliation and Nessie log.
- **StormDesk** (`#stormdesk`): detection → case → agent → reviewer → human decision → audit with real counts, then the review queue (the human decision block), agent runs with cost and latency, and evals.

#124's hashes (`#accounts`, `#droid`, `#evals`) still land in the right place. The design tokens are in `src/index.css`: navy page, teal = verified / settled, amber = pending / offline, coral = conflict / frozen. Anything simulated or replayed carries a label.

- **Spec:** §18
- **Done when:** the full core demo runs with only dashboard clicks + phones, and every tab survives a page reload.
- **Built so far:** the top navigation bar (tabs, Demo mode, connection dot, clock, Reset demo), in the bank style of the approved mockup (#93); the Accounts tab (live Nessie balances that animate on change, Nessie call log, Ledger balanced ✓, Nessie queued counter, simulated town totals); the Cases tab and proof page; the Town tab (map, relay paths, and sliders over a quick in-memory re-sim, all labelled simulated); the Evals tab; the Droid tab (`#droid`, spec §18.7: Droid's stored runs, their tool calls, totals per job and the guardrails that fired).

## Run

The server must be running (see `server/README.md`). In dev, Vite proxies `/v1` to it (default `http://localhost:8000`, override with `STORMCASH_API`):

```bash
cd dashboard && npm ci && npm run dev
```

Open http://localhost:5173. The tab lives in the URL hash (`#accounts`), so a reload stays put.

In dev, the connection dot can sit on "Connecting…" for up to 15 s after a load: the Vite proxy holds the stream's headers until the server's first keep-alive ping. A build served by the server goes live at once.

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
- **A second, independent check (proof page):** the same press also runs our C++ verifier (`cpp/verify`), compiled to WebAssembly, on the same proof (`src/cppverify.ts`, `src/proof/CppCheck.tsx`). WebCrypto stays the primary result. Under it, the page shows the C++ verdict, then "Verified by 2 independent implementations", "Neither implementation verified this proof" or "The two implementations disagree". If the WebAssembly can't load, it shows "C++ check unavailable". The module is in `src/wasm/` and is built by `cpp/verify/wasm/build.sh`; don't edit it by hand, and CI checks that it matches the C++ sources. Only the proof page loads it (518 KB, 163 KB gzipped).
- **Tests:** `npm test` checks the same code against `spec/vectors.json`, and runs both checks on proofs captured from the server and on tampered copies (`src/cppverify.test.ts`).

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
