# StormCash — Build Spec v4 (HackHarvard 2026)

> **Audience:** the two humans on the team and every Claude session working on this repo.
> **Status:** source of truth. If code and this doc disagree, the doc wins until the doc is changed. Change the doc in the same commit as the code, and say so in the commit message.
> **v4.1 (Oct 16):** work split rebalanced: Person A also reviews the TypeScript half of WS0, owns WS7 Photon, and records the backup video (§4, §22). Marked **[v4.1]**.
> **v4.2 (Oct 16):** Nessie integration rewritten after the hour-1 VERIFY (§11.4): money moves as withdrawal + deposit pairs, balances are computed from Nessie transactions, Nessie amounts are whole dollars, base URL is HTTPS. Marked **[v4.2]**.
> **v4.3 (Oct 16):** WS2 server core (#13): every Nessie money movement is a `nessie_moves` row executed after commit and replayed until both halves exist; signed API writes spelled out; fallback switches `NESSIE_DISABLED` and `API_SIG_REQUIRED` (§6.3, §11.1, §11.4, §12, §22.4). Marked **[v4.3]**.
> **v4.4 (Oct 16):** seed-town against the hosted DB takes ~45 s instead of ~46 min: each upload is one pipelined transaction (uploads one at a time) instead of one transaction per item, with the same results (§11.2, §16.5). Marked **[v4.4]**.
> **v4.5 (Oct 17):** Photon shapes verified (§6.3, §17): Spectrum webhooks with HMAC signatures inbound, a small Node bridge for outbound. Marked **[v4.5]**.
> **v4.6 (Oct 16):** Chalk verified and built (#28, §15.1, §15.2): sim-time windows are an `as_of` feature (no Postgres views needed), SQL resolvers read the Neon integration `neon_stormcash`, the NWS resolver labels live vs replayed, and `query_features` calls Chalk with fallback switch `CHALK_DISABLED` (§6.3, §14.7a, §22.4). Marked **[v4.6]**.
> **v4.7 (Oct 17):** Chalk Evaluations built (#33, §15.3): 48-row dataset from 5 seeds in local per-seed databases, a token-gated gateway behind one tunnel for the StormDesk task, a rules-only baseline task, the `run_local.py` fallback, and results files that never show a fake-runner run as StormDesk. Marked **[v4.7]**.
> **v4.8 (Oct 17):** Evals tab built (#38, §18.5): `GET /v1/evals` serves the saved Chalk runs, and only a verified Droid run fills the StormDesk column. Marked **[v4.8]**.
> **v4.9 (Oct 17):** first live Droid runs (#27): run cost recorded per run, the citation check accepts a hard case's `proof_item_id`, the prompt says evidence ids name records, not field values (§14.2, §14.4, §14.7). Marked **[v4.9]**.
> **v4.10 (Oct 17):** the colluder scenario now takes pool money that the hard rules can't deny (3 cheaters' re-spends per colluder, §16.4), after the first live triage dismissed a colluder whose only pool payment was already covered. Marked **[v4.10]**.
> **v4.11 (Oct 17):** first real StormDesk Chalk Evaluation (#33, §15.3): the eval dataset is rebuilt from the v4.10 simulator (43 rows), and a Droid guard checks every row's model and credits from the Droid session files, stops the run on a model switch or at a credit cap, and never saves a mixed or partial run as StormDesk. Marked **[v4.11]**.
> **v4.12 (Oct 17):** StormDesk prompt v2 (§14.4): how to weigh soft evidence, written after reading v1's eval errors, so not a blind holdout. Marked **[v4.12]**.
> **v4.13 (Oct 17):** resident FREEZE by text built (§17.2): residents get a Photon handle (`resident_contacts`), a FREEZE text freezes the cert through the hard-rule freeze path and publishes a POLICY, `cert_status.owner_freeze_at` feeds cap_drain's `owner_freeze_request`, and resident threads live in `messages` (§11.1, §12.1, §12.3, §13.2). Migration `004_resident_freeze.sql`. Marked **[v4.13]**.
> **v4.14 (Oct 17):** prompt v2 evaluated complete on the 43-row dataset, and on held-out seeds fixed before the run (#100, §15.3): the held-out section on the Evals tab, the prompt-version guard, and an idempotent eval gateway. Marked **[v4.14]**.
> **v4.15 (Oct 17):** a reviewer Droid (§14.7b): a second session tries to refute each triage Flag with the same read-only tools before a person sees it; a valid disagreement marks the flag "agents disagree" and keeps it open for a person, who still decides. `STORMDESK_REVIEW`, `POST /v1/stormdesk/review`, `flags.review` / `agents_disagree`, `stormdesk_runs.job = 'review'` (§6.3, §11.1, §12.1, §14.1, §22.4). Migration `005_stormdesk_review.sql`. Marked **[v4.15]**.
> **v4.16 (Oct 17):** the reviewer Droid evaluated on held-out rows (§15.3, §14.7b): "v2 alone" vs "v2 + reviewer" as two Chalk Evaluations on run B's frozen outputs; a one-row-at-a-time driver that never sends a review twice. Marked **[v4.16]**.
> **v4.17 (Oct 17):** live reconciliation of the ledger with Nessie's own records (§11.4a): `GET /v1/accounts/reconcile` and a "Reconciled with Capital One Nessie" panel on the Accounts tab (§12.1, §18.2). Balances and the check share one ≤ 10 s cache of each account's records. Marked **[v4.17]**.
> **v4.18 (Oct 17):** a demo dry run (§21.6): `python -m stormcash.dryrun` plays the server side of the 2:30 script as three labelled test identities and prints ✓ or ✗ per beat, before every judge. StormDesk's worker skips dry-run identities and a demo reset removes them; `GET /v1/demo/dry-run` (§12.1, §14.7a). Marked **[v4.18]**.
> **v4.19 (Oct 17):** every demo reset opens a fresh guarantee pool account under the same "StormCash Operator" customer, at `NESSIE_POOL_DOLLARS`, so the pool's Nessie records start clean and reconcile ✓; the old account stays in Nessie untouched. The current pool is the newest `nessie_pool_accounts` row, else `NESSIE_POOL_ACCOUNT_ID` (§6.3, §11.1, §11.4, §11.4a, §12.1). Migration `006_nessie_pool.sql`. Marked **[v4.19]**.
> **v4.20 (Oct 17):** the public proof page checks each proof a second time with our C++ verifier (`cpp/verify`) compiled to WebAssembly, next to WebCrypto; the two implementations share no code (§18.6). Marked **[v4.20]**.
> **v4.21 (Oct 17):** a shop's appeal by text is one conversation (§17.2): each appeal thread (shop + flag) keeps one Droid session, resumed with `Session.resume` for every new text, with the same read-only tools, permission handler and citation check on every turn; a session that can't be resumed is replaced by a new one seeded with the thread from `messages`. `STORMDESK_APPEAL_SESSIONS` (§6.3, §12.1, §14.7c, §18.7, §22.4). No migration: each turn's run stores its session, turn and thread. Marked **[v4.21]**.
> **v4.22 (Oct 17):** Droid proposes a new deterministic detector as a pull request (§14.7d): it writes a pure detector and its test in a throwaway worktree, under a permission handler and two macOS sandbox profiles; our server re-runs the tests and an evaluation on the simulator's labelled candidates and rejects any mismatch; then deterministic code opens a PR labelled for a person and never merges it. `STORMDESK_AUTHOR`, `POST /v1/stormdesk/author-detector`, `stormdesk_runs.job = 'author'`, `server/stormcash/detectors_proposed/` (§6.3, §11.1, §12.1, §14.1, §18.5, §18.7, §22.4). Migration `007_stormdesk_author.sql`. Marked **[v4.22]**.
> **v4.23 (Oct 17):** dashboard redesign (#93, §18): one Stripe-like style for every tab and the proof page (a white page, no cards, headings over hairline rules, plain tables, small status pills, carbon blue as the only accent), a left sidebar in place of the header, and no intro screen (the dashboard opens on Accounts). Each tab splits into views: Accounts (Balances, Reconciliation, Nessie log), Cases (Proven fraud, Review queue, Owner freezes), Town (Map, Relay paths, What-if), Evals (Held-out towns, Main dataset, Runs), Droid (Runs, Guardrails, Detector proposals). Every feature is kept. A readability pass: plain words instead of internal names (signals, jobs, rules, tools, the rules-only "stand-in"), times as "4:34 PM", secondary text no lighter than #545969 and never under 13 px, a one-line takeaway from real data atop each tab, account-setup Nessie calls behind "Show setup calls", proven cases from your phones before the simulated town's, and raw hashes under "Technical details". Marked **[v4.23]**.
> **Builds on:** "StormCash: The 10/10 Build" v3 (Oct 16, Alexandre Lugovoi, on Brian Maina's Oct 11 draft). Everything new since v3 is marked **[v4]**.

---

## Table of contents

0. How to use this doc (read first, Claude)
1. Product in one page
2. Prize map and what each judge must see
3. Event facts and hard constraints
4. Team, machines, ownership
5. Repo layout
6. Tech stack, versions, environment setup
7. Protocol: crypto, encoding, objects
8. Offline checks and fraud rules
9. Device logs, contacts and the "merchant knew" rule **[v4]**
10. Gossip and store-and-forward relay over Multipeer **[v4]**
11. Server: schema, settlement, ledger, Nessie
12. Server API
13. Soft signals (deterministic detectors) **[v4]**
14. StormDesk agent (Factory Droid SDK) **[v4]**
15. Chalk: features, query tool, evaluations **[v4]**
16. Town simulator (40 shops) **[v4]**
17. Photon messaging agent **[v4]**
18. Dashboard
19. Mobile app
20. Test vectors
21. Demo: table, scripts, sponsor add-ons
22. Build plan, cut order, checklists
23. Pitfalls
24. Judge Q&A
25. Glossary

---

## 0. How to use this doc (read first, Claude)

**You are one of several parallel workers.** Each Claude session owns exactly one workstream (§4.3) and one folder. Do not edit files outside your folder except `spec/` (shared protocol) when the task says so, and never without updating this doc.

**Rules of engagement**

1. **The protocol (§7–§10) is frozen once test vectors exist (§20).** Any change to field order, encoding, or rules requires: updating §7–§10, regenerating `spec/vectors.json`, and passing both the Python and TypeScript vector tests. Tell the humans in your final message.
2. **Never put AI in the money path.** The agent (StormDesk) reads data and returns a structured proposal. Only deterministic code freezes certificates, and only a human click moves money on a soft flag.
3. **Be honest in UI copy.** Simulated shops say "simulated". Replayed weather says "replayed". Numbers on the Evals tab come only from an actual run. No invented statistics anywhere (README, Devpost, slides, dashboard).
4. **Prefer boring code.** Plain SQL with psycopg, plain FastAPI, plain React. No ORMs, no Redis, no Kubernetes, no microservices.
5. **Everything has a fallback** (§22.4). If you build a risky thing, build its fallback switch at the same time.
6. **Done means demoable.** A workstream is done when the "Done when" line in its section is true on the real demo hardware, not when unit tests pass.
7. **Money is integer cents everywhere** (`*_cents`), except at the Nessie boundary, which takes **whole dollars as an integer** **[v4.2]**. Convert in exactly one helper (`server/nessie.py: cents_to_dollars`), which refuses non-whole-dollar amounts instead of rounding (§11.4).
8. **Time is integer Unix seconds (UTC)** everywhere in the protocol. Display local time only in UIs.
9. When something in this doc is marked **VERIFY**, check it against the real docs or API in the first hour and fix the doc if it is wrong.

---

## 1. Product in one page

**One line:** When a disaster takes out towers and card readers, StormCash keeps phones paying local shops, and stops cheaters with no internet.

**The problem.** After Hurricane Helene (2024), card readers in western North Carolina couldn't connect, most ATMs were down or empty, and some shops stayed cash-only for a month. After Hurricane Maria (2017), it was almost impossible to find a place in San Juan that took cards. People had money in the bank and phones with battery, and still couldn't pay, because every payment app needs a server to approve each payment.

**What StormCash does.**

- Before or without a storm warning, a resident's bank (Capital One, via Nessie) locks a small amount in an escrow account and the StormCash server signs a **certificate** saying "this phone may spend up to $X". Always-on cap $20; Storm Mode raises it to $50.
- Offline, the resident pays a shop by QR. The shop's phone checks the bank-backed certificate and the resident's signature with no network, and shows "Backed by Capital One, $12 of $50 used".
- Every payment produces a signed **spend tag**. Phones gossip tags over Bluetooth/peer Wi-Fi (Apple Multipeer). Customers carry tags from shop to shop. A rolled-back wallet trying to spend the same money is **refused offline** by the next shop that has seen the tag, and the two conflicting signatures are **self-proving evidence**.
- Payments, tags and logs travel **phone to phone** (store-and-forward) until any phone gets a signal and uploads them. The server pays merchants in Nessie, freezes cheaters, and sends signed receipts, freeze lists and renewed certificates back the same way.
- **[v4]** Every phone keeps a signed, hash-chained **device log** of payments and contacts. A shop that accepted a payment while holding the conflicting tag is caught by its own signature ("merchant knew"). A shop that goes quiet while taking guarantee-pool money is flagged.
- **[v4]** **StormDesk**, a back-office agent built on the Factory Droid SDK with data and evals on Chalk, investigates fraud cases and triages suspicious patterns. It proposes; a human approves. Merchants get notices and can appeal by text through a **Photon** agent.

**The line judges should repeat:** "I tried to cheat it with no internet, and it refused me."

**The closing line:** "Math flags. The agent investigates. A person decides."

**Honest limits (say them before judges do):**
- Offline double spending is bounded, not impossible. A shop no tag has reached can be fooled once, up to the cap; settlement proves it and the guarantee pool pays the shop.
- The wallet counter lives in app storage, not a secure chip.
- iPhones only exchange data while the app is open.
- Phones share pseudonymous certificate ids, amounts and running totals, never names or which shop was paid.

---

## 2. Prize map and what each judge must see

Confirmed by organizers: a team may enter **one track plus any number of sponsor challenges**; sponsor judges (incl. Chalk and Factory) judge **at our table**. No new challenges announced as of Friday.

| Prize | Award | What wins it for us | Must exist in the build |
|---|---|---|---|
| **Digital Trust** track (Fintech & Cybersecurity) | Brick per member | Judge personally fails to cheat with no internet; signed proof; "merchant knew" rule | Judge mode, refusal screen, Verify-it-yourself page, device logs |
| **Best Use of Nessie** (Capital One) | $300 gift card per member | Nessie moves the money live: escrow, settlement, guarantee pool, refund | Accounts tab with live balances + Nessie call log |
| **Factory Droid SDK** | $2,000 team + $200 credits each | Droid does real work in the running product: investigates cases and triages flags | StormDesk worker, live tool-call stream, README section "Where Droid runs" |
| **Chalk** data-driven agent | $1,500+ Apple credits, interviews | Agent runs on real-world data (Nessie, NWS alerts, logs) and is evaluated rigorously | Chalk features used by the agent at runtime + Evals tab from a real Chalk Evaluation run |
| **Photon** messaging agent | $400 + $300 credits + interview fast-track (runner-up $200) | An agent on a real number that argues with evidence | Merchant hold notice + appeal conversation on Telegram/iMessage |

Not targeting: Regeneron, ASUS, Hardware for Good, Daytona, SpaceXAI. Use Claude as the model where we choose a model, in case an Anthropic prize appears.

---

## 3. Event facts and hard constraints

- HackHarvard 2026, Oct 16–18, Harvard. Hacking starts after the 3–4 PM Friday opening ceremony.
- **Devpost submission due Sunday 8:00 AM.** Judging in person, Canopy Hall, 9:00–10:30 and 10:30–12:00. Closing ceremony 3 PM.
- **Venue closes overnight.** Late blocks happen wherever we sleep. Confirm Saturday opening time.
- Sponsor fair Saturday 10 AM–12 PM, 3rd Floor Atrium: show Capital One, Factory, Chalk, Photon our flow and ask what they reward.
- Photon workshop Friday 4–5 PM. Go if possible.
- **Hardware: 3 iPhones, 2 Macs. No Android, no 4th phone.**
- **No paid Apple Developer account.** Free Personal Team signing via Xcode, local builds only, 7-day expiry. No EAS device builds, no TestFlight.
- Team: 2 humans + Claude (Max). Claude writes code; humans install on phones, test in the hall, integrate, demo.

---

## 4. Team, machines, ownership

### 4.1 People

- **Person A — Mobile.** Owns `mobile/`. Only person who installs on iPhones. Mac 1. **[v4.1]** Also reviews the TypeScript half of WS0 (`mobile/src/protocol/`), owns WS7 Photon (the demo Telegram already runs on Mac 1), and records the backup video.
- **Person B — Server, dashboard, integration.** Owns `server/`, `dashboard/`, merges Claude workstreams except WS7 and the TypeScript half of WS0. Mac 2.

(Brian and Alexandre: write your names next to A and B in the repo README.)

### 4.2 Machines

| Machine | Runs |
|---|---|
| **Mac 1** | Xcode, Expo dev builds to all 3 iPhones, Claude session for mobile help |
| **Mac 2** | Postgres client, FastAPI server, dashboard dev server, `droid` CLI, cloudflared tunnel, Claude sessions for server-side workstreams; during demo: dashboard on screen |
| **Laptop for Photon** | During demo, Mac 1 (or whichever is free) shows the Corner Store owner's Telegram/Messages. |

### 4.3 Workstreams (one Claude session each, one folder each)

| ID | Workstream | Folder | Owner reviewing | Depends on |
|---|---|---|---|---|
| WS0 | Protocol spec + test vectors + shared libs | `spec/`, `server/stormcash/protocol/`, `mobile/src/protocol/` | B (Python), A (TypeScript) **[v4.1]** | — |
| WS1 | Mobile app | `mobile/` | A | WS0 |
| WS2 | Server core: settlement, ledger, Nessie, API, SSE | `server/` | B | WS0 |
| WS3 | Dashboard | `dashboard/` | B | WS2 API |
| WS4 | Town simulator | `sim/` | B | WS0, WS2 ingest function |
| WS5 | StormDesk agent | `server/stormcash/stormdesk/` | B | WS2, WS6 |
| WS6 | Chalk features + evals | `chalk/` | B | WS2 DB, WS4 |
| WS7 | Photon agent | `server/stormcash/photon/` | A **[v4.1]** | WS2, WS5 |

**Integration rule:** WS2 owns `server/stormcash/db.py`, `schema.sql`, and `app.py`. Other server workstreams add routers in their own module and B wires them in.

---

## 5. Repo layout

```
stormcash/
  README.md                  # pitch, setup, "Where Droid runs", "How we use Chalk", honest limits
  CLAUDE.md                  # points every session at this spec
  STORMCASH_BUILD_SPEC.md    # this file
  spec/
    vectors.json             # generated test vectors (§20)
    gen_vectors.py           # generates vectors.json from fixed keys
    README.md
  server/
    pyproject.toml
    schema.sql
    stormcash/
      app.py                 # FastAPI app, router wiring
      config.py              # env vars
      db.py                  # psycopg pool, helpers
      protocol/              # canonical encoding, hashing, signing, verify, rules (Python twin of mobile/src/protocol)
        encoding.py
        crypto.py
        objects.py
        rules.py             # offline checks + equivocation + merchant-knew
      settlement.py          # ingest items, cases, payouts
      ledger.py
      nessie.py
      policy.py              # signed policy list (frozen certs + merchant limits)
      detectors.py           # soft-signal candidate detectors (§13)
      sse.py
      routes/                # one module per API area
      stormdesk/             # WS5
      photon/                # WS7
    tests/
  mobile/
    app.json
    src/
      protocol/              # TS twin: encoding.ts, crypto.ts, objects.ts, rules.ts
      store/                 # SQLite: wallet, items, devicelog, peers
      transport/             # Multipeer wrapper + QR sync fallback
      screens/
      demo/                  # judge mode, demo topology, reset
    modules/sc-multipeer/    # fallback native Expo module (Swift) if the community lib fails
  dashboard/
    src/tabs/{Accounts,Cases,Town,Evals}.tsx
    src/proof/               # public "Verify it yourself" page
  sim/
    stormcash_sim/
    scenarios/
  chalk/
    features.py
    resolvers/
    evals/
  cpp/                       # C++ toolkit (off the demo path): stormcash-verify, a third verifier of the §20 vectors and case proofs; scale/, Scale Lab (simulated city-scale §16 town)
  fixtures/
    nws_helene_buncombe.json # replayed alerts, labeled
```

---

## 6. Tech stack, versions, environment setup

### 6.1 Stack

| Layer | Choice | Notes |
|---|---|---|
| Mobile | React Native + Expo SDK (latest stable), **development build** (`expo-dev-client`), New Architecture on | Expo Go cannot load native modules |
| Mobile crypto | `@noble/curves` (p256), `@noble/hashes` (sha256), `react-native-get-random-values` | Pin exact versions in `package.json` |
| Mobile storage | `expo-sqlite`, `expo-secure-store` (private key) | |
| Mobile biometrics | `expo-local-authentication` | Face ID usage string in app.json |
| Mobile QR | `react-native-qrcode-svg` (show), `expo-camera` (scan) | |
| Mobile peer link | `expo-nearby-connections` (Multipeer on iOS) **VERIFY iOS support in hour 1**; fallback: our own Expo module `modules/sc-multipeer` wrapping `MCSession`/`MCNearbyServiceAdvertiser`/`MCNearbyServiceBrowser` | |
| Mobile network detect | `expo-network` | uplink = internet reachable |
| Server | Python 3.11, FastAPI, uvicorn, psycopg 3 (pool), `cryptography`, `httpx`, `sse-starlette`, `pydantic` v2 | |
| Database | **Hosted Postgres (Neon or Supabase free tier)** | Chalk resolvers run in Chalk's cloud and must reach the DB. Local Postgres only as fallback (§22.4) |
| Public URL | `cloudflared tunnel --url http://localhost:8000` (quick tunnel, no account) | Needed for Photon webhooks and Chalk eval tasks |
| Dashboard | React + Vite + TypeScript, Tailwind, Recharts, SSE (`EventSource`) | |
| Agent | Factory Droid SDK for Python (`pip install "droid-sdk[mcp]"`), `droid` CLI on PATH, `FACTORY_API_KEY` | |
| Data/evals | Chalk (`chalk` client, `chalkcompute` for evaluations) | Sign up at chalk.ai/hackharvard |
| Messaging | Photon 2.0 (Telegram channel primary; iMessage optional) | Follow Photon docs linked from hhuh.io |
| Bank | Capital One Nessie REST API | |
| Weather | NWS API `https://api.weather.gov/alerts/active?area=NC` (needs `User-Agent` header) + replayed fixture | |

### 6.2 iPhone setup (free signing) — do Friday

1. On each iPhone: **Settings → Privacy & Security → Developer Mode → On**, restart, enter passcode.
2. Mac 1: Xcode → Settings → Accounts → add an Apple ID → a "Personal Team" appears.
3. `cd mobile && npx expo prebuild` then `npx expo run:ios --device --configuration Release`. In Xcode → target → Signing & Capabilities → Team = Personal Team, unique bundle id (e.g. `edu.bu.stormcash.<initials>`).
4. On the phone after first install: **Settings → General → VPN & Device Management → trust** the developer certificate.
5. Repeat for each phone. If Xcode refuses a device (free-team limits), sign that phone with its owner's Apple ID (different bundle id is fine; Multipeer matches by service type, not bundle id).
6. After first USB install, enable **Connect via network** in Xcode → Devices so rebuilds go over Wi-Fi.
7. Builds expire after 7 days. Irrelevant for this weekend.

**Info.plist (via app.json `ios.infoPlist`):**

```json
{
  "NSLocalNetworkUsageDescription": "StormCash talks to nearby phones to share payment records when there is no internet.",
  "NSBonjourServices": ["_stormcash._tcp", "_stormcash._udp"],
  "NSBluetoothAlwaysUsageDescription": "StormCash uses Bluetooth to reach nearby phones when there is no internet.",
  "NSCameraUsageDescription": "Scan payment QR codes.",
  "NSFaceIDUsageDescription": "Confirm payments with Face ID."
}
```

Multipeer service type: **`stormcash`** (1–15 chars, lowercase letters, digits, hyphen).

### 6.3 Environment variables (server, `.env`, never committed)

```
DATABASE_URL=postgresql://...
NESSIE_API_KEY=...
NESSIE_BASE_URL=https://api.nessieisreal.com     # [v4.2] verified; HTTP is refused
SERVER_SIGNING_KEY_PEM=...                        # P-256 private key, generated once
FACTORY_API_KEY=...
CHALK_CLIENT_ID=... / CHALK_CLIENT_SECRET=... / CHALK_ENVIRONMENT=...   # [v4.6] empty = the machine's `chalk login`
CHALK_DISABLED=0                                  # [v4.6] fallback: 1 = query_features reads Postgres only (§15.2)
PHOTON_API_KEY=... (unused; see the Photon lines below)
SPECTRUM_WEBHOOK_SECRET=...                       # [v4.5] Photon webhook signing secret (inbound HMAC)
PHOTON_BRIDGE_TOKEN=...                           # [v4.5] shared secret between the server and photon/bridge
PHOTON_BRIDGE_URL=http://127.0.0.1:8787           # [v4.5]
PHOTON_DISABLED=0                                 # [v4.5] fallback: 1 = record messages, send nothing
PUBLIC_BASE_URL=https://<cloudflared>.trycloudflare.com
NWS_USER_AGENT=StormCash HackHarvard demo (team email)
DEMO_MODE=1
NESSIE_POOL_ACCOUNT_ID=...                        # [v4.3] guarantee pool; create once: python -m stormcash.nessie_setup
NESSIE_POOL_DOLLARS=1000                          # [v4.19] what the pool is opened at (nessie_setup and every demo reset)
NESSIE_DISABLED=0                                 # [v4.3] fallback: 1 = ledger-only, no Nessie calls
API_SIG_REQUIRED=1                                # [v4.3] fallback: 0 = accept unsigned writes (§12)
BACKGROUND_TASKS=1                                # [v4.3] Nessie replay (10 s) + escrow release (60 s)
STORMDESK_RUNNER=auto                             # [v4.3] droid | fake | auto (§14.7a)
STORMDESK_MODEL=                                  # [v4.3] empty = Droid picks
STORMDESK_AUTO=1                                  # [v4.3] worker runs StormDesk on new cases and candidates
STORMDESK_REVIEW=1                                # [v4.15] a reviewer Droid checks every triage (§14.7b); 0 = off
STORMDESK_APPEAL_SESSIONS=1                       # [v4.21] a shop's appeal is one Droid session, resumed per text (§14.7c); 0 = one run per message
STORMDESK_AUTHOR=0                                # [v4.22] 1 = Droid may propose detectors as PRs (§14.7d); off by default
STORMDESK_AUTHOR_BASE=origin/main                 # [v4.22] the ref the author sandbox is a worktree of
STORMDESK_AUTHOR_MAX_CREDITS=250000               # [v4.22] an author run stops at this many Factory credits
```

The server's public key is compiled into the mobile app (`mobile/src/config.ts: SERVER_PUB`). Generate the server key once on Friday and do not rotate it.

---

## 7. Protocol: crypto, encoding, objects

### 7.1 Primitives

- **Curve:** ECDSA P-256 (secp256r1). The only curve the iPhone Secure Enclave supports.
- **Hash:** SHA-256.
- **Signature input:** sign the 32-byte SHA-256 digest of the canonical string (prehashed). Python: `ec.ECDSA(utils.Prehashed(hashes.SHA256()))`. noble: `p256.sign(digest, priv)` with the digest as the message hash (no extra hashing). **VERIFY** the noble version's API for prehash vs. message. Software signers sign deterministically (RFC 6979: Python `ec.ECDSA(..., deterministic_signing=True)`, noble's default), so the same key and digest always give the same low-S signature; the Secure Enclave signs randomly, which is fine because verifiers never compare signatures.
- **Signature format:** raw 64 bytes `r || s`, big-endian, each 32 bytes. **Signers must normalize to low-S.** Verifiers must accept both low-S and high-S (noble: `{ lowS: false }` on verify). Python `cryptography` emits DER; convert with `decode_dss_signature` and normalize S in `crypto.py`. Secure Enclave also returns DER; same helper on mobile.
- **Public keys:** SEC1 compressed, 33 bytes.
- **Random:** 16-byte nonces and ids from a CSPRNG.

### 7.2 Canonical encoding (what gets hashed and signed)

```
canonical(TYPE, f1, f2, ..., fn) = "SC1|" + TYPE + "|" + f1 + "|" + f2 + ... + "|" + fn
digest = SHA-256(UTF-8(canonical))
```

Field rendering rules (no exceptions):

| Kind | Rendering |
|---|---|
| integer | base-10 ASCII, no sign, no leading zeros, `0` for zero. Negative values are invalid. Max `2^53 − 1` (JavaScript's safe-integer limit). |
| bytes (keys, hashes, ids, nonces, sigs) | **lowercase hex** |
| string | UTF-8, NFC-normalized before rendering; must not contain `\|`, `,`, `\n`; max 48 Unicode code points after NFC (code points, not UTF-16 units) |
| list of bytes | sorted ascending by hex, joined with `,`; empty list = empty string |
| list of strings | each rendered as a string, sorted ascending by UTF-8 bytes, joined with `,`; empty list = empty string |
| enum | uppercase ASCII token matching `[A-Z][A-Z0-9_]*`, e.g. `ACCEPT`, `C6` |

`TYPE` is a domain-separation tag so no signature for one object type can be replayed as another. Besides the objects in §7.4, these derived hashes use the same encoding: `GEN` (§7.4), `DGEN` and `CONTACT` (§9.2), `PRF` (§10.2).

### 7.3 Transport encoding (JSON over QR, Multipeer and HTTP)

- JSON objects with the short keys listed below.
- **All byte fields are base64url without padding** in JSON. Converting base64url ↔ hex happens only in the codec (`objects.py` / `objects.ts`). Decoders reject padding, non-canonical base64url, and missing or unknown keys.
- The signature travels as `sig` next to the fields; it is never part of the canonical string.
- QR payload: the string `SC1:` + JSON. Error correction level L. If scanning is slow, see §23.

### 7.4 Objects

Field order below **is** the canonical order. JSON short key in brackets.

#### CERT — resident certificate (signed by server)

| # | Field | Type | Notes |
|---|---|---|---|
| 1 | cert_id [`ci`] | bytes16 | stable for the wallet's life |
| 2 | cert_ver [`cv`] | int | starts 1; +1 on Storm Mode raise, renewal, close |
| 3 | holder_pub [`hp`] | bytes33 | resident device key |
| 4 | cap_cents [`cap`] | int | 2000 always-on, 5000 Storm Mode |
| 5 | issued_at [`ia`] | int | |
| 6 | expires_at [`ea`] | int | issued_at + 72 h |
| 7 | escrow_ref [`er`] | string | Nessie escrow account id |

`TYPE = CERT`. Server signature `[sig]`.

**[v4] Versions share one chain.** Storm Mode, renewal and close all issue a new **version** of the same `cert_id`. The running total continues across versions, so a holder can never spend more than the highest cap ever issued, which the escrow covers. A merchant checks `cum ≤ cap` against whichever valid version is presented.

**Escrow release on close:** the server keeps escrow = the highest cap ever issued until every version with that cap has expired, plus a 24 h grace window. Then it refunds `escrow − settled spend` to checking.

#### MCERT — merchant certificate (signed by server)

| # | Field | Type |
|---|---|---|
| 1 | merchant_id [`mi`] | bytes16 |
| 2 | merchant_ver [`mv`] | int |
| 3 | merchant_pub [`mp`] | bytes33 |
| 4 | display_name [`dn`] | string |
| 5 | region_id [`rg`] | string |
| 6 | expires_at [`ea`] | int (issued + 30 days) |

`TYPE = MCERT`. Server signature `[sig]`.

#### REQ — payment request (signed by merchant, shown as QR)

| # | Field | Type |
|---|---|---|
| 1 | merchant_id [`mi`] | bytes16 |
| 2 | amount_cents [`amt`] | int |
| 3 | nonce [`n`] | bytes16 |
| 4 | req_expires_at [`rx`] | int (now + 120 s) |

`TYPE = REQ`. Merchant signature `[sig]`. The QR carries `{mc: MCERT, rq: REQ}` so the payer can verify the merchant offline.

#### DET — payment details (not gossiped; hashed into the tag)

| # | Field | Type |
|---|---|---|
| 1 | merchant_pub [`mp`] | bytes33 |
| 2 | nonce [`n`] | bytes16 |
| 3 | ts [`ts`] | int (payer device time) |

`details_hash = SHA-256(canonical(DET, ...))`.

#### TAG — spend tag (the only resident signature)

| # | Field | Type | Notes |
|---|---|---|---|
| 1 | cert_id [`ci`] | bytes16 | |
| 2 | counter [`k`] | int | 1, 2, 3, … |
| 3 | prev_hash [`ph`] | bytes32 | previous tag_hash; for counter 1: `GENESIS(cert_id)` |
| 4 | amount_cents [`amt`] | int | > 0 |
| 5 | cum_cents [`cum`] | int | running total including this payment |
| 6 | details_hash [`dh`] | bytes32 | |

`TYPE = TAG`. Holder signature `[sig]`. `tag_hash = SHA-256(canonical(TAG, ...))`. It is the payment id.

**[v4] Genesis:** `GENESIS(cert_id) = SHA-256(canonical(GEN, cert_id))`. It replaces v3's "certificate hash for counter 1", because certificate versions change the cert hash, but the chain must not break.

#### PAY — payment (QR from payer to merchant; relayed to server)

`{c: CERT(with sig), t: TAG(with sig), d: DET}`. A merchant stores the full PAY. Gossip carries only the TAG. **[v4.3]** The PAY itself is relayed too (store-and-forward, §10.1), so a relay's upload can settle another shop's payment; production encrypts relayed bundles to the server key (§24 Q11).

#### DLOG — device log entry [v4] (§9)

#### BUNDLE items [v4] (§10)

#### POLICY — signed policy list (replaces v3 "frozen list")

| # | Field | Type |
|---|---|---|
| 1 | policy_ver [`pv`] | int, strictly increasing |
| 2 | issued_at [`ia`] | int |
| 3 | frozen_certs [`fc`] | list of bytes16 |
| 4 | merchant_limits [`ml`] | list of strings `"<merchant_id_hex>:<cents>"`, sorted |

`TYPE = POLICY`. Server signature `[sig]`. A phone keeps the highest `policy_ver` it has verified.

#### RENEW — renewal request (signed by holder)

| # | Field | Type |
|---|---|---|
| 1 | cert_id [`ci`] | bytes16 |
| 2 | chain_head [`ch`] | bytes32 (latest tag_hash or GENESIS) |
| 3 | counter [`k`] | int (latest counter, 0 if none) |
| 4 | ts [`ts`] | int |

`TYPE = RENEW`. Holder signature `[sig]`. The server answers with a new CERT version (expiry +72 h) unless the cert is frozen.

#### RCPT — server receipt

| # | Field | Type |
|---|---|---|
| 1 | ts [`ts`] | int |
| 2 | item_ids [`ids`] | list of bytes32 (full item ids, §10.2) |

`TYPE = RCPT`. Server signature `[sig]`. Phones delete carried items whose ids appear in a verified receipt.

#### PROOF — equivocation proof

`{a: TAG, b: TAG, rule: "SAME_COUNTER"|"BROKEN_LINK"|"TOTAL_BACKWARDS"}`. Self-proving: anyone with the cert's `holder_pub` can check it. No extra signature. Builders order the tags so `a.counter ≤ b.counter` (ties by tag_hash) and name the lowest-numbered rule that fires. A PROOF is valid when both tags verify under `holder_pub`, share a `cert_id`, and break the named rule, in either order.

---

## 8. Offline checks and fraud rules

### 8.1 Payer-side checks (resident phone, before signing)

1. MCERT has a valid server signature and is not expired.
2. REQ signature matches `merchant_pub`; `req_expires_at > now - 600`.
3. `amount_cents ≤ cap − cum_so_far` (else show "Over your limit").
4. Show "Pay <display_name> $X.XX", require Face ID, then build DET, TAG and PAY, increment counter, persist the wallet **before** showing the payment QR.

### 8.2 Merchant offline checks, in order (v3 checks, numbered for UI copy)

| # | Check | Failure copy on the red screen |
|---|---|---|
| C1 | CERT server signature valid | "Certificate not issued by StormCash" |
| C2 | CERT not expired (10-min clock tolerance) and `cert_id` not in policy `frozen_certs` | "Certificate expired" / "Certificate frozen" |
| C3 | TAG `cert_id` is the CERT's and the TAG signature matches CERT `holder_pub` | "Signature doesn't match" |
| C4 | `details_hash` matches DET; DET names **this** merchant's key and the **open** request's nonce; TAG amount = REQ amount; REQ not expired | "Payment is for a different request" |
| C5 | `amount > 0`, `cum ≥ amount`, `cum ≤ cap`; amount ≤ merchant limit from policy (if any) | "Over certificate cap" / "Over this shop's limit" |
| C6 | Against every stored tag for this cert: no equivocation (§8.3), and `counter >` the highest counter seen | "These funds were already spent nearby (rule: …). Certificate flagged." |

Within a check, conditions run in this order and the first failure wins. Each failure has a machine reason token (used in logs, vectors and both protocol libraries; the UI shows the copy above):

| Check | Reason tokens, in evaluation order |
|---|---|
| C1 | `BAD_CERT_SIG` |
| C2 | `EXPIRED` (`now > expires_at + 600`), `FROZEN` (`cert_id` in the highest verified policy's `frozen_certs`) |
| C3 | `WRONG_CERT` (TAG `cert_id` ≠ CERT `cert_id`), `BAD_TAG_SIG` |
| C4 | `DETAILS_MISMATCH` (`details_hash` ≠ SHA-256 of canonical DET), `WRONG_MERCHANT`, `WRONG_NONCE`, `WRONG_AMOUNT`, `REQ_EXPIRED` (`now > req_expires_at`, merchant's own clock, no tolerance) |
| C5 | `BAD_AMOUNT` (`amount ≤ 0` or `cum < amount`), `OVER_CAP`, `OVER_LIMIT` |
| C6 | `INVALID_TAG` (single-tag validity, §8.3); then `SAME_COUNTER` / `BROKEN_LINK` / `TOTAL_BACKWARDS` against stored tags of this cert, taken in (counter, tag_hash) order, first conflict wins; then `COUNTER_NOT_NEW` (`counter ≤` the highest stored counter, e.g. a replayed payment) |

All six pass: green screen "Verified. Backed by Capital One, $<cum> of $<cap> used." Then the merchant stores the PAY, appends a DLOG `ACCEPT` (§9), and queues the TAG for gossip.

Any check fails: red screen naming the check; if C6 fails, store the attempted PAY as evidence, append DLOG `REFUSE`, build a PROOF and gossip it at top priority.

### 8.3 Equivocation rules (hard, self-proving)

For two tags A and B with the same `cert_id`, ordered so that `A.counter ≤ B.counter`:

| Rule | Condition |
|---|---|
| **R1 SAME_COUNTER** | `A.counter == B.counter` and `tag_hash(A) != tag_hash(B)` |
| **R2 BROKEN_LINK** | `B.counter == A.counter + 1` and `B.prev_hash != tag_hash(A)` |
| **R3 TOTAL_BACKWARDS** | `B.counter > A.counter` and `B.cum − B.amount < A.cum` |

Tags with different `cert_id`s never equivocate. If a pair breaks more than one rule (R2 and R3 can both hold), report the lowest-numbered one.

Plus single-tag validity: `counter ≥ 1`, `amount > 0`, `cum ≥ amount`, and counter 1 must have `prev_hash == GENESIS(cert_id)` and `cum == amount`.

Server-only hard rules:

| Rule | Condition |
|---|---|
| **R4 OVER_CAP** | the highest `cum` among a cert's settled tags exceeds the highest `cap_cents` of any issued version |
| **R5 MERCHANT_KNEW** [v4] | §9.4 |
| **R6 LOG_TAMPER** [v4] | a device's DLOG chain has a fork (two entries with the same seq) or a broken prev_hash link |

Any hard rule opens a **case**, freezes the certificate (R1–R4) or the merchant's pool eligibility (R5, R6), and publishes a new POLICY version. **No AI is involved.**

### 8.4 Loss bound (say it out loud)

A cheater can take at most the cap once from each shop no tag has reached, before the freeze spreads. With a $50 cap and five unreached shops, the worst case is $250 per cheater, with their signatures as evidence. The always-on cap is $20, and merchants can set a lower per-payment limit.

---

## 9. Device logs, contacts and the "merchant knew" rule [v4]

### 9.1 Why

The guarantee pool pays merchants for accepted payments, including double spends they couldn't have known about. A colluding merchant can keep their phone deliberately "unreached" (Bluetooth off), accept rolled-back payments, and get paid from the pool. Device logs make "what did you know, and when" provable.

### 9.2 DLOG entry (every device keeps one; signed by the device key)

The device key is the holder key for residents and the merchant key for merchants.

| # | Field | Type |
|---|---|---|
| 1 | device_pub [`dp`] | bytes33 |
| 2 | seq [`q`] | int, starts 1, +1 per entry |
| 3 | prev_hash [`ph`] | bytes32: previous entry hash; for seq 1: `SHA-256(canonical(DGEN, device_pub))` |
| 4 | ts [`ts`] | int |
| 5 | kind [`kd`] | `ACCEPT` \| `REFUSE` \| `CONTACT` |
| 6..n | body | per kind, below |

`TYPE = DLOG`. Device signature. `entry_hash = SHA-256(canonical(DLOG, ...))`.

**Body per kind (fields 6..n):**

| Kind | Body fields |
|---|---|
| `ACCEPT` | tag_hash [`th`] (bytes32), cert_id [`ci`] (bytes16), held_ids [`hi`] (list of bytes32: every tag_hash **for this cert_id** the device held at acceptance) |
| `REFUSE` | tag_hash [`th`] (bytes32), cert_id [`ci`] (bytes16), check [`ck`] (enum: `C1`…`C6`) |
| `CONTACT` | contact_id [`cid`] (bytes32), peer_pub [`pp`] (bytes33), sent_ids [`si`] (list of bytes8), recv_ids [`ri`] (list of bytes8), sent_overflow [`so`] (int), recv_overflow [`ro`] (int) |

- Body keys sit in the same flat JSON object as the header (as in §12.2), with the signature in `sig`. Body fields of other kinds are absent.
- `sent_ids` / `recv_ids` are the first 8 bytes of the item ids (§10.2) of **TAG and PROOF items only**, capped at 200 each. Anything beyond the cap is counted in `*_overflow`. **[v4.3]** A PAY item counts as its TAG (same id).
- `contact_id = SHA-256(canonical(CONTACT, pub_low, pub_high, nonce_low, nonce_high))`. The pubs are sorted bytewise; each side's HELLO nonce is ordered by its pub. Both sides compute the same id, so the server can pair the two logs of one meeting. The two pubs must differ.

### 9.3 Both sides log every contact

Each side of a sync session (§10) writes one CONTACT entry when the session ends. A merchant cannot hide a contact, because the peer's signed log shows it. But a dishonest peer could also *claim* a contact that never happened, since its log is only its own testimony. So the server treats a **one-sided** contact as **weak evidence** (a soft-signal input only) and a **paired** contact (both sides logged the same `contact_id`) as **strong evidence**, usable by hard rule R5.

### 9.4 R5 MERCHANT_KNEW (hard)

For a payment P (tag `z`, cert `C`) accepted by merchant M at time `t_accept`, if there exists a tag `x` of cert `C` such that `x` and `z` violate R1–R3, and **either**:

- (a) M's own `ACCEPT` entry for `z` lists `x` in `held_ids`, **or**
- (b) a **paired** CONTACT (both sides logged it) between M and any peer, with `ts < t_accept`, where the peer's `sent_ids` or M's `recv_ids` contains `id8(x)`,

then M knowingly accepted a double spend: P is marked `denied_knowing`, it is **not** paid from the guarantee pool (escrow still pays if the payment is first on the honest chain), and a case `MERCHANT_KNEW` opens with M's own signatures as evidence.

Precisely: `id8(x)` is the first 8 bytes of `tag_hash(x)`. A contact is **paired** when M logged a CONTACT with that `contact_id` naming the peer as `peer_pub`, and the peer logged one with the same `contact_id` naming M. It is dated by M's own CONTACT entry, so `ts` and `t_accept` (M's ACCEPT entry for `z`) both come from M's clock. A contact only one side logged never fires R5, even if it is M's own entry. Clause (a) is checked before (b); conflicting tags are taken in (counter, tag_hash) order.

(a) catches an app that was modified to skip C6 but still logs honestly. (b) catches an app that also lies in its own log, using the peer's log and M's own contact entry.

### 9.5 R6 LOG_TAMPER (hard)

On ingest, the server verifies each device's chain. Two entries with the same `seq` and different hashes, or a broken `prev_hash`, open a `LOG_TAMPER` case. For a merchant, pool payouts are suspended pending review.

Entries arrive out of order by gossip, so a missing `seq` is not tampering: a link is checked only where the previous entry is known (seq 1 against `DGEN`). Scan by ascending `seq`; at each `seq`, a fork is reported before a broken link.

### 9.6 Storage

DLOG entries are ~300 bytes. They are synced like any other item (§10) and deleted after a receipt.

---

## 10. Gossip and store-and-forward relay over Multipeer [v4]

### 10.1 Model

Delay-tolerant networking with epidemic routing: every phone carries everything it has not seen a receipt for, and hands it to every phone it meets. Any phone that gets internet uploads what it carries. The same mechanism moves items **up** (payments, tags, proofs, logs, renewal requests) and **down** (receipts, policy, renewed certs).

### 10.2 Items

Every syncable thing is an **item**: `{kind, body, path}`.

| kind | body | item_id = SHA-256 of | Priority |
|---|---|---|---|
| `PROOF` | PROOF | `canonical(PRF, tag_hash(a), tag_hash(b))` with the two tag hashes sorted | 1 |
| `POLICY` | POLICY | canonical POLICY | 2 |
| `RCPT` | RCPT | canonical RCPT | 2 |
| `CERT` | CERT version (renewal response) | canonical CERT | 2 |
| `PAY` | PAY | tag_hash | 3 |
| `DLOG` | DLOG entry | entry_hash | 3 |
| `RENEW` | RENEW | canonical RENEW | 3 |
| `TAG` | TAG | tag_hash | 4 |

Note: `PAY` and `TAG` for one payment share an id on purpose: once a PAY is held, the TAG is redundant.

**[v4.3] PAY supersedes TAG.** Because they share an id, a phone that holds only the TAG would never ask for the PAY, and the PAY could not travel past the shop (found by the simulator: two thirds of payments never reached the server). So: a phone holding only the TAG for an id still requests and stores the PAY, which replaces the TAG; and the server puts a TAG's id in a RCPT only once it holds the PAY, because a receipted id makes phones delete the PAY too. Until then the TAG is stored but not receipted, and phones keep carrying it. "canonical X" means the object's digest without its signature. `id8` is the first 8 bytes of an item id.

`path` is **unsigned metadata**: an array of `[device_short_id, ts]` appended by each carrier. `device_short_id` = first 4 bytes of the device pub as hex. It is only for the dashboard's hop display, never for security.

### 10.3 Sync session (runs on every Multipeer connection; also over QR sync)

```
1. HELLO      → {v:1, dp: device_pub, role, n: nonce16, pv: policy_ver, inv: [id8...], pays: [id8...] }   (pays [v4.3]: the inv ids held as PAY)
2. HELLO      ← same from the peer
3. WANT       → [id8 the peer has and I don't, plus ids in the peer's `pays` I hold only as TAG]  (both directions)
4. ITEMS      → items for the requested ids, highest priority first, ≤ 64 KB per message, chunked
5. DONE       → {}   both sides
6. Each side appends one DLOG CONTACT entry (§9.2) and updates `path` on items it received.
```

- `inv` lists id8 of every item the device holds (cap 5,000; send priority 1–3 first if over).
- Policy: if the peer's `pv` is higher, request it explicitly.
- Every received item is **verified before it is stored** (signatures, cert chain). Invalid items are dropped and the peer is not trusted for the rest of the session.
- The session times out after 15 s.

### 10.4 Retention

- Keep each item until a verified RCPT covers it, or for 7 days.
- Storage cap 5,000 items; evict the lowest priority, oldest first. Never evict PROOF or POLICY.
- Tags for a cert are deleted 72 h after the cert's last known version expires.

### 10.5 Upload (any phone with internet)

When `expo-network` reports internet: `POST /v1/sync` with every item that has no receipt. The response contains RCPT, the latest POLICY, CERT versions for any RENEW the phone carried, and nothing else. Store them as items so they gossip back down.

### 10.6 Demo topology (demo mode only)

All 3 phones on a table are in range of each other. In demo mode, each phone only accepts sessions from peers on its allowlist:

```
Pharmacy ↔ Maya ↔ Gas Station          (Pharmacy and Gas Station never link directly)
```

So the pharmacy's records reach the gas station only through Maya's phone, and the gas station's upload carries the pharmacy's payment 2 hops. The dashboard draws the path from `path` metadata: "Pharmacy → Maya → Gas Station → server · 2 hops · 4 min".

The allowlist lives in `mobile/src/demo/topology.ts`, keyed by device label, toggled in the hidden demo menu.

### 10.7 QR sync fallback

If Multipeer is unreliable, the same session runs over QR: each side shows HELLO+inventory as a QR sequence, then the items needed for the demo (only a few tags, a proof, a policy) as QR frames. It is slow but fully offline, and still writes CONTACT entries. Build a "Sync by QR" button on the Records screen.

---

## 11. Server: schema, settlement, ledger, Nessie

### 11.1 Schema (`server/schema.sql`)

```sql
-- Entities
CREATE TABLE regions (
  region_id TEXT PRIMARY KEY,           -- e.g. 'asheville-downtown'
  display_name TEXT NOT NULL,
  county TEXT NOT NULL,                 -- 'Buncombe'
  x INT NOT NULL, y INT NOT NULL, w INT NOT NULL, h INT NOT NULL  -- map rectangle on town grid
);

CREATE TABLE residents (
  resident_id UUID PRIMARY KEY,
  display_name TEXT NOT NULL,
  holder_pub BYTEA UNIQUE NOT NULL,
  region_id TEXT REFERENCES regions,
  nessie_customer_id TEXT,
  checking_account_id TEXT,
  escrow_account_id TEXT,
  simulated BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE merchants (
  merchant_id BYTEA PRIMARY KEY,        -- 16 bytes
  display_name TEXT NOT NULL,
  merchant_pub BYTEA UNIQUE NOT NULL,
  region_id TEXT REFERENCES regions,
  x INT, y INT,                         -- position on town map
  nessie_account_id TEXT,
  per_payment_limit_cents INT,          -- NULL = none
  pool_eligible BOOLEAN NOT NULL DEFAULT TRUE,
  simulated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE merchant_contacts (        -- Photon mapping
  merchant_id BYTEA REFERENCES merchants,
  channel TEXT NOT NULL,                -- 'telegram' | 'imessage' | 'sms'
  handle TEXT NOT NULL,
  PRIMARY KEY (channel, handle)
);

CREATE TABLE resident_contacts (        -- [v4.13] Photon mapping for residents (FREEZE by text, §17.2)
  resident_id UUID NOT NULL REFERENCES residents,
  channel TEXT NOT NULL,                -- 'telegram' | 'imessage' | 'sms'
  handle TEXT NOT NULL,
  PRIMARY KEY (channel, handle)
);

CREATE TABLE certificates (
  cert_id BYTEA NOT NULL,
  cert_ver INT NOT NULL,
  resident_id UUID REFERENCES residents,
  holder_pub BYTEA NOT NULL,
  cap_cents INT NOT NULL,
  issued_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL,
  escrow_ref TEXT NOT NULL,
  server_sig BYTEA NOT NULL,
  PRIMARY KEY (cert_id, cert_ver)
);
CREATE TABLE cert_status (
  cert_id BYTEA PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('active','frozen','closing','closed')),
  max_cap_cents INT NOT NULL,
  frozen_at BIGINT,
  storm_mode BOOLEAN NOT NULL DEFAULT FALSE,
  storm_mode_at BIGINT,
  owner_freeze_at BIGINT                -- [v4.13] the owner texted FREEZE (§17.2); cap_drain's owner_freeze_request
);

-- Protocol data
CREATE TABLE tags (                     -- every tag the server has seen (from PAY or gossip)
  tag_hash BYTEA PRIMARY KEY,
  cert_id BYTEA NOT NULL,
  counter INT NOT NULL,
  prev_hash BYTEA NOT NULL,
  amount_cents INT NOT NULL,
  cum_cents INT NOT NULL,
  details_hash BYTEA NOT NULL,
  sig BYTEA NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON tags (cert_id, counter);

CREATE TABLE payments (
  tag_hash BYTEA PRIMARY KEY REFERENCES tags,
  cert_id BYTEA NOT NULL,
  merchant_id BYTEA NOT NULL REFERENCES merchants,
  nonce BYTEA NOT NULL,
  device_ts BIGINT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  relay_device BYTEA,                   -- pub of the uploader
  hops INT,
  path JSONB,
  status TEXT NOT NULL CHECK (status IN
    ('pending','settled','held','denied_knowing','refused_evidence','invalid')),
  funded_escrow_cents INT NOT NULL DEFAULT 0,
  funded_pool_cents INT NOT NULL DEFAULT 0
);
CREATE INDEX ON payments (merchant_id, device_ts);
CREATE INDEX ON payments (cert_id);

CREATE TABLE device_log (
  device_pub BYTEA NOT NULL,
  seq INT NOT NULL,
  entry_hash BYTEA NOT NULL,
  prev_hash BYTEA NOT NULL,
  ts BIGINT NOT NULL,
  kind TEXT NOT NULL,
  body JSONB NOT NULL,
  sig BYTEA NOT NULL,
  PRIMARY KEY (device_pub, seq, entry_hash)   -- allows storing forks as evidence
);
CREATE INDEX ON device_log (device_pub, ts);

CREATE TABLE contacts (                 -- derived from CONTACT entries
  contact_id BYTEA NOT NULL,
  device_pub BYTEA NOT NULL,
  peer_pub BYTEA NOT NULL,
  ts BIGINT NOT NULL,
  sent_ids BYTEA[] NOT NULL,
  recv_ids BYTEA[] NOT NULL,
  paired BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (contact_id, device_pub)
);
CREATE INDEX ON contacts (device_pub, ts);

-- Hard cases (deterministic)
CREATE TABLE cases (
  case_id BIGSERIAL PRIMARY KEY,
  rule TEXT NOT NULL CHECK (rule IN
    ('SAME_COUNTER','BROKEN_LINK','TOTAL_BACKWARDS','OVER_CAP','MERCHANT_KNEW','LOG_TAMPER')),
  cert_id BYTEA,
  merchant_id BYTEA,
  device_pub BYTEA,
  tag_a BYTEA, tag_b BYTEA,
  evidence JSONB NOT NULL,              -- ids of everything that proves it
  detected_where TEXT NOT NULL CHECK (detected_where IN ('offline','server')),
  exposure_cents INT NOT NULL DEFAULT 0,
  case_file_md TEXT,                    -- written by StormDesk
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Soft flags (detector candidates + agent verdicts)
CREATE TABLE candidates (
  candidate_id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('merchant_silence','cap_drain','region_dark')),
  subject_id TEXT NOT NULL,             -- merchant_id hex | cert_id hex | region_id
  window_start BIGINT NOT NULL, window_end BIGINT NOT NULL,
  features JSONB NOT NULL,              -- detector inputs, frozen at creation
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, subject_id, window_start)
);

CREATE TABLE flags (                    -- StormDesk output (one per candidate)
  flag_id BIGSERIAL PRIMARY KEY,
  candidate_id BIGINT REFERENCES candidates,
  kind TEXT NOT NULL,                   -- may be 'none' (agent dismissed)
  severity TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  evidence_ids TEXT[] NOT NULL,
  exposure_cents INT NOT NULL,
  summary TEXT NOT NULL,
  proposed_action TEXT NOT NULL,
  citations_valid BOOLEAN NOT NULL,
  agent_session_id TEXT,
  agent_transcript JSONB,               -- tool calls for replay on dashboard
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','rejected','dismissed','invalid')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  review JSONB,                         -- [v4.15] the reviewer's second opinion (§14.7b)
  agents_disagree BOOLEAN NOT NULL DEFAULT FALSE -- [v4.15] a valid review didn't agree: open for a person
);

CREATE TABLE stormdesk_runs (           -- [v4.3] every StormDesk run, for replay and audit (§14.7, §14.8)
  run_id BIGSERIAL PRIMARY KEY,
  job TEXT NOT NULL CHECK (job IN ('investigate','triage','respond','review','author')), -- [v4.15] review (§14.7b), [v4.22] author (§14.7d)
  case_id BIGINT REFERENCES cases,
  candidate_id BIGINT REFERENCES candidates,
  merchant_id BYTEA,
  runner TEXT NOT NULL,                 -- 'droid' | 'fake' (a fake run is never shown as an agent result)
  status TEXT NOT NULL CHECK (status IN ('running','succeeded','invalid','failed')),
  output JSONB,                         -- the structured output (Flag / CaseFile / AppealReply / Review)
  citations_valid BOOLEAN,
  transcript JSONB NOT NULL DEFAULT '{}', -- {runner, steps: [{tool, input, ok}], missing_citations, error}
  session_id TEXT,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE approvals (
  approval_id BIGSERIAL PRIMARY KEY,
  flag_id BIGINT REFERENCES flags,
  decision TEXT NOT NULL CHECK (decision IN ('approve','reject')),
  operator TEXT NOT NULL,
  note TEXT,
  executed_actions JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (                 -- Photon conversations
  message_id BIGSERIAL PRIMARY KEY,
  merchant_id BYTEA REFERENCES merchants,
  resident_id UUID REFERENCES residents, -- [v4.13] a resident's thread (FREEZE by text); merchant_id is then NULL
  flag_id BIGINT REFERENCES flags,
  direction TEXT NOT NULL CHECK (direction IN ('out','in')),
  channel TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Money
CREATE TABLE payouts (
  payout_id BIGSERIAL PRIMARY KEY,
  tag_hash BYTEA REFERENCES payments,
  merchant_id BYTEA NOT NULL,
  amount_cents INT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('escrow','pool')),
  nessie_transfer_id TEXT,              -- [v4.2] deposit id of the Nessie withdrawal + deposit pair
  status TEXT NOT NULL CHECK (status IN ('queued','pending','executed','failed','ledger_only','held')),  -- [v4.3] held: an approved hold_pool_payout
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ledger_entries (
  entry_id BIGSERIAL PRIMARY KEY,
  txn_id UUID NOT NULL,
  account TEXT NOT NULL,
  debit_cents INT NOT NULL DEFAULT 0,
  credit_cents INT NOT NULL DEFAULT 0,
  ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE nessie_calls (             -- feeds the dashboard call log
  call_id BIGSERIAL PRIMARY KEY,
  method TEXT, path TEXT, request JSONB, status INT, response JSONB,
  summary TEXT,                         -- "Escrow → Pharmacy, $12 (withdrawal + deposit)"
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE nessie_moves (             -- [v4.3] one Nessie withdrawal + deposit pair per money movement (§11.4)
  txn_id UUID PRIMARY KEY,              -- ledger txn_id; also in both Nessie descriptions
  from_account_id TEXT NOT NULL,        -- Nessie account ids
  to_account_id TEXT NOT NULL,
  amount_cents INT NOT NULL,            -- whole dollars only
  summary TEXT NOT NULL,
  payout_id BIGINT REFERENCES payouts,  -- set for merchant payouts
  withdrawal_id TEXT,
  deposit_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('queued','executed')),
  attempts INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE nessie_pool_accounts (     -- [v4.19] the guarantee pool's Nessie account: the newest row is the current pool (§11.4)
  pool_id BIGSERIAL PRIMARY KEY,
  account_id TEXT UNIQUE NOT NULL,      -- Nessie account id
  customer_id TEXT,                     -- the "StormCash Operator" customer
  opening_cents INT NOT NULL,           -- the balance it was opened at (whole dollars)
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policy_versions (
  policy_ver INT PRIMARY KEY,
  issued_at BIGINT NOT NULL,
  frozen_certs BYTEA[] NOT NULL,
  merchant_limits TEXT[] NOT NULL,
  server_sig BYTEA NOT NULL
);

CREATE TABLE uploads (                  -- one row per /v1/sync call
  upload_id BIGSERIAL PRIMARY KEY,
  device_pub BYTEA NOT NULL,
  region_id TEXT,
  item_count INT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  simulated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE weather_alerts (
  alert_id TEXT PRIMARY KEY,
  region_id TEXT REFERENCES regions,
  event TEXT NOT NULL,                  -- 'Hurricane Warning', 'Flash Flood Warning'
  severity TEXT,
  onset BIGINT, expires BIGINT,
  source TEXT NOT NULL CHECK (source IN ('live','replayed')),
  raw JSONB
);
```

### 11.2 Settlement (`settlement.py: ingest_items(device_pub, items) -> SyncResponse`)

One function, used by `/v1/sync`, the simulator, and tests. Idempotent: re-ingesting the same items changes nothing.

For each item, in priority order:

1. **Verify.** Signatures, cert chain (server sig), merchant cert. Invalid → drop, count it.
2. **TAG / PAY:** upsert into `tags` (dedupe by tag_hash). Run R1–R3 against every stored tag of that cert. Any hit → open a case (`detected_where='server'` unless the matching PROOF item was already received from a phone, then `'offline'`), set `cert_status='frozen'`, publish a new POLICY.
3. **PAY:** insert into `payments` with status `pending`, then decide:
   - R5 MERCHANT_KNEW true → `denied_knowing`, no pool funding.
   - Merchant has an **approved** `hold_pool_payout` action → `held`.
   - Otherwise **pay**: `escrow_avail = max_cap − already_paid_from_escrow(cert)`; `from_escrow = min(amount, escrow_avail)`; `from_pool = amount − from_escrow`. Record each payout in Nessie as a withdrawal + deposit pair (§11.4); set `settled`.
   - R4 OVER_CAP check after payment.
4. **PROOF:** store both tags (step 2 handles the case).
5. **DLOG:** verify the chain against stored entries for that device (R6). Insert. For CONTACT entries, upsert `contacts` and mark `paired` when both sides exist. After inserting, re-run R5 for that device's accepted payments whose certs have cases.
6. **RENEW:** if the cert isn't frozen, issue CERT version `+1`, expiry now + 72 h, same cap as the current max version.
7. Collect every accepted item id into an RCPT; return `{rcpt, policy, certs}`.
8. Emit SSE events (§12.3) for everything that changed.

After ingest, call `detectors.run_incremental()` (§13), which may create candidates, which enqueue StormDesk jobs.

**[v4.3] Ingest details (`settlement.py`).**
- Order: priority, and within priority 3 `DLOG` → `PAY` → `RENEW`, so a merchant's `REFUSE` entry (and its contacts, for R5) is stored before its PAY. **[v4.4]** An upload is stored in one transaction, one upload at a time (an advisory lock); every item is checked before anything of it is written and runs under its own savepoint, so an invalid item is dropped, left out of the RCPT and leaves nothing behind. (Before v4.4 each item had its own transaction.)
- **[v4.4] Round trips.** The hosted DB costs ~30 ms a round trip, so the upload's transaction runs in pipeline mode (`db.pipelined`): DLOG entries are inserted as one batch, everything the PAY and TAG checks read is fetched once per upload and kept current as items are stored, the R5 re-check's reads go with the DLOG batch, and the detectors' reads go with the COMMIT (evaluated after it, so a detector failure still can't fail a sync). Paths that open a case use the plain per-query code and read again after it. A seed-42 town stored this way is identical, table by table, to one stored item by item.
- A verified PAY whose tag fails single-tag validity is stored with status `invalid` and not paid (a merchant skipped C5/C6). A PAY over the cap is settled like any other, so R4 can catch it after payment. A PAY whose tag the same merchant logged as `REFUSE` is `refused_evidence` and not paid. PAYs naming an unregistered merchant are dropped.
- `escrow_avail` is the escrow's ledger balance, which equals `max_cap − already_paid_from_escrow` until a refund on close lowers it.
- `payments.hops = len(path) − 1`; `relay_device` is the uploader.
- RENEW: a renewal the latest version already postdates (`issued_at ≥ RENEW.ts − 600`) gets that version back instead of a new one, so re-ingesting is idempotent.
- The response always carries a POLICY: version 1 (empty lists) is issued the first time one is needed.

**[v4.3] Cases (`cases.py`).**
- A new tag is checked against the stored tags of its cert; the first conflict opens one case per tag pair (stored ordered as in a PROOF). A PROOF item opens its case before its tags are stored, so a pair a phone found first is `detected_where='offline'`. Re-ingesting opens nothing new.
- R1–R4 freeze the cert and publish the next POLICY (all frozen certs + all `per_payment_limit_cents` as merchant limits), serialized by an advisory lock. R5 and R6 set `merchants.pool_eligible = false` and publish nothing, since POLICY carries neither.
- R5 runs when a PAY is ingested, again for a merchant's payments when its log or a peer's CONTACT naming it arrives, and for every payment of a cert when an equivocation case opens on it (a conflicting TAG can arrive after the PAY). Money already paid stays paid; the case records it.
- A `denied_knowing` payment gets no pool money. Escrow still pays it only if it is first on the honest chain: its counter is lower than every tag it conflicts with.
- A merchant without pool eligibility gets the escrow share only; a payment that needed pool money is `held`.
- Exposure: R1–R3 the later tag's amount, R4 `cum − max cap`, R5 the payment's amount.

### 11.3 Ledger

Every money movement writes a balanced pair (one debit, one credit) under one `txn_id`. Account names:

| Account | Meaning |
|---|---|
| `checking:<resident>` | resident's Nessie checking (mirror) |
| `escrow:<cert_id>` | locked funds for a certificate |
| `merchant:<merchant_id>` | merchant's Nessie account (mirror) |
| `pool` | guarantee pool |
| `fraud_receivable:<cert_id>` | what a cheater owes the pool |
| `pool_recoveries` | offset for receivables |

| Event | Debit | Credit |
|---|---|---|
| Lock escrow / top up | `escrow:<cert>` | `checking:<res>` |
| Settle from escrow | `merchant:<m>` | `escrow:<cert>` |
| Settle from pool | `merchant:<m>` | `pool` |
| …and book the receivable | `fraud_receivable:<cert>` | `pool_recoveries` |
| Refund on close | `checking:<res>` | `escrow:<cert>` |

Invariant test: for every `txn_id`, `sum(debit) == sum(credit)`. Show "Ledger balanced ✓" on the Accounts tab.

### 11.4 Nessie integration (`nessie.py`)

**[v4.2] Verified on Oct 16 against the live API and `https://nessieisreal.com/nessie-openapi-spec.yaml`.** The current Nessie differs from what v3 assumed:

- An account's `balance` is set when the account is created and **never changes**. Transfers, withdrawals and deposits are records attached to an account; they don't move the balance. `PUT /accounts/{id}` only accepts `nickname`.
- Transfers have **no payee** (`medium` and `payee_id` are rejected) and stay `pending`. Don't use `/transfers`.
- Amounts are **integer dollars**. `12.34` is silently stored as `12`.
- Base URL is `https://api.nessieisreal.com`. HTTP (port 80) is refused. Auth is `?key=` on every call.

| Purpose | Call |
|---|---|
| Create customer | `POST /customers?key=` `{first_name, last_name, address: {street_number, street_name, city, state, zip}}` (all strings) → `objectCreated._id` |
| Create account | `POST /customers/{id}/accounts?key=` `{type: "Checking", nickname, rewards: 0, balance: <int dollars>}` → `objectCreated._id` |
| Get account | `GET /accounts/{id}?key=` → `balance` is the opening balance |
| Money out | `POST /accounts/{id}/withdrawals?key=` `{medium: "balance", transaction_date: "YYYY-MM-DD", status: "completed", amount: <int dollars>, description}` |
| Money in | `POST /accounts/{id}/deposits?key=` (same body) |
| List | `GET /accounts/{id}/withdrawals?key=`, `GET /accounts/{id}/deposits?key=` |

**Moving money is a matched pair.** Every movement in §11.3 (lock or top up escrow, settle from escrow, settle from pool, refund on close) is one withdrawal on the source account and one deposit on the destination account, both `completed`, both with the description `"SC <txn_id> <summary>"` so the pair links to the ledger `txn_id`. `payouts.nessie_transfer_id` stores the deposit id; both ids are in `nessie_calls`.

**Balances.** `nessie_balance(account) = opening balance + Σ deposits − Σ withdrawals`, read live from Nessie (`GET /accounts/{id}`, `/deposits`, `/withdrawals`) and cached ≤ 10 s. The Accounts tab labels these "from Nessie transactions". Open escrow and merchant accounts at $0 and the pool at its full funding, so every later change is a visible Nessie record.

**[v4.3] Guarantee pool account.** `python -m stormcash.nessie_setup [dollars]` creates the "StormCash Operator" customer and a "Guarantee Pool" account opened at its full funding (default $1000) and prints `NESSIE_POOL_ACCOUNT_ID=...` for `.env`. Without it, pool-funded payouts are `ledger_only`. **[v4.19]** The current pool is the newest `nessie_pool_accounts` row, else `NESSIE_POOL_ACCOUNT_ID` (`nessie.pool_account_id`); `nessie_setup` records the account it creates there. Every demo reset opens a fresh "Guarantee Pool" account under the current pool's customer at `NESSIE_POOL_DOLLARS` (default $1000), logs the open call in `nessie_calls` and records it as the current pool, so the pool's Nessie records start clean. The old account stays in Nessie untouched; nothing rewrites history. No pool configured means no pool is opened (pool money stays ledger only).

**Whole dollars.** `cents_to_dollars(cents)` returns an `int` and raises if `cents % 100 != 0`; it never rounds. A real-merchant payout that isn't a whole dollar amount is recorded `ledger_only` with the summary "not whole dollars, ledger only". Demo payments use whole dollars ($12). Simulated money never touches Nessie, so it can use any cents.

Account mapping:

| Nessie account | Owner |
|---|---|
| Checking | each real resident (Maya) |
| StormCash escrow | each real resident (one escrow account per resident, used by their cert) |
| Guarantee pool | a "StormCash Operator" customer |
| Merchant account | each real merchant (Pharmacy, Gas Station). Corner Store is simulated (§16.3) and ledger-only. |

Rules:
- **Only real demo entities touch Nessie.** Simulated residents and merchants (`simulated=true`) are **ledger-only** (`payouts.status='ledger_only'`), or the 40-shop town would hit rate limits.
- Every call is logged to `nessie_calls` with a human summary for the dashboard.
- **Fallback:** if either half of a pair errors or times out (3 s), queue the payout (`status='queued'`) and keep the ledger moving. A background task replays queued payouts every 10 s, creating only the missing half (check by the `txn_id` in the description). The Accounts tab shows "Nessie queued: n".
- **[v4.3] How the queue works.** Each movement is written as a `nessie_moves` row (`queued`) in the same DB transaction as its ledger pair, and executed right after commit. The row keeps the withdrawal and deposit ids as they are created; on a retry the server first looks for a record whose description starts with `SC <txn_id>` before creating a half, so a half that succeeded without a response is never repeated. When both ids exist the row is `executed`, and a linked payout (`payout_id`) becomes `executed` with `nessie_transfer_id` = the deposit id. Escrow locks, top-ups and refunds use the same queue.
- **[v4.3] Account creation** (register) is not queued: if Nessie is down the request answers 503. `NESSIE_DISABLED=1` switches every entity to ledger-only (`escrow_ref = "ledger-only"`).
- **[v4.3] Reads** (`GET`) are logged too; `GET /v1/nessie/log` hides them unless `?reads=1`, and only writes are published as `nessie_call` SSE events.
- A payout is `executed` only when both Nessie records exist. Never fake "executed".

### 11.4a Reconciliation with Nessie (`reconcile.py`) [v4.17]

`GET /v1/accounts/reconcile` proves the ledger and the bank agree, per real account that has a Nessie account (each real resident's checking and escrow, each real shop, the guarantee pool), in integer cents. Read-only: it never writes to the ledger or to Nessie.

- **Nessie's side:** the account's fixed `balance` (its opening) + completed deposits − completed withdrawals, from the same ≤ 10 s cache as the balances (`NessieClient.account_records`). Records whose status isn't `completed` are listed, not counted.
- **Our side:** the opening + Σ ledger movements on the ledger accounts the Nessie account mirrors (a resident's escrow covers all their certs), leaving out simulated money. The ledger books no opening entry, so the opening is compared on its own: ours is the logged "open account" call in `nessie_calls` (request `balance`), else StormCash's opening rule (checking $500, escrow and shops $0), else, for an account opened outside this database (a pool `nessie_setup` created against another database), Nessie's own value, said so. **[v4.19]** After a demo reset the pool's opening comes from the call log like every other account.
- **Simulated money** (a txn whose other side is a simulated resident or shop, or a settlement whose payer is simulated) is shown per account as "ledger only, never sent to Nessie", never as a difference.
- **A difference is split by txn** using the `SC <txn_id>` in each Nessie description, so the items add up to it exactly: `opening` (the two openings differ), `queued` (a `nessie_moves` row not executed yet), `half_pair` (one half recorded), `in_flight` (executed after Nessie was read), `pending_in_nessie`, `ledger_only` (not whole dollars, no pool account in Nessie, a `ledger_only` payout), `held` (an approved hold booked and reversed in the ledger), `not_in_ledger` (an `SC` record with no ledger txn; our call log says whether we made it and where its other half went), `unlinked` (a record with no `SC` id), and `unexplained` for anything else. Nessie is read before the database, so a txn posted in between shows as queued or in flight, not missing.
- **Pairs:** every `SC <txn_id>` on the accounts read, and every move touching them, must be one completed withdrawal on the move's source and one completed deposit on its destination, both equal to the ledger amount. Problems are listed by kind.
- **Nessie unreachable:** the account says so with the error and no number; `last_ok_at` is the last check that read every account (server memory). `NESSIE_DISABLED=1` makes every account "ledger only".
- Response: `{checked_at, ok, last_ok_at, nessie: {enabled, error}, accounts: [{key, label, kind, nessie_account_id, status: reconciled|difference|error|no_nessie_account, error, fetched_at, opening: {cents, source: call_log|rule|nessie, call_id, at, nessie_cents}, ledger_cents, simulated: {cents, txns, label}|null, expected_cents, nessie_cents, difference_cents, records, by_kind, items, items_total}], pairs: {checked, complete, problems, problems_total}, simulated_town}`.

---

## 12. Server API

All JSON. Byte fields base64url. Prefix `/v1`. Auth for demo: none on reads; resident/merchant writes carry a holder/merchant signature over `canonical(API, path, body_sha256_hex, ts)` in header `X-SC-Sig` with `X-SC-Pub` and `X-SC-Ts`. Operator actions require header `X-SC-Operator: <name>` (demo only).

**[v4.3] Signed writes, exactly.** `X-SC-Pub` = base64url compressed key; `X-SC-Ts` = Unix seconds, within ±600 s of the server; `X-SC-Sig` = base64url raw r‖s over SHA-256 of `canonical(API, path, body_sha256, ts)` with §7.2 rendering: `path` is the URL path as a string (`/v1/storm-mode`), `body_sha256` is SHA-256 of the exact body bytes as bytes32 (lowercase hex), `ts` an integer. Register requests must be signed by the key being registered; Storm Mode requests by the cert's holder. Errors: 401 bad or missing signature, 403 wrong key. `API_SIG_REQUIRED=0` accepts unsigned writes (fallback). Python helper: `stormcash.auth.sign_request`.

### 12.1 Endpoints

| Method + path | Body / query | Returns | Owner |
|---|---|---|---|
| `POST /v1/residents/register` | `{display_name, holder_pub, region_id, contact?: {channel, handle}}` (**[v4.13]** `contact` is the Photon handle that may text FREEZE; also saved when the resident already exists) | `{resident_id, cert}` — creates Nessie customer, checking (seeded $500), escrow (opened at $0); locks $20 as a withdrawal + deposit pair (§11.4); issues cert v1 cap 2000 | WS2 |
| `POST /v1/merchants/register` | `{display_name, merchant_pub, region_id, x, y, contact?: {channel, handle}}` | `{merchant_id, mcert}` | WS2 |
| `POST /v1/storm-mode` | `{cert_id, cap_cents}` | `{cert}` — tops escrow up in Nessie, issues new version | WS2 |
| `POST /v1/storm-mode/close` | `{cert_id}` | `{cert}` (cap back to 2000; refund scheduled per §7.4) | WS2 |
| `POST /v1/sync` | `{device_pub, items: [...]}` | `{rcpt, policy, certs: [...]}` | WS2 |
| `GET /v1/policy` | `?since=ver` | `{policy}` | WS2 |
| `GET /v1/accounts` | | live Nessie balances for demo entities (computed from Nessie transactions, §11.4) + ledger totals. **[v4.3]** `{accounts: [{key, label, kind, nessie_account_id, nessie_cents, nessie_error, ledger_cents}], simulated_town, ledger: {balanced, unbalanced_txns, totals}, nessie: {enabled, queued}}`; a Nessie failure shows as `nessie_error`, never as a number | WS2 |
| `GET /v1/accounts/reconcile` **[v4.17]** | | the ledger against Nessie's own records per real account, with every difference explained by txn and every `SC` pair checked (§11.4a) | WS2 |
| `GET /v1/health` **[v4.3]** | | `{ok, time, demo_mode, nessie_enabled, api_sig_required, server_pub}` for the header and phones | WS2 |
| `GET /v1/nessie/log` | `?limit=50` | rows of `nessie_calls` | WS2 |
| `GET /v1/cases` / `GET /v1/cases/{id}` | | case with both tags, the cert, the rule, evidence, case file. **[v4.23]** The list also gives each case `simulated` (its wallet's resident or a shop is simulated), `merchant`, and `payment_a` / `payment_b` `{counter, amount_cents, status, merchant, simulated}`, read-only, for the dashboard's plain titles | WS2 |
| `GET /v1/proof/{case_id}` | | everything the public verify page needs: cert (+server sig), tag A, tag B, holder_pub, rule. **[v4.3]** Each object comes with its `canonical` string so a browser can verify it with WebCrypto ECDSA P-256/SHA-256 over the UTF-8 bytes | WS2 |
| `GET /v1/flags` / `GET /v1/flags/{id}` | | flag + candidate features + agent transcript | WS5 |
| `POST /v1/flags/{id}/approve` / `reject` | `{note}` | executes actions (§14.6), returns approval. **[v4.3]** `X-SC-Operator` names the operator; `GET /v1/flags/{id}/approvals` lists decisions | WS5 |
| `POST /v1/stormdesk/run` | `{candidate_id}` or `{case_id}` | `{flag}` or `{case_file_md}` (sync; used by evals) | WS5 |
| `POST /v1/stormdesk/review` **[v4.15]** | `{flag_id}` or `{candidate_id}` (the stored flag), or `{candidate_id, proposal}` (a Flag to review, e.g. an eval's stored output; `flags` untouched) | the review run: `{output: Review, after_review: {status, agents_disagree, kind, proposed_action}, flag?, runner, model, usage, prompt_version, duration_s, …}` (sync, operator header). 409 for a decided or invalid flag, or a proposal whose citations don't hold (§14.7b) | WS5 |
| `POST /v1/stormdesk/author-detector` **[v4.22]** | `{gap, examples?}`: `gap` names a candidate kind (or describes it); `examples` are dev row ids (`seed:candidate_id`) or `{row_id, note}`. Held-out rows are refused | 202 `{run_id, subject, status: "running", kind}`; steps stream as `stormdesk_step` (subject `author run #N`) and phases as `author` events; the result is the run (`GET /v1/stormdesk/runs/{id}`). 409 when the switch is off, Droid or the OS sandbox is missing, or a run is in progress (§14.7d) | WS5 |
| `GET /v1/stormdesk/author-detector` **[v4.22]** | — | `{enabled, reasons, model, max_credits, base_ref, budget, running, runs}` | WS5 |
| `GET /v1/stormdesk/runs` / `GET /v1/stormdesk/runs/{id}` **[v4.3]** | `?case_id&candidate_id` | stored runs; one run with its full transcript for replay (§14.8). `POST /v1/stormdesk/run` needs the operator header | WS5 |
| `GET /v1/evals` **[v4.8]** | | the saved Chalk eval runs for the Evals tab: the newest file per comparison column (full), the others as summaries (§18.5) | WS3 |
| `GET /v1/droid/console` **[v4.16]** | `?limit=200` | read-only aggregates of the stored StormDesk runs for the Droid tab: per-run outcome, totals per job, guardrail events, harness (§18.7) | WS3 |
| `GET /v1/town` | | regions, merchants (x, y, simulated), live dots, recent payments, uploads, alerts | WS4/WS2 |
| `GET /v1/relay/paths` | `?limit=20` | recent payments with `path`, hops, latency. **[v4.3]** Each hop names the device (resident or merchant, from `device_short_id`) | WS2 |
| `GET /v1/town/quick` **[v4.3]** | `?adoption&p_link&p_uplink` | the §16.6 quick re-sim: `{baseline, current, seconds}` | WS4 |
| `POST /v1/photon/inbound` | Photon webhook payload | 200 | WS7 |
| `POST /v1/photon/resident-contact` **[v4.13]** | `{resident_id \| display_name, channel, handle}` | the resident and the saved handle. Operator header; `display_name` must match exactly one real (not simulated) resident, e.g. Maya | WS7 |
| `GET /v1/photon/messages` **[v4.13]** | `?merchant_id=` or `?resident_id=` | `{messages}`: one shop's or resident's Photon thread, oldest first. **[v4.21]** A shop's thread also has `turns`: the respond runs that answered it, each with its Droid session, turn, and whether the agent's reply was sent (§14.7c) | WS7 |
| `GET /v1/photon/freezes` **[v4.13]** | `?cert_id&limit` | certs whose owner texted FREEZE: `[{cert_id, status, frozen_at, owner_freeze_at, resident_id, display_name, policy_ver}]`, `policy_ver` = the first POLICY listing the cert | WS7 |
| `POST /v1/demo/reset` | | clears real-device demo data, reissues Maya's cert, keeps the simulated town. **[v4.18]** Removes the dry run's identities first (§21.6) and returns `dry_run_removed`. **[v4.19]** Opens a fresh guarantee pool account (§11.4) and returns it as `pool: {account_id, customer_id, opening_cents, replaced}` (null without a pool) | WS2 |
|  |  | **[v4.3]** Operator header. Deletes what touches a real resident or shop (payments, tags, cases, candidates, logs, contacts, uploads, payouts, whole ledger transactions, queued moves), opens fresh Nessie accounts under the same customers (checking $500, escrow $0, shops $0; Nessie balances can't be edited), reissues each real resident a new cert (new `cert_id`, $20 locked), restores the shops' pool eligibility and publishes a POLICY without the old certs. The phone gets its new cert by registering again. Optional `{storm_cap_cents: 5000}` pre-stages Storm Mode. Measured live: under 1 s. |  |
| `POST /v1/demo/seed-town` | `{seed}` | runs the simulator into the DB (§16) | WS4 |
| `GET /v1/demo/dry-run` **[v4.18]** | | `{prefix, stormdesk_skips_dry_run, stormdesk_worker, stormdesk_runner, stormdesk_review}`: what the dry run checks before it writes anything (§21.6) | WS2 |
| `GET /v1/stream` | | SSE | WS2 |

### 12.2 `POST /v1/sync` example

```json
{
  "device_pub": "A8x...",
  "items": [
    {"kind": "PAY", "body": {"c": {...}, "t": {...}, "d": {...}}, "path": [["9f1c2a3b", 1760000000], ["44aa01de", 1760000240]]},
    {"kind": "DLOG", "body": {"dp": "...", "q": 7, "ph": "...", "ts": 1760000100, "kd": "CONTACT", "...": "..."}, "path": []}
  ]
}
```

### 12.3 SSE events (`GET /v1/stream`)

| event | data |
|---|---|
| `nessie_call` | row from `nessie_calls` |
| `accounts` | balances snapshot. **[v4.3]** Sent after each executed Nessie pair as `{changed: [nessie account ids], txn_id}`; the dashboard refetches `GET /v1/accounts` |
| `payment` | payment row incl. status, funding split, path |
| `case_opened` | case summary |
| `policy` | new policy version |
| `candidate` | candidate summary |
| `stormdesk_step` | `{flag_or_case, tool, input_summary, ok}` (live tool calls) |
| `flag` | flag row |
| `approval` | approval + executed actions |
| `message` | Photon message in/out. **[v4.13]** `merchant_id` or `resident_id` says whose thread |
| `owner_freeze` **[v4.13]** | `{resident_id, cert_ids, newly_frozen, policy_ver, owner_freeze_at}` after a resident's FREEZE text |
| `upload` | device, items, hops |
| `town` **[v4.3]** | `{seed, status, summary}` when seed-town finishes |

---

## 13. Soft signals (deterministic detectors) [v4]

Detectors are deterministic SQL/Python in `server/stormcash/detectors.py`. They produce **candidates** with frozen feature snapshots. **They never act.** StormDesk judges each candidate.

Rules-only baseline (for evals): "flag every candidate with its default action".

### 13.1 `merchant_silence`

Window: rolling 6 h (simulated time), evaluated per merchant.

Features:
- `contacts_per_hour` (from `contacts`, this merchant)
- `neighbor_median_contacts_per_hour` (merchants within radius R=3 grid cells, same window)
- `silence_ratio = contacts_per_hour / max(neighbor_median, 0.1)`
- `pool_funded_count`, `pool_funded_cents`, `accepted_count`, `pool_funded_share`
- `distinct_cheater_certs` (certs with hard cases among this merchant's accepted payments)
- `near_cap_share` (accepted payments with `cum ≥ 0.8 × cap`)
- `paired_contact_share`, `one_sided_contacts`
- `prior_windows_flagged`

**Fires when:** `silence_ratio < 0.2` **and** `pool_funded_count ≥ 1` in the window.

Default action: `hold_pool_payout`.

### 13.2 `cap_drain`

Per cert, any 15-minute window.

Features: `distinct_merchants_15m`, `spent_15m_cents`, `cap_cents`, `drain_share`, `minutes_since_storm_mode`, `home_region`, `regions_in_window`, `region_mismatch`, `hour_of_day`, `gap_since_last_activity_min`, `owner_freeze_request` (from Photon `FREEZE`).

**Fires when:** `distinct_merchants_15m ≥ 3` **and** `drain_share ≥ 0.8`.

**[v4.13]** `owner_freeze_request` is true when `cert_status.owner_freeze_at` is set when the candidate is created (the owner texted FREEZE, §17.2, before or during the drain's uploads). Like every feature it is frozen at creation; the dashboard shows a later request next to the flag from `GET /v1/photon/freezes`.

Default action: `freeze_cert`. (Even an approved soft freeze is a human decision; contrast with hard rules.)

### 13.3 `region_dark`

Per region, evaluated hourly (simulated time).

Features: `active_certs`, `expiring_12h_share`, `hours_since_last_upload`, `active_alerts` (event, severity, source), `population_weight` (active residents), `merchants_open`.

**Fires when:** `expiring_12h_share ≥ 0.3` **and** `hours_since_last_upload ≥ 48`.

Default action: `dispatch_relay`.

### 13.3a As built [v4.3]

- `detectors.run_incremental(deps, now)` runs after every ingest, in protocol time (`payments.received_at` and `uploads.received_at` are the ingest's `now`, so the simulator's virtual clock works). `cap_drain` looks at the 15 minutes ending at each newly received payment; `merchant_silence` (6 h window) and `region_dark` run once per hour boundary passed, catching up on missed hours. A detector error never fails a sync.
- One candidate per stretch: a new candidate is skipped if one for the same kind and subject overlaps its window. `region_dark`'s window is the dark stretch itself (from the last upload, or the region's first cert if there was none). A candidate with no flag is a queued StormDesk job.
- `contacts_per_hour` counts distinct `contact_id`s the merchant is in, from either side's log. Neighbors are merchants within 3 grid cells (Euclidean). `pool_funded_share` = pool-funded payments ÷ accepted payments. `near_cap_share` compares `cum` with the cert's highest cap. `owner_freeze_request` is `false` until Photon FREEZE (WS7) exists.
- Accepted payments are those `settled`, `held` or `denied_knowing`.
- Store-and-forward data can arrive hours late, so a newly received pool-funded payment also re-checks its merchant's silence windows that contain it. `cap_drain` remembers which payments it has looked at (several uploads can land in the same second).
- R5 loads only the log entries that can fire it (the merchant's ACCEPT for the payment, and the contacts whose id lists carry a conflicting tag), and per-entry re-checks are batched once per upload.

### 13.4 Why the agent adds value over the detectors

The detectors are designed to fire on **traps** too (§16.4). A rules-only system flags all of them. The agent's job is to keep recall on real fraud while dismissing traps using the full context (pool share, repeat patterns, regions, alerts). The Evals tab compares the two.

---

## 14. StormDesk agent (Factory Droid SDK) [v4]

### 14.1 Jobs

| Trigger | Job | Output |
|---|---|---|
| A hard case opens | **Investigate:** gather evidence, independently re-verify both signatures and the rule with the deterministic verifier tool, compute exposure and who is owed what, write a case file and recovery plan | `CaseFile` → `cases.case_file_md` |
| A candidate is created | **Triage:** decide whether it's real, cite evidence, choose severity and action, or dismiss with a reason | `Flag` → `flags` |
| A merchant appeals by message (§17) | **Respond:** compare the claim with the logs, reply with evidence, escalate or resolve | `AppealReply` → `messages` |
| A triage stores an open or dismissed flag **[v4.15]** | **Review:** a second session tries to refute the Flag; it never acts (§14.7b) | `Review` → `flags.review` |
| An operator asks for a detector for a gap **[v4.22]** | **Author:** write a pure detector and its test in a sandbox, prove it on labelled data; our code re-checks it and opens a PR for a person (§14.7d) | `DetectorProposal` → a pull request |

Jobs run in a worker (`stormdesk/worker.py`): an asyncio queue, max 4 concurrent Droid sessions.

### 14.2 Harness configuration

```python
from droid_sdk import run, Session, SessionConfig, InteractionHandlers, PermissionRequest, PermissionResponse, ToolConfirmationOutcome
from droid_sdk.mcp import create_sdk_mcp_server, tool

server = create_sdk_mcp_server(name="stormdesk", tools=[...], version="1.0.0")

def deny_everything_else(req: PermissionRequest) -> PermissionResponse:
    # Only our MCP tools are allowed; they are read-only. Everything else is refused.
    ...

config = SessionConfig(
    system_prompt=STORMDESK_PROMPT,          # §14.4
    mcp_servers=[server],
    disabled_tools=BUILTIN_TOOLS,            # every built-in tool id from session.list_tools() (droid 0.244.0)
    disable_builtin_skills=True,
)
```

- Use `run(prompt, output=Flag)` (or `Session.stream`) with **structured output** (Pydantic). Missing or invalid output = `RunFailure` with `error_structured_output`: retry once, then store the flag as `invalid`.
- Stream messages; for each `ToolCall` / `ToolResult`, emit SSE `stormdesk_step` and append to `agent_transcript`.
- **Verified Oct 16** with droid CLI 0.244.0: the built-in tool ids to disable (`list_tools()`; the full list is `runner.BUILTIN_TOOLS`) and the MCP tool id format (`mcp__stormdesk__<tool>`). Structured output is still to be seen working on a live run.
- **[v4.9] First live runs (Oct 17, droid 0.244.0, `claude-sonnet-5-5`).** Structured output works through `Session.stream`. Droid's `ToolSearch` runs once per session even though it is in `disabled_tools`: it loads our MCP tool schemas (`mcp__stormdesk__*`) and reads nothing else, and it shows up as a step. Each run stores `model` (what the session actually ran on, read from `Session.settings`, which Factory updates when it switches models, e.g. to Droid Core once Standard Usage runs out), `model_requested` and `usage` (tokens and `factory_credits`, summed over attempts) in its transcript and in the `POST /v1/stormdesk/run` response. The Droid badge shows the model and credits (and "asked for …" after a switch), and every replay is labelled "Replay of run at … · Droid, <model>" or "· fake runner, rules only". Measured cost: an investigation took 12k–17k credits, a merchant triage with 14 tool calls 63k.
- **Droid can't run** (`RunFailure` `error_during_execution`, e.g. "model_usage_exhausted" when the account is out of credits, or the CLI/process fails): not retried. The job is answered by the labelled fake runner instead, the run records `fallback_from_droid` with the reason, and Droid is skipped for 5 minutes before it is tried again.
- Model: let Droid pick (`model="auto"`) unless a Claude model is selectable; prefer Claude.

### 14.3 Tools (all read-only, in-process MCP)

| Tool | Args | Returns |
|---|---|---|
| `get_case` | `case_id` | rule, tags, cert, evidence ids, exposure |
| `get_candidate` | `candidate_id` | kind, subject, window, frozen features |
| `get_cert_chain` | `cert_id` | all tags in counter order, versions, status, settled total |
| `verify_tags` | `tag_hashes[]` | deterministic re-check: signatures valid? which rule (if any) any pair breaks? (calls `protocol/rules.py`) |
| `get_device_log` | `device_id, since, until` | DLOG entries (ACCEPT/REFUSE/CONTACT), chain status |
| `get_contacts` | `device_id, since, until` | contacts with paired flags and peer ids |
| `get_merchant_payments` | `merchant_id, since, until` | payments with funding split and cert status |
| `query_features` | `entity: merchant\|cert\|region, id, features[]` | Chalk online query (§15.2) |
| `get_region_status` | `region_id` | active certs, expiries, last upload, alerts (live + replayed, labeled) |
| `get_nessie_balances` | `entity_id` | balances for demo entities (cached ≤ 10 s) |
| `get_messages` | `merchant_id` | Photon conversation so far |

There is **no** write tool. The agent's only output is its structured result.

### 14.4 System prompt (starting point)

```
You are StormDesk, the back-office fraud analyst for StormCash, an offline payment system
used after disasters. Capital One funds resident escrow accounts; a guarantee pool pays shops
for accepted payments above a cheater's escrow.

Facts you must respect:
- Hard rules (SAME_COUNTER, BROKEN_LINK, TOTAL_BACKWARDS, OVER_CAP, MERCHANT_KNEW, LOG_TAMPER)
  are mathematical proofs computed by deterministic code. Never second-guess a hard rule; you
  may re-verify it with verify_tags and describe it.
- Soft candidates are only suspicions. Many are innocent: remote shops with little foot traffic,
  phones with drifting clocks, honest residents stocking up right after Storm Mode.
- You cannot move money or freeze anything. You propose; a human operator decides.
- Every claim must cite ids you actually retrieved from tools (tag hashes, log entry hashes,
  contact ids, payment ids, alert ids). Never invent an id. Uncited claims are discarded.
- **[v4.9]** evidence_ids name records: tag hashes, device-log entry hashes, contact ids, cert ids,
  merchant ids, alert ids and a case's proof_item_id. Field values (prev_hash, details
  hashes, signatures, keys) are not ids: mention them in the text, not in evidence_ids.
- Prefer dismissing with a clear reason over flagging when the evidence is weak.
- Be brief. The operator reads your summary in 10 seconds.

**[v4.12]** How to weigh soft evidence (prompt v2):
- Exposure is money someone loses, not only the guarantee pool's. A resident's escrow drained by
  someone else is the resident's loss: "every cent came from escrow" does not mean "no exposure".
- A hard case settles the cheating certificate, not the people around it. Don't treat "covered by
  escrow" or "covered by a hard case" as no exposure: ask who kept the money and whether the
  pattern goes on.
- A certificate that sat idle, then spends most of its cap at several shops within minutes,
  outside its home region, points to a stolen phone, whatever funds the payments.
- A shop reached by one or two cheaters while it keeps syncing normally is usually their victim.
  A shop that goes quiet relative to its neighbors while accepting pool-funded payments from
  several certificates the hard rules caught fits a shop working with them. Weigh silence,
  pool-funded share and the number of distinct cheater certificates together; no single one
  decides.
```

**[v4.12] Prompt v2 is not a blind holdout.** The first real eval (#33, PR #85, v1, `claude-sonnet-5-5`, 43 rows) caught 2 of 23 real cases and dismissed every stolen phone ("all from escrow, so no exposure") and every colluder ("the cheaters' victim"). We wrote the v2 lines above after reading those errors on that same dataset. They are general principles, with no seed, shop, scenario or trap names, but a v2 score on that dataset still isn't a blind test. Each Droid run stores `prompt_version` in its transcript.

### 14.5 Output schemas

```python
class Flag(BaseModel):
    kind: Literal["merchant_silence", "cap_drain", "region_dark", "none"]
    severity: Literal["info", "review", "urgent"]
    subject_id: str
    evidence_ids: list[str]               # must exist; server checks (§14.7)
    exposure_cents: int
    summary: str                          # ≤ 2 sentences, operator-facing
    reasoning: str                        # ≤ 6 bullet points, shown on expand
    proposed_action: Literal["none", "lower_merchant_limit", "hold_pool_payout",
                             "freeze_cert", "dispatch_relay"]
    action_params: dict[str, int | str]   # e.g. {"limit_cents": 1000}
    merchant_notice: str | None           # draft text for Photon, if action affects a merchant

class CaseFile(BaseModel):
    rule: str
    verified_independently: bool          # verify_tags agreed with the hard rule
    who_paid: list[dict]                  # merchant, amount, source (escrow/pool)
    exposure_cents: int
    recovery_plan: list[str]
    evidence_ids: list[str]
    summary_md: str

class AppealReply(BaseModel):
    reply: str                            # sent to the merchant
    claim_consistent_with_logs: bool
    evidence_ids: list[str]
    escalate: bool
```

### 14.6 Approval actions (deterministic, run by the server on Approve)

| Action | Effect |
|---|---|
| `hold_pool_payout` | Merchant's not-yet-executed pool-funded payouts → `held`; future pool payouts held until released. Photon notice sent. |
| `lower_merchant_limit` | Sets `merchants.per_payment_limit_cents`; publishes a new POLICY (spreads to phones by gossip). Photon notice sent. |
| `freeze_cert` | `cert_status='frozen'`, new POLICY. |
| `dispatch_relay` | Adds a task "Send a relay to <region>" to the operator's list (no money, no messages). |
| `none` | Nothing. |

Reject = flag `rejected`, nothing executes. Every approval writes an `approvals` row and an SSE event.

**[v4.3] As built (`server/stormcash/approvals.py`).** `POST /v1/flags/{id}/approve` and `/reject` take `{note}` and the `X-SC-Operator` header (the operator's name). Only `open` flags with valid citations can be decided, and a decision is final. `hold_pool_payout`:
- the shop's pool payouts not yet executed (`queued`, `pending`, `ledger_only`) become `held` (a new payout status), with the payment `held`;
- their queued Nessie moves are cancelled;
- the payout and its fraud receivable are reversed in the ledger, so it stays balanced;
- `pool_eligible = false`, so future pool money is held at settlement.
`lower_merchant_limit` needs `action_params.limit_cents`. Approving `hold_pool_payout` or `lower_merchant_limit` sends Photon's hold notice (`photon/notices.hold_notice`), recorded on the thread even when it can't be delivered. The `approval` SSE event carries the executed actions. A real shop with a registered handle also gets Photon's settled notice when its payout executes.

### 14.7 Guardrails

- **Citation check:** before saving, the server checks every `evidence_ids` entry exists in the DB (tags, payments, device_log entry hashes, contacts, alerts; **[v4.9]** also cert and merchant ids and a hard case's `proof_item_id`, which `get_case` returns). Any miss → `citations_valid=false`, flag status `invalid`, never shown as actionable. Counted in evals.
- No write tools; permission handler denies everything except our MCP tools.
- Hard rules are never routed through the agent for a decision.
- Every run's transcript is stored for replay and audit.

### 14.7a As built [v4.3]

- `server/stormcash/stormdesk/`: `tools.py` (the 11 tools, plain SQL reads in a `READ ONLY` transaction, ids returned as hex so they can be cited), `runner.py`, `service.py`, `worker.py`, `schemas.py`, `prompt.py`, `citations.py`.
- **Runners.** `STORMDESK_RUNNER=droid|fake|auto` (auto = Droid only when the SDK, the `droid` CLI and `FACTORY_API_KEY` are present). `DroidRunner` uses `droid-sdk` 0.5.0: our tools are an in-process MCP server named `stormdesk`, `SessionConfig(system_prompt, mcp_servers, disabled_tools, disable_builtin_skills=True)`, `Session.stream(prompt, output=Model)`, `ToolCall`/`ToolResult` events become steps, and a failed structured output is retried once. The permission handler allows only `McpToolAction`s from the `stormdesk` server naming one of our 11 tools and cancels everything else. The `disabled_tools` list is every built-in tool id (verified with `list_tools()`, §14.2). If Droid can't run at all, the fake runner answers the job and the run records `fallback_from_droid` (§14.2). `FakeRunner` calls the same tools and applies the rules-only baseline (every candidate gets its default action; case files from `verify_tags` + `get_cert_chain`). Its triage also calls `query_features` with `as_of` = the candidate's `window_end` and says in the reasoning whether Chalk or the Postgres fallback answered; it reports those values but doesn't weigh them. Its summaries start with "Fake runner", its session ids with `fake-`, and every run records its runner, so a fake result is never shown as an agent's judgement (§0 rule 3).
- **Storage.** Every run is a `stormdesk_runs` row (§11.1) with its transcript. Triage writes one `flags` row per candidate (`dismissed` for kind `none`, `invalid` on a citation miss or no output). A re-run updates it unless an operator already approved or rejected it. An investigation writes `cases.case_file_md` only when its citations hold.
- **Citations** (§14.7) accept tag/payment hashes, device-log entry hashes, contact ids, cert ids, merchant ids (hex, optional `kind:` prefix) and weather alert ids. A flag of a real kind must cite at least one; a dismissal may cite none.
- **Worker.** Polls every 5 s for candidates without a flag and cases without a case file (at most 2 runs each), up to 4 at a time (the same limit covers `POST /v1/stormdesk/run`). `STORMDESK_AUTO=0` turns it off. **[v4.18]** It never queues a case or candidate of the demo dry run's identities (display names starting `Dry-run `, §21.6), so a dry run never starts Droid or writes a run.
- **SSE `stormdesk_step`:** `{run_id, job, subject, runner, index, tool, input_summary, ok}` per tool call, then `{run_id, done, status}`. A `flag` event follows triage.
- `query_features` asks Chalk (§15.2) **[v4.6]**; the Postgres fallback (§22.4: the detectors' frozen features) answers when Chalk is off or fails.
- Checked on the seeded town with the fake runner: all 22 hard cases and 12 candidates give valid outputs with verified citations.

### 14.7b Reviewer Droid: agents check agents, a person decides [v4.15]

- **Job `review`** (`runner.py`, `service.py`, `prompt.py`). After a triage stores an `open` or `dismissed` flag, a second, independent Droid session tries to refute it. Its own system prompt (`REVIEW_PROMPT`, `REVIEW_PROMPT_VERSION = 1`): don't trust StormDesk's summary or reasoning, re-run the tools, check that every cited record exists and supports the claim it is cited for, look for what was missed (a dismissal can be wrong too); then StormDesk's "Facts you must respect" and v2 weighing, verbatim. It gets the candidate id and StormDesk's structured `Flag` (with its `reasoning` field), never the first run's transcript or session. The same 11 read-only MCP tools, `disabled_tools`, permission handler and citation check (§14.7) apply.
- **Output** (`schemas.Review`): `verdict: agree | disagree | insufficient_evidence`, `reasons` (≤ 4), `evidence_ids`, and, when it doesn't agree, `suggested_kind`, `suggested_severity`, `suggested_action`.
- **What it does to the flag** (`service.after_review`, deterministic). The review is stored as `flags.review` (the output plus its run id, runner, status, citations, model, usage, prompt version and duration). Only a valid review by an agent counts:
  - `agree`: the flag stays as StormDesk proposed it.
  - `disagree` or `insufficient_evidence`: `flags.agents_disagree = true`, and the flag is `open` for a person (a dismissal is reopened).
  - StormDesk's kind and proposed action never change, and Approve runs only that action (§14.6). The reviewer's suggestion is shown, never executed. The reviewer can't act.
  - A review with a missing citation or no output, and the fake reviewer's answer, are shown and don't count. Invalid flags aren't reviewed (they never reach a person). A decided flag stays decided. A re-triage clears the review, and a review that finishes after a re-triage is kept as a run only.
- **Fake reviewer.** `FakeRunner` re-reads the candidate and its records (payments, cert chain or region) and compares the proposal with the rules-only baseline: `agree` when they match, `disagree` for a dismissal, `insufficient_evidence` otherwise. Its reasons start with "Fake reviewer:" and it never escalates a flag: a rules-only comparison isn't a second opinion (the baseline flags every honest subject, §15.3).
- **Recording**, exactly as a triage: a `stormdesk_runs` row with `job = 'review'` and the candidate id, its runner, `model`, `model_requested`, `usage` (Factory credits), `prompt_version` (the reviewer's), `duration_s` (now on every run), steps, and `reviewed` (flag id, StormDesk run id, the proposal). Live steps are `stormdesk_step` events with subject `review of candidate #N`, then a `flag` event.
- **Every Droid run** (triage, investigation and review) now also stores, in its transcript:
  - `attempts`: one `{attempt, ok, error}` per session, so a structured-output retry leaves a trace.
  - `permission_denials`: one `{tool, server, reason}` per action the permission handler refused, and `[]` when it refused none.
  - On a fallback, the Droid attempt's own lists are under `fallback_attempts` / `fallback_permission_denials`.
  - The keys are absent on fake-runner runs and on older runs: not recorded, never zero.
- **Switch.** `STORMDESK_REVIEW=1`, the default when the server loads its environment (bare `Settings` in tests: off), reviews every triage that stores an open or dismissed flag, with the runner the desk would pick (Droid, or the labelled fake runner on fallback). The `POST /v1/stormdesk/run` response then has `review`. `STORMDESK_REVIEW=0` turns it off. `POST /v1/stormdesk/review` reviews a stored flag on request, or a Flag passed in with its candidate (§12.1).
- **Dashboard** (the StormDesk flag panel): a "Second opinion" section with "Reviewer agrees / disagrees / not enough evidence", the reviewer's badge (model and credits, or "Fake runner · rules only"), its reasons, the records it cited (checked), what it would do instead, and its own steps, live or replayed. A flag where the agents disagree says "Agents disagree · a person decides" in its header and in the list. "Ask the reviewer" / "Review again" calls the endpoint.
- **Not built:** reviewing investigations (hard cases are proofs) and appeal replies.
- **Honesty.** The reviewer prompt was written before any review ran and without reading any held-out row; its author knew run B's aggregate scores (§15.3).
- **First live reviews, Oct 17** (`claude-sonnet-5-5`, demo DB, seed 42), both answered on the first attempt with valid citations:
  - Corner Store (flag 16, StormDesk run 88, prompt v2, hold pool payouts): review run 89 **agreed**. 14 steps (`ToolSearch` and 13 tool calls), 10 cited ids, 56,198 credits, 43.6 s.
  - Stolen phone, Resident 174 (flag 17, the fake runner's freeze_cert baseline): review run 90 **agreed**. 9 steps, 5 cited ids, 16,828 credits, 30.0 s. It also noted that the baseline's text missed the region mismatch and the idle gap.
  - Neither shows a disagreement. How often the reviewer disagrees, and whether that helps, is for an eval on stored proposals (§15.3).

### 14.7c Appeals as one Droid session [v4.21]

- **One conversation per appeal thread.** A thread is a shop and the flag its texts are about (`messages.merchant_id`, `flag_id`). Its first text opens a Droid session with StormDesk's system prompt (v2), the 11 read-only tools, the built-ins off and the permission handler. Each later text resumes that session with `Session.resume(session_id, mcp_servers=…, disabled_tools=BUILTIN_TOOLS, disable_builtin_skills=True, interactions=…)` and streams one new turn with `output=AppealReply`. Verified on droid-sdk 0.5.0 with droid 0.244.0: a resumed session keeps its model and system prompt, and an unknown id raises `SessionNotFoundError`.
- **Prompts** (`prompt.py`, `APPEAL_PROMPT_VERSION = 1`). The opening turn says who is appealing which flag and gives the thread so far, the hold notice included, then the new text. Later turns give only the new text, plus anything the session didn't see: that its previous reply was held back and why ("Your previous reply was not sent: …"), and messages answered while Droid couldn't run.
- **Guardrails on every turn.** The tools and permission handler are passed again on each resume. The reply is sent only if it cites at least one id and every cited id exists (§14.7, `photon/appeal.pick_reply`). Otherwise the shop gets the neutral acknowledgement, and the next turn is told. A failed structured output is asked again once, in the same session.
- **A session that can't be resumed** (expired, or saved on another machine) is replaced by a new session seeded with the last 30 messages of the thread from `messages`. That turn records `session: restarted`, `resumed_from` and `resume_error`. If Droid can't run at all, the labelled fake runner answers as before (§14.2).
- **Where the session id lives.** There's no new table. Every turn is a `stormdesk_runs` row (job `respond`) with the session id in `session_id` and `transcript.appeal` = `{mode, flag_id, in_message_id, out_message_id, reply_sent, session: started | resumed | restarted, turn, prompt_version}`. Like every run it also has model, credits, duration, attempts and permission denials. The thread's session is the one its latest Droid turn ran in, as long as that turn's message is still on the thread: a thread cleared from `messages` starts a new conversation. A thread's turns run one at a time (a lock per thread in `photon/appeal.py`), so each turn knows what the shop was actually sent.
- **Switch.** `STORMDESK_APPEAL_SESSIONS=1` is the default when the server loads its environment (bare `Settings` in tests: off). `0` gives one fresh run per message, as before (`transcript.appeal.mode = per_message`). The fake runner keeps its labelled deterministic reply in both modes.
- **Dashboard.** Under each StormDesk reply, the Photon thread says which turn of which Droid session wrote it ("Droid · turn 2 · same Droid session 8c1f2a3b"), or why the reply was held back. Its header says "One Droid session · 3 turns · N credits". The Droid tab counts appeal turns and sessions (resumed, restarted) and labels each respond run with its turn (§18.7).
- **First live appeal, Oct 17** (`claude-sonnet-5-5`, Neon demo DB, the Corner Store's flag 16). The texts came in as simulated inbound webhooks, with Photon sending off. The shop texted three times, all answered in one Droid session (runs 91–93):
  1. "We were closed that afternoon, the generator died around 2." Turn 1 (new session, 5 tool calls, 36,715 credits, 33 s) answered with the six payments the shop's signed log accepted after 2 PM. It also cited `16`, the flag's number, which isn't a record, so the citation check held the reply back and the shop got the neutral acknowledgement.
  2. "The phone was off the whole time, it was in a drawer." Turn 2 (resumed, and told its last reply wasn't sent; 5 tool calls, 18,298 credits, 30 s): "A phone that is switched off can't sign payments … This also differs from your first message. A generator failure would explain a closed shop, but it wouldn't stop the phone from working."
  3. "I already explained what happened. Why is my payout still on hold?" Turn 3 (resumed; 3 tool calls, 13,118 credits, 21 s) answered from the conversation and escalated to a person: "First you said the shop was closed after the generator died around 2. Then you said the phone was off in a drawer the whole time."
  - Since that run, the opening prompt no longer names the flag's number and says to cite only records retrieved with the tools. The one allowed retry's first turn (run 94, new session, 4 tool calls, 61,428 credits, 38 s) cited 11 records, all of which exist, and its reply was sent. The credit guard stopped the retry there, because another turn could have passed the 200,000-credit cap. Total: 129,559 credits.
  - Afterwards the proof's messages and its test handle were removed from `messages` and `merchant_contacts`, so the table demo starts a new conversation. Runs 91–94 are kept.
### 14.7d Droid proposes a detector as a pull request [v4.22]

The one job where Droid writes code. It never runs in the money path: a proposed detector is a module and a test in a pull request, and nothing imports it until a person merges a follow-up that wires it into `detectors.run_incremental` (§0 rule 2).

- **Trigger.** "Ask Droid to write a detector" on the Evals tab, or `POST /v1/stormdesk/author-detector {gap, examples}` (§12.1). The tab's gap comes from the stored eval runs; the first is `region_dark` (StormDesk v2 caught 3 of 5 dark regions on dev rows and 0 of 2 on held-out rows; rules-only flags every quiet region too). Examples are dev rows StormDesk got wrong. Held-out rows are refused.
- **Sandbox** (`stormdesk/sandbox.py`). Each layer confines Droid on its own:
  1. A throwaway `git worktree` of `STORMDESK_AUTHOR_BASE` (`origin/main`, fetched first) in a temp directory outside every checkout; one with an env file is refused. Droid's session runs there.
  2. The permission handler (`AuthorGuard`) allows Create, Edit and ApplyPatch only on `server/stormcash/detectors_proposed/<name>.py` and `server/tests/test_proposed_<name>.py`, for one `<name>` fixed by the first allowed edit, ≤ 20 kB each, plus our MCP tools. Everything else is refused and recorded in `permission_denials`. A refusal ends Droid's turn ("cancelled by user"), so up to two follow-up turns in the same session tell it what was refused.
  3. Built-in tools: only Create, Edit and ApplyPatch are on (Create and Edit are off by default in SDK sessions; `enabled_tools`). The rest, from `list_tools()` at run time, are off, the shell included. **Checked live Oct 17 (droid 0.244.0):** the CLI auto-runs a command it rates read-only (`ls`, rule `builtin/directory-list-allow`) without asking the permission handler, and it never asks before reads. So Droid reads through MCP tools confined to the worktree (`read_file`, `list_dir`, `search`; never held-out rows, `chalk/evals/results`, `.git`, env files or keys), and the two allowlisted commands are MCP tools, `run_tests(name)` (pytest on the test file) and `run_eval(name)` (the evaluation script), with a budget of 6 and 3 runs.
  4. The `droid` CLI runs under `sandbox-exec` with a scrubbed environment (PATH, HOME, TMPDIR and the Factory variables only): writes only inside the sandbox, `~/.factory` and temp; no reads of env files, `~/.ssh`, `~/.config/gh`, `~/.aws`, `~/.netrc` or held-out data. The login keychain stays readable: the CLI's own login is there.
  5. `run_tests` and `run_eval` run in our server, outside Droid's profile, in a second profile: no network (so no database), writes only to the sandbox's tmp, a scrubbed environment, 120 s. The tests can't read held-out data either.
  6. macOS only: without `sandbox-exec` the job refuses to run.
- **Evaluation** (`stormdesk/detector_eval.py`, deterministic, offline). A detector is `KIND`, `NAME`, `fires(features) -> bool` over one candidate's frozen snapshot. Before import it must pass a purity check (imports only `math`, `statistics`, `typing`, `dataclasses`, `collections`; no `open`, `print`, `eval`, `getattr`, dunder or `_` attributes, global state). It runs over the Chalk eval datasets' candidates of that kind (§15.3), dev seeds 42, 7, 13, 99, 2026 and held-out seeds 1, 2, 3, and reports TP/FP/FN/TN, precision and recall next to the rules-only §13 detector (which raised every row, so it fires on all of them). Labelled subjects no detector raised count as missed by both. Held-out rows are only ever aggregates, and errors never name one.
- **Output** `DetectorProposal {name, kind, rationale, files_changed, tests_passed, metrics: {dev, heldout: {proposed, rules_only}}, caveats}`.
- **Our checks** (`author.verify`, after the session closed): only the two files changed (`git status`), the detector is pure, no secret value from the server's settings or environment is in either file, then our re-run of the tests and the eval. Droid's name, kind, files, `tests_passed` and every number must equal the re-run, or the run is stored `invalid` ("Re-run rejected" on the Droid tab) and no PR opens.
- **Hand-off** (`author.open_pr`, deterministic, Droid runs only). Commit the two files on the worktree's detached HEAD as the repo owner (`git config user.name/email`), push `droid/detector-<name>-run<N>`, open "Detector proposed by Droid: <name>" against `main` with the rationale, our re-run's metrics, data and detector hashes, caveats, run id, session, model and credits, labelled `droid-proposal`. Never merged by code. The worktree is removed whatever happens.
- **Recording.** A `stormdesk_runs` row with `job = 'author'` (migration `007`): runner, model, `usage` (the credits are the CLI's own session record, `tokenUsage.factoryCredits`, with the SDK's sum beside it), attempts, permission denials, steps, lab runs, operator, the checks, the files Droid wrote and the PR. A run stops at `STORMDESK_AUTHOR_MAX_CREDITS` (the stream's usage events are checked live). The Droid tab counts author tool calls as "in the sandbox", not read-only.
- **Switch.** `STORMDESK_AUTHOR=1` turns it on (bare `Settings` in tests: off). It needs Droid (`STORMDESK_RUNNER=droid` uses the CLI's login, or `auto` with `FACTORY_API_KEY`); a fake runner never opens a PR.
- **Probes while building it** (scratch sessions, not stored runs; 25,715 credits in all, `claude-sonnet-5-5`): the CLI's login works inside the profile; `ls` was auto-run without a permission request (and killed by the profile); a Create on `server/stormcash/detectors.py` was refused, recorded and left the file untouched, while a Create on the allowlisted path was asked, allowed and written.
- **First live run, Oct 17** (run #95, operator "Claude for Alex", `claude-sonnet-5-5`, 21,186 credits, 36 s, 5 tool calls: ToolSearch, Create × 2, `run_tests`, `run_eval`; first attempt, 0 permission denials). Droid proposed `region_dark_alert_gate`: the two §13 thresholds plus at least one active weather alert. Our re-run matched every claim. Dev: precision 1.00, recall 1.00 (TP 5, FP 0, TN 4) vs rules-only 0.56 / 1.00; held-out: 1.00 / 1.00 (TP 3, FP 0, TN 3) vs 0.50 / 1.00. It opened Alexlgvcode/stormcash#122, labelled for a person and left open. Droid's caveats, which we share: the simulator plants an alert on every dark region and none on quiet-region traps, so the score shows the rule fits the simulator; a region that goes dark before any warning would be missed; 15 rows is a small sample.
- **Not built:** Linux sandboxing (bubblewrap), wiring a merged detector in automatically (by design), other gaps from the dashboard (the endpoint takes any kind).

### 14.8 Demo replay

Agent runs take 30–90 s. For the planted demo cases, run StormDesk ahead of time (Saturday night) and store transcripts. The dashboard can **replay** a stored transcript step by step (labeled "replay of run at 11:42 PM") or run live on request.

### 14.9 Factory requirement: README section "Where Droid runs"

Explain: worker file, the three jobs, the tools, structured outputs, the permission handler, and that Droid runs on every case and candidate in the running product. Include a screenshot of the live step stream.

**Done when:** a hard case and a merchant_silence candidate from the seeded town both produce valid outputs with verified citations, and the dashboard streams the steps.

---

## 15. Chalk: features, query tool, evaluations [v4]

**VERIFY** every API below against docs.chalk.ai in hour 1; the shapes here follow the docs as read on Friday.

### 15.1 Feature classes (`chalk/features.py`)

```python
from chalk.features import features

@features
class Merchant:
    id: str                       # merchant_id hex
    region_id: str
    simulated: bool
    contacts_per_hour_6h: float
    neighbor_median_contacts_6h: float
    silence_ratio_6h: float
    pool_funded_count_6h: int
    pool_funded_share_6h: float
    distinct_cheater_certs_6h: int
    near_cap_share_6h: float
    paired_contact_share_6h: float

@features
class Certificate:
    id: str
    home_region: str
    cap_cents: int
    spent_15m_cents: int
    distinct_merchants_15m: int
    region_mismatch_15m: bool
    minutes_since_storm_mode: int
    status: str

@features
class Region:
    id: str
    active_certs: int
    expiring_12h_share: float
    hours_since_last_upload: float
    active_alert_events: list[str]
    alert_source: str             # 'live' | 'replayed'
```

- **SQL resolvers** (`chalk/resolvers/*.chalk.sql`) read the hosted Postgres (§6.1) for Merchant, Certificate and Region features.
- **Python resolver** for live NWS alerts: `GET https://api.weather.gov/alerts/active?area=NC` with `User-Agent`, mapped to regions by county/zone; fallback to `weather_alerts` rows (`source='replayed'`).
- Features in the window are computed against **simulated time** for simulated data. Pass `as_of` (sim clock) as an input feature or query parameter. **VERIFY** the cleanest way in Chalk (time-travel/`now` input vs. explicit window columns). If unclear in 30 min, precompute window features in SQL views in Postgres and let Chalk SQL resolvers read the views.

**[v4.6] As built (verified against docs.chalk.ai and chalkpy 2.163).**
- **Sim time is an `as_of` feature** on each class (Unix seconds). A tiny SQL resolver per class defaults it to the sim clock, `max(uploads.received_at)` (the server's latest sync, which is "now" for the seeded town and for real phones alike); a query that passes `as_of` as an input skips that resolver. Window resolvers take `${ns.id}` and `${ns.as_of}` as parameters. Chalk's own clock (`Now`, `${now}`, `ChalkClient.query(now=...)`) is wall-clock time unless every caller passes the sim time, so it isn't used, and no Postgres views were needed.
- **Classes** (`chalk/features.py`), all windows ending at `as_of`:
  - `Merchant`: `name, region_id, simulated`, and over 6 h `contacts_per_hour_6h, neighbors_6h, neighbor_median_contacts_6h, silence_ratio_6h, accepted_count_6h, pool_funded_count_6h, pool_funded_cents_6h, pool_funded_share_6h, distinct_cheater_certs_6h, near_cap_share_6h, paired_contact_share_6h, one_sided_contacts_6h, prior_windows_flagged`.
  - `Certificate`: `status, storm_mode, home_region`, and over 15 min (inclusive) `cap_cents` (the version in force at `as_of`), `spent_15m_cents, distinct_merchants_15m, drain_share_15m, regions_15m, region_mismatch_15m, minutes_since_storm_mode, gap_since_last_activity_min, hour_of_day` (Asheville time).
  - `Region`: `name, county, active_certs, expiring_12h_share, hours_since_last_upload, merchants_open_6h, replayed_alert_events, live_alert_events, nws_reachable, active_alert_events, alert_source`.
  - Shares and times are `None` when there's nothing to divide or measure (no accepted payments, no own contacts, no Storm Mode). Definitions are §13's, as coded in `detectors.py`.
- **SQL resolvers** use the Chalk PostgreSQL integration **`neon_stormcash`** (added in the Chalk dashboard; credentials live only there, ideally a read-only role). Three per class: fixed attributes, the `as_of` default, the window features.
- **Frozen vs current.** A candidate's features are frozen when the detector fires; Chalk recomputes from everything the server holds now. Store-and-forward data arrives late, so they can differ for the same window (seed 42: Downtown Market's 6 h window gained contacts that turned out paired). `cap_drain` features matched exactly on all five seed-42 candidates.
- **NWS resolver** (`chalk/resolvers/nws.py`): one NWS call a minute at most; all four regions are in Buncombe County (SAME `037021`, zones `NCC021`, `NCZ053`). Live alerts win when NWS has any for the region; otherwise the replayed rows active at `as_of`. `alert_source` says which one `active_alert_events` came from (`replayed` whenever NWS is unreachable). `NWS_USER_AGENT` can be set as a Chalk secret; the default names the repo.
- Deploy: `cd chalk && uv sync && chalk apply`. Local checks: `chalk lint`, `uv run pytest`.

### 15.2 `query_features` tool

StormDesk calls Chalk's online query API through `ChalkClient().query(input={Merchant.id: ...}, output=[...])`. This is how Chalk "does real work" at runtime. Log every query (feature names, latency) for the Chalk add-on demo.

Fallback if Chalk is down: the tool reads the same features from Postgres views and marks the result `source: "postgres_fallback"`.

**[v4.6] As built.** `server/stormcash/chalk_features.py` holds the `ChalkClient` (string FQNs, so the server doesn't import `chalk/`; credentials from `CHALK_CLIENT_*` or the machine's `chalk login`; 10 s timeout). Tool args: `entity: merchant|cert|region, id, features[]?, as_of?`; `cert` maps to the `certificate` namespace, and no `features` means all of the entity's features. The answer is `{source: "chalk", entity, id, as_of, features, latency_ms}` (+ `errors`, `unknown_features`), and each query logs one line with the feature names and latency. If Chalk fails or `CHALK_DISABLED=1`, the tool returns the Postgres fallback as before (the detectors' frozen features for the subject's latest candidate, not views) with `source: "postgres_fallback"` and `chalk_error`.
- Deployed with `chalk apply` on Oct 16 and checked on the seeded town through the tool itself: Downtown Market's 16 merchant features in ~2 s on a cold client (token exchange, Neon waking up), then 125–350 ms per query for merchant, cert and region features.

### 15.3 Evaluations

**Dataset** (`chalk/evals/build_dataset.py`): rows from 5 simulator seeds (§16), one row per candidate.

| Column | Meaning |
|---|---|
| `candidate_id`, `kind`, `subject_id`, `features` | input |
| `label_kind` | ground truth: `merchant_silence` \| `cap_drain` \| `region_dark` \| `none` |
| `label_action` | ground-truth best action |
| `label_scenario` | `colluder`, `stolen_phone`, `dark_region`, `trap_remote_shop`, `trap_victim_shop`, `trap_stockup`, `trap_clock_drift`, `trap_quiet_region` |
| `honest_subject` | bool |

Target ~60 rows (time budget: 60 × ~60 s / 6 parallel ≈ 10 min per run).

**Task:** a `chalkcompute.function` that calls `POST {PUBLIC_BASE_URL}/v1/stormdesk/run {candidate_id}` and returns the Flag JSON. (Chalk's functions can't run the local `droid` CLI; the tunnel solves it.) **Fallback:** run the agent locally over the dataset and upload outputs as the result dataset, then score in Chalk.

**Scorers:**

| Scorer | Type | Pass condition |
|---|---|---|
| `valid-json` | built-in | output parses as Flag |
| `kind-correct` | function | `output.kind == label_kind` |
| `action-correct` | function | `output.proposed_action == label_action` |
| `no-false-flag` | function | if `honest_subject`, `output.kind == "none"` or severity `info` with action `none` |
| `citations-valid` | function | every `evidence_ids` exists (call `GET /v1/exists?ids=` or check against row's known ids) |
| `summary-quality` | LLM judge (stretch) | concise, cites evidence, no overclaiming |

**Comparison to show (Evals tab):** rules-only baseline vs. StormDesk on the same rows:

| Metric | Rules only | StormDesk |
|---|---|---|
| Colluders caught (recall) | from run | from run |
| Honest subjects flagged (false-flag rate) | from run | from run |
| Precision per kind | from run | from run |
| Citations valid | n/a | from run |
| Pool $ protected (held correctly) | from run | from run |

**Never type numbers into this table by hand.** The tab renders the latest stored run (`chalk/evals/results/*.json`) with the run id and timestamp.

**[v4.7] As built (#33, `chalk/evals/README.md`; verified against docs.chalk.ai and chalkcompute 2.13.7).**
- **Dataset.** Seeds 42, 7, 13, 99 and 2026, 72 h from a fixed T0 (2026-10-14 00:00 UTC). Rebuilt from the #82 simulator (colluders take pool money R5 can't deny), they give **43 rows (20 honest)**, under the ~60 target. The first build, from the old simulator, gave 48 rows. Labels come from each seed's `labels.json` by subject. `honest_subject` means "flagging it is a false flag" (every trap); a `hard_case` subject's soft candidate takes the candidate's kind. `trap_clock_drift` never raises a candidate. `meta.json` lists the labelled subjects no detector raised; no runner sees them. Re-running gives the same rows byte for byte.
- **One local database per seed** (`stormcash_eval_<seed>`, Docker Postgres, `schema.sql` + `migrations/`), never the hosted demo DB, because towns from two seeds share the grid and would skew `merchant_silence`'s neighbour median. The towns are signed with a throwaway eval key.
- **Task path.** One server per seed (Nessie, Photon, background loops and the worker off; `CHALK_DISABLED=1`, since `neon_stormcash` points at the demo DB, so `query_features` answers `postgres_fallback` from the eval DB). A stdlib gateway (`gateway.py`) sits in front of them behind one cloudflared quick tunnel and a bearer token. The task `sd-stormdesk-triage(seed, candidate_id)` posts a job and polls until it's done, because a Droid run can outlast the tunnel's ~100 s response limit. The gateway calls the real `POST /v1/stormdesk/run {candidate_id}` and exposes no other route.
- **Output** = the Flag JSON plus `_run` (the server's `runner`, `citations_valid`, `missing_citations`, `fallback_from_droid`, `run_id`). A run with no Flag returns plain text, so `valid-json` fails it.
- **`citations-valid`** reads the server's own §14.7 check, made against the eval DB when the flag was stored, so no `GET /v1/exists` endpoint was needed. It isn't in the rules-only evaluation, because the baseline cites nothing (n/a).
- **`no-false-flag`** passes non-honest rows (the "if honest_subject" in its pass condition), and the results file also gives its honest-only mean.
- **Every scorer returns one score.** Chalk computes no score summary for a run whose scorers return lists (checked Oct 17).
- **Rules-only baseline** is its own Chalk task (`sd-rules-only`): deterministic, no server. **Fallback** `run_local.py` runs every row through the local gateway, uploads rows plus `agent_output`, and scores them in Chalk with a replay task.
- **Honesty.** The results file takes its runner from the outputs. Only an all-Droid run with no fallback fills the StormDesk column (`table_column: "stormdesk"`). A fake or mixed run is saved with `runner: "fake"` / `"mixed"` and `table_column: null`.
- `summary-quality` (LLM judge) isn't built: the environment's Model Gateway serves no models.
- **Droid guard [v4.11].** Droid's session files (`~/.factory/sessions/<cwd>/<id>.jsonl` and `.settings.json`) record each message's `modelId` and the session's `factoryCredits`. The gateway copies them into every row's `_run` and audits every session the eval servers wrote, retries included. Its breaker refuses further rows on a model change (Factory switches to "Droid Core" when Standard Usage runs out), on a fallback, on an unreadable session, or at `--max-credits`. A StormDesk result needs every row on the one named model and a complete run. Measured on 3 seed-42 rows with `claude-sonnet-5-5`: 47,054 / 16,052 / 33,393 credits, 28–46 s each.
- **[v4.11] First real run, Oct 17**, on the rebuilt 43-row dataset. Rules-only `71142eed-2864-413d-ac27-da1e3c537e50`. StormDesk (Droid) `a91828a0-342b-4030-b046-a926fe5ade9d`: all 43 rows and 43 sessions on `claude-sonnet-5-5`, no fallback, breaker never tripped, 1,404,702 Factory credits. Results: `chalk/evals/results/20261017T134729Z-rules_only.json` and `20261017T135917Z-droid.json`.
- **[v4.11] Prompt v2 re-run, Oct 17** (#86, written after reading v1's errors on these rows, so not a blind holdout).
  - A first attempt, `b30fd876-16e0-4002-b118-6bcfe116c0f7` (1,314,180 credits), was answered by stale prompt-v1 servers. It's discarded: the `prompt_version` check kept it out, and #88 fixed `stack.py`.
  - The real attempt, `aca3204b-db75-4908-a388-4594d4ee97a7`, ran prompt v2 on `claude-sonnet-5-5` for 32 rows. The 1.6M admission cap refused the other 11 (1,481,125 credits including a check row). It's saved as incomplete and isn't a score; the StormDesk column stays v1.
- **[v4.14] Prompt v2, complete (#100).**
  - Run A, `4119a11e-018f-41ae-86fc-9cede513969f`: all 43 rows, `claude-sonnet-5-5`, prompt v2 on every row, 1,815,847 credits. It fills the StormDesk column; v1 stays as an older run.
  - Run B, `51b74f56-d8d8-466b-a07c-3ddf8baa8064`: held-out seeds 1 and 2 (20 rows), next to rules-only `dc1fd4c9-734e-408d-8c48-9c583dcb3867` on the same rows, 937,859 credits.
  - The held-out seeds 1, 2, 3 were fixed in writing before their rows existed. Seed 3 was left out by the credit rule written before run A.
  - Held-out results are their own `eval` (`stormdesk-triage-heldout`), served under `heldout` by `GET /v1/evals` and shown in their own panel.
  - 4 of B's task calls were delivered twice by Chalk (136,808 extra credits), so the gateway's `POST /runs` is now idempotent on a `request_id`.
- **[v4.16] Reviewer eval (§14.7b), Oct 17.** Run B's 20 held-out prompt-v2 outputs were frozen and reviewed live, one at a time, from this machine (the review endpoint isn't idempotent), then scored in Chalk as "v2 alone" (`28f97eca-0402-4c86-9c76-5e380eae6dc0`) vs "v2 + reviewer" (`e3ecc828-c97e-41d3-9cf8-d7185b3d8013`) on one dataset revision.
  - Real cases reaching a person: 6/9 → 8/9. Honest subjects reaching a person: 0/11 → 0/11. Kind and action unchanged by design (17/20).
  - 20 valid reviews on `claude-sonnet-5-5`, reviewer prompt v1, 799,185 credits.
  - Results are in `chalk/evals/results/review/`.
- **Pipeline checks, Oct 17**, on the first 48-row dataset, 48 rows each with no row errors: rules-only `85ec3bf0-3cf2-4cd9-bde2-0fb2b0d38326`, fake runner through the tunnel `edfbe2bc-aabe-4aa7-99e5-594e217ecf12`, `run_local.py` `e0bff8a4-53e9-4545-adec-9e45a1538519`. These ran before Factory credits arrived.

---

## 16. Town simulator (40 shops) [v4]

### 16.1 Purpose

One simulator feeds four things: the Town tab backdrop, StormDesk's data, the Chalk eval dataset, and the "how often does this work?" answer (share refused offline, caught at settlement, loss per cheater, time to settlement vs. relay density).

### 16.2 Rules

- Python, in `sim/`, imports `server/stormcash/protocol` and calls `settlement.ingest_items()` directly. The town is checked by **exactly** the same code as the real phones.
- Simulated entities generate real P-256 keys and real signatures. `simulated=true` on every row. Ledger-only money (no Nessie).
- Deterministic by `--seed`. Virtual clock; a 72 h storm simulates in < 60 s.
- **[v4.3] As built (`python -m stormcash_sim --seed 42 --hours 72`):** keys, cert ids and merchant ids are derived from the seed, so the same seed gives the same town byte for byte. Only adopters are modelled; residents make trips to shops and phones meet within 2 cells at a shop; shops don't link to each other directly (customers carry records, §24 Q5); a pair syncs at most once an hour; a carried item is dropped an hour after the server first had it (standing in for receipts gossiping down); POLICY travels as device state. A seed refuses to run twice into one database. The Deps must have Nessie off.
- The UI labels every simulated shop and resident "simulated".

### 16.3 Town model

- Grid 40×24 cells. 4 regions (Buncombe County names for flavor): `asheville-downtown`, `west-asheville`, `black-mountain`, `swannanoa`.
- 40 merchants placed in clusters per region. 2 of them are the **real** demo phones (Pharmacy, Gas Station), drawn at fixed positions in `asheville-downtown`. **Corner Store** is a simulated merchant (ledger-only money) with one real thing: its Photon contact is the laptop at the table.
- ~400 residents with home regions; 60% adoption by default; each has a cert (cap 20 always-on, 50 after Storm Mode at T+2 h for 70%).
- Residents walk: pick a destination merchant weighted by distance; travel time by distance; pay at merchants (amounts $3–$45, log-normal).
- Phones meet when within 2 cells at the same tick (probability `p_link`, default 0.6) → run the sync logic (simplified: exchange item sets, write CONTACT entries both sides).
- Relays: a phone gets internet with probability `p_uplink` per hour (default 0.03; a shelter merchant in `asheville-downtown` has uplink 0.5/h).
- Tick = 1 simulated minute.

### 16.4 Scenarios (labels for evals)

| Scenario | Count/seed | Behavior | Ground truth |
|---|---|---|---|
| `double_spender` | 6 | rolls back after a payment, spends again 1–3 shops later (half reuse counter, half skip) | hard cases (R1/R2/R3) |
| `colluder` | 2 | merchant turns gossip off for 6 h and accepts payments from double spenders (**[v4.10]** pool-funded re-spends from 3 cheaters that R5 can't prove, so the pool pays the shop); in seed 42, Corner Store also accepts one double spend right after a paired contact that delivered the conflicting tag (plants an R5 MERCHANT_KNEW case for the Digital Trust add-on) | `merchant_silence`, `hold_pool_payout` (+ the R5 hard case) |
| `stolen_phone` | 2 | cert drains ≥ 80% at 3+ shops in 15 min, in a non-home region, after ≥ 3 h idle | `cap_drain`, `freeze_cert` |
| `dark_region` | 1 | `swannanoa` loses all uplink for 60 h during an active alert | `region_dark`, `dispatch_relay` |
| `trap_remote_shop` | 2 | honest merchant at the map edge, low contacts, receives 1 pool-funded payment as a **victim** of a double spender | `none` |
| `trap_victim_shop` | 2 | honest merchant briefly silent (generator out, no payments) then victimized once | `none` |
| `trap_stockup` | 3 | honest resident spends ≥ 80% at 3 shops in their home region within 30 min of Storm Mode | `none` |
| `trap_clock_drift` | 2 | honest phone clock 8 min off | `none` (no hard rule fires; only noise) |
| `trap_quiet_region` | 1 | region with no uploads for 48 h but few active certs and no alert | `none` or `info` |

### 16.4a As built [v4.3]

- Scripted double spends pay first at the Downtown Shelter, which is forced to upload, so the rolled-back re-spend elsewhere needs guarantee-pool money ($35 of a $50 cap: $20 from the pool). Organic double spenders roll back 1–3 shops later, up to twice; their phones relay nothing.
- `colluder`: Corner Store (gossip + uplink off T+26–32 h) and one clustered shop (T+50–56 h); their app accepts what fails C2/C6 but logs honestly. **[v4.10]** In its silent window each colluder takes re-spends from 3 scripted double spenders (each pays the Shelter first, then re-spends $35 at the colluder: $20 of it pool money). No paired contact brings the shop a conflicting tag and nothing is in its `held_ids`, so R5 can't prove it knew. The pool pays it $60, the hard rules catch only the cheaters, and only `merchant_silence` (3 distinct cheater certs, $60 pool-funded, no contacts) points at the shop. The R5 courier is never a resident of the dark region: its scripted upload at T+35 h would end Swannanoa's dark window. The planted R5: a courier syncs with the Shelter, then with Corner Store (a paired contact carrying the tag), then the rolled-back wallet pays Corner Store, whose ACCEPT lists the tag in `held_ids` → MERCHANT_KNEW (clause a).
- `stolen_phone`: an idle phone pays 3 West Asheville shops $15 + $15 + $13 in 8 minutes. `dark_region`: no uplink in Swannanoa T+6–66 h; the sim inserts the Flash Flood Warning as `source='replayed'`. `trap_remote_shop`: two West Asheville shops moved to the map edge. `trap_victim_shop`: shut 4 h first. `trap_stockup`: $15 + $14 + $13 right after Storm Mode. `trap_clock_drift`: +8 min. `trap_quiet_region`: Black Mountain without uplink from T+12 h, no alert.
- `labels.json`: `{seed, start, hours, subjects: [{subject_type, subject_id, name, scenario, expected_kind, expected_action, hard_rules, note}]}`; `expected_kind` is a soft kind, `hard_case` or `none`.
- `stats.json`: `double_spends` (attempts, refused offline, accepted offline, caught at settlement, shares, refusals by check), `cheaters`, `mean_loss_per_cheater_cents` (pool money paid on cheaters' certs ÷ cheaters), `median_hours_to_settlement`, `hops_histogram`, plus counts of candidates and cases.
- Seed 42 (checked by `sim/tests/test_scenarios.py`): R1/R2/R3 cases, MERCHANT_KNEW at Corner Store, and `merchant_silence` (colluders and traps), `cap_drain` (stolen phones and stock-up traps) and `region_dark` (Swannanoa and the quiet-region trap) candidates, every one on a labeled subject; the honest town alone produces none.

### 16.5 Outputs

- Writes everything into Postgres through `ingest_items()` (uploads happen when simulated relays get uplink).
- `sim/out/<seed>/labels.json`: ground truth per subject.
- `sim/out/<seed>/stats.json`: share of double spends refused offline, caught at settlement, mean loss per cheater, median time to settlement, hops histogram. These feed the Town tab charts.
- `POST /v1/demo/seed-town {seed}` runs seed 42 into the live DB with the planted demo cases: **Corner Store** = colluder (with the real Photon handle), one stolen phone, `swannanoa` dark. **[v4.3]** Operator header required; answers 202 and runs in the background (72 h ending now; Nessie off; simulated events go to a quiet broker), `GET /v1/demo/seed-town` reports `{status, progress, summary}`, and a `town` SSE event fires when it's done. Body: `{seed, hours, residents, corner_store_contact?: {channel, handle}, replace?}`. **[v4.10]** `replace: true` first clears the simulated town (`demo.clear_town`: every simulated resident and shop and what touches them, every `region_dark` candidate, whole ledger transactions, the shops' Photon threads). Real-device data stays, and the shops' Photon handles are restored on the new town (a seed derives the same shop ids). Use it to re-seed after a scenario change; without it the same seed is refused. **[v4.4]** Seed 42 takes ~45 s against the hosted Neon DB (it was ~46 min with a transaction per item) and ~8 s locally; still seed before the judging slot.

### 16.6 Sliders (Town tab)

Adoption, foot traffic (`p_link`), relay density (`p_uplink`). Moving a slider runs a quick re-sim (seeded, ≤ 3 s, in-memory, not written to DB) and replots: share refused offline, caught at settlement, loss per cheater, median hours to settlement.

**[v4.3] As built.** `sim/stormcash_sim/quick.py` uses the same town, trips, gossip and relay rules as the full simulator, but payments are plain ids (no signatures, no DB). It pools 5 seeded runs with 8% of adopters double spending, so each answer covers about 160 attempts. A shop's stored tags (for C6) are kept apart from what it carries to relay, which is dropped an hour after the server has it. `GET /v1/town/quick?adoption&p_link&p_uplink` returns `{baseline, current}` (answers are cached). The Town tab shows each metric as default town vs your settings, labelled simulated. Measured end to end: a slider move replots in about 2 s.

**Done when:** `seed-town 42` produces the planted cases plus candidates for all three soft kinds, and stats.json has all metrics.

---

## 17. Photon messaging agent [v4]

**VERIFY Photon 2.0's SDK/webhook shapes from the official guidelines and docs** (linked from hhuh.io) and the Friday workshop. Do not guess field names. Wrap it in `photon/client.py` with two functions: `send(channel, handle, text)` and a FastAPI route for inbound messages.

**[v4.5] Verified Oct 17 against photon.codes/docs (Stable, Spectrum).**
- **Inbound:** Spectrum Cloud POSTs each message to `POST /v1/photon/inbound` as JSON `{event: "messages", space, message}`; `message.content` is tagged by `type` (`text` has `text`), `message.sender.id` is the platform user id, `message.id` is the dedup key (at-least-once delivery). Headers `X-Spectrum-Timestamp` and `X-Spectrum-Signature: v0=<hex>`, an HMAC-SHA256 with the webhook secret over `v0:{timestamp}:{raw body}`; reject if more than 300 s off.
- **Outbound:** sending exists only in the TypeScript SDK (`spectrum-ts`; Telegram: `telegram(app).user(id)` → `space.create(user)` → `space.send(text)`). So `server/stormcash/photon/bridge/` is a ~90-line Node process the Python `client.send` calls over localhost with a bearer token. Env for the bridge: `PROJECT_ID`, `PROJECT_SECRET`, `TELEGRAM_BOT_TOKEN`, `PHOTON_BRIDGE_TOKEN`.
- `merchant_contacts.handle` for Telegram is the numeric Telegram user id (stringified).

### 17.1 Channels

- **Primary:** Telegram (Telegram Desktop on a laptop at the table).
- **Optional:** iMessage via Messages on a Mac signed into a teammate's Apple ID.
- Phones are in airplane mode during the demo, so the "merchant" conversation lives on a laptop.

### 17.2 Flows

| Flow | Trigger | Message |
|---|---|---|
| Hold notice | Operator approves `hold_pool_payout` or `lower_merchant_limit` | Agent's `merchant_notice` draft, checked to contain no invented numbers (numbers must match the flag's evidence), e.g. "Corner Store: your $140 guarantee-pool payout is on hold. Your phone logged no contact with other phones from 2–8 PM while 2 nearby shops logged 41. Reply to explain." |
| Appeal | Merchant replies | StormDesk `respond` job (§14.1) gets the message + `get_messages` + logs; replies with evidence; if `escalate`, flag status stays open with the appeal attached; dashboard shows the thread |
| Settled notice | Payout executed | "Paid: $12.00 from StormCash for payment at 4:12 PM." (template, no agent) |
| Resident FREEZE | Resident texts `FREEZE` from their registered handle | Freeze cert, new POLICY, confirm by text. Feeds `owner_freeze_request` in cap_drain. Mention in pitch; demo only if time allows. |

**[v4.13] Resident FREEZE, as built (`photon/freeze.py`).**
- The text must be exactly `FREEZE` after trimming, in any case. It comes from a handle in `resident_contacts` (set by `contact` on register, or by the operator with `POST /v1/photon/resident-contact`). The handle isn't verified (demo only; a real deployment would confirm it with a code).
- Deterministic, never through StormDesk: every cert of the resident that isn't `closed` goes through `cases.freeze_cert` (`cert_status = 'frozen'`, a new signed POLICY, SSE `policy`), `cert_status.owner_freeze_at` is set once, and SSE `owner_freeze` fires. A second FREEZE changes nothing (no new POLICY) and gets the same confirmation; duplicate webhook deliveries are dropped by message id.
- Reply (template): "Your StormCash wallet is frozen. Shops will refuse it as the freeze list spreads." The FREEZE and the reply are recorded on the resident's thread (`messages.resident_id`). With `PHOTON_DISABLED=1` the freeze still happens and the reply is recorded with `delivered: false`.
- Texting can't unfreeze: any other text from a resident gets "Text FREEZE to freeze your StormCash wallet. Texting can't unfreeze it." A FREEZE from an unknown handle gets a neutral reply ("This account isn't linked to a StormCash wallet, so nothing was changed.") and changes nothing; other texts from unknown handles are ignored.
- One handle can be both a shop and a resident (one Telegram account at the table): `FREEZE` is the resident's, anything else is the shop's appeal.
- Dashboard: Cases → Owner freezes lists them with the thread; a `cap_drain` flag on a frozen-by-owner cert shows the request.

**[v4.21] Appeals as one conversation, as built.** Each shop's appeal thread (shop + flag) is one Droid session, resumed for every new text, so the agent remembers what the shop said and what it checked, and argues from it (§14.7c). The citation check still applies to every reply. FREEZE is untouched: it never reaches StormDesk. `STORMDESK_APPEAL_SESSIONS=0` gives one run per message.

### 17.3 Demo conversation (target)

```
StormCash: Corner Store, your $140 guarantee-pool payout is on hold. Your phone logged no contact
           with other phones from 2–8 PM while 2 nearby shops logged 41. Reply to explain.
Merchant:  we were closed, generator died
StormCash: Your log shows you accepted 3 payments at 4:12, 4:30 and 5:05 PM during that window.
           I've sent this to a reviewer with your reply attached.
```

The agent's reply must cite real log entries (citation check applies).

### 17.4 Voice (stretch, last)

Photon's best voice agent prize: the same appeal flow by phone call. Only after everything else.

**Done when:** approving the Corner Store flag sends the notice to the laptop, a typed reply gets an evidence-based answer within 60 s, and the thread shows on the dashboard.

---

## 18. Dashboard

React + Vite + TS, one page with four tabs and a persistent header. Live via SSE. Big fonts: judges stand 1 m away. **[v4.16]** A fifth tab, Droid (§18.7).

### 18.1 Header

Title, "Demo mode", connection dot, **Reset demo** button (calls `/v1/demo/reset`, < 30 s), clock.

**[v4.23] As built (#93).** The header is a left sidebar: "StormCash", the tabs with small icons (Accounts, Cases, Town, then an "Agents" group with Droid and Evals), and at the bottom "Demo mode", "Nessie off: ledger only" when it is, the connection dot, the clock and Reset demo. Each tab opens with its title and a grey subtitle. The intro screen (#91) is gone: no Intro item, no `#intro` link, no I shortcut; the dashboard opens on Accounts. Design tokens (white page, hairline rules, carbon blue #2B3A9E as the only accent, status pills) live in `dashboard/src/index.css`; the shared pieces (page header, tabs, section, table, pill, button) in `dashboard/src/components/ui.tsx`.

### 18.2 Accounts tab (Capital One add-on)

- Cards: Maya Checking, Maya Escrow, Pharmacy, Gas Station, Guarantee Pool (Nessie), plus a "Simulated town (ledger only)" totals card. Live Nessie balances, labeled "from Nessie transactions" (§11.4); animate on change.
- Nessie call log (scrolling): `POST withdrawal Maya Escrow, $12 · completed` / `POST deposit Pharmacy, $12 · completed`.
- Ledger panel: "Ledger balanced ✓", totals per account type.
- Queued Nessie payouts counter (fallback visible).
- **[v4.17]** "Reconciled with Capital One Nessie" panel (§11.4a): per account ✓ or the difference with its explanation, how each side represents the opening, simulated money as "ledger only, never sent to Nessie", the `SC` pair check, when it last ran, and a Re-check button. It re-runs (debounced) on `accounts`, `payment`, `upload` and `nessie_call` SSE events. If Nessie can't be read it says so and shows the last successful check's time.

- **[v4.23] As built (#93).** Three views. **Balances**: one status line ("Ledger balanced", "Reconciled with Nessie, n of n accounts", "Nessie queued: n" when payouts wait, the check's time), a table Account | Owner | Balance | Bank (owner per §11.4's account mapping; Bank is "Matches" or the difference with its reasons from the reconciliation), "Simulated town: n shops, ledger only, never sent to Nessie", and the latest Nessie calls (time, description, amount, status). **Reconciliation**: the full panel above as a table, with the pair check, the simulated-town line and the ledger totals per account type. **Nessie log**: "Nessie queued: n" and every logged call.

### 18.3 Cases tab (Digital Trust + Factory add-ons)

- **Hard case panel:** the two conflicting tags side by side, the broken rule highlighted, the field that conflicts in red. Buttons: **Verify it yourself** (in-browser WebCrypto ECDSA P-256 check against `holder_pub`), **Proof QR** (opens `/proof/<case_id>` on a judge's phone).
- **Case file** from StormDesk (markdown).
- **StormDesk panel:** list of flags; selecting one shows the summary, evidence links, and the live/replayed tool-call steps (`get_merchant_payments` ✓, `query_features` ✓, …). **Approve** / **Reject** buttons with operator name.
- Photon thread for the selected merchant flag.
- **[v4.3] As built.** The Cases tab switches between *Hard cases* and *StormDesk flags*. A flag shows its subject, summary, exposure, reasoning, evidence ids (marked as checked), the tool calls (live from `stormdesk_step`, or a stored run replayed step by step, labelled "Replay of run at …"), Run again, Approve / Reject with the operator's name, and the Photon thread live from `message` events. Each hard case has a StormDesk section (Investigate, live steps, replay). Fake-runner output carries a "Fake runner · rules only" badge everywhere.
- "Merchant knew" case view: the merchant's ACCEPT entry listing the conflicting tag, with its signature.

- **[v4.23] As built (#93).** Three views. **Proven fraud**: the case list, then the selected case: "CASE #n", the amount and what happened to it, a status pill, Proof QR and Verify it yourself, a summary strip (rule, where it was detected, exposure, certificate), the two tags as one table with the conflicting row tinted, the merchant-knew log, a Timeline and Payment details (from the case, its certificate and the payments' relay paths, matched by tag id), StormDesk and the case file. **Review queue**: a table of flags (subject, signal, exposure, second opinion, status), then the selected flag's proposal with Approve / Reject and the operator's name, evidence and agent steps side by side, the second opinion and the Photon thread. **Owner freezes**: the FREEZE-by-text list and the resident's thread.

### 18.4 Town tab

- SVG grid map: regions (shaded), merchants (dots; real ones larger and labeled; simulated ones labeled "simulated" in a legend), live payment pulses, relay uploads, region alert badges (labeled live/replayed), dark regions hatched.
- Relay path panel: recent payments with hop paths.
- Sliders (§16.6) + charts: share refused offline, caught at settlement, loss per cheater, time to settlement.
- **[v4.3]** `GET /v1/town` also returns `dark_regions` (a `region_dark` candidate in the last 6 h), active alerts with their source, and the latest simulator `stats.json` for a one-line summary. Payment pulses come from `payment` SSE events; merchants without pool eligibility are drawn amber.

- **[v4.23] As built (#93).** Three views: **Map** (a summary strip from the seeded town's `stats.json`, labelled simulated, then the map in light colors and a few recent relay paths), **Relay paths** and **What-if** (the sliders and the default-vs-yours table).

### 18.5 Evals tab (Chalk add-on)

- Run id, timestamp, dataset size, link to the Chalk run.
- Rules-only vs. StormDesk table (§15.3) and a per-scenario breakdown; a "trap cases it got right" list with one example opened.
- Empty state: "No eval run yet." Never placeholder numbers.
- **[v4.8] As built (#38).** `GET /v1/evals` reads `chalk/evals/results/*.json` (`EVALS_RESULTS_DIR` overrides) on every request, so a new run shows up without a restart (the tab also re-fetches every 60 s). The server re-checks each file before it fills a column: rules-only needs runner `rules_only`; StormDesk needs runner `droid`, `is_agent_result`, every row answered by Droid and no fallback to the fake runner. Every other run (fake, mixed, older) is listed by time, run id and the reason it isn't scored, never with its numbers. Until a Droid run exists the StormDesk column says "No StormDesk run yet" and the trap list waits for it. The Chalk run is identified by its run id and "Evaluations → StormCash → <evaluation>"; it is a link only if the results file carries `chalk.dashboard_url` (the dashboard URL format isn't verified). Planted subjects the detectors never raised are listed, not counted.

- **[v4.22]** "Ask Droid to write a detector" (§14.7d) under the eval sections: the gap from the stored StormDesk runs (dark regions caught on dev and held-out rows) and the dev rows Droid is shown, the operator's name, the button (off with the reasons when the server can't run it), the live tool calls (`StepList`), then a result card: the verdict, the Droid badge with model and credits, the PR link, the rationale, our re-run's metrics table, each check ✓/✗, Droid's caveats, what the sandbox refused, the code Droid wrote and the replayable steps.

- **[v4.23] As built (#93).** Three views, held-out towns first: **Held-out towns** (a strip with seeds, cases, model and Chalk run, the comparison, the scenarios, both runs, then "Ask Droid to write a detector"), **Main dataset** (the same, plus the trap cases and the planted subjects not in the dataset) and **Runs** (every saved run that isn't scored, with its reason, and Reload results).

### 18.6 Public proof page `/proof/:caseId`

Mobile-friendly, no login. Shows the two tags, the rule, and a **Verify** button that runs WebCrypto ECDSA verification in the judge's browser against the holder key and the server-signed certificate. Explains in two sentences why this proves cheating.

**[v4.3] As built.** `dashboard/src/verify.ts` rebuilds each signed string from the displayed fields with the §7.2 rules (TAG, CERT, DLOG), so the server can't show one thing and sign another; checks the CERT against the server key, both TAGs against the cert's `holder_pub`, re-checks the rule from the fields, and for MERCHANT_KNEW checks the merchant's own ACCEPT entry and that its `held_ids` list payment A. Compressed keys are decompressed in JS (WebCrypto imports raw keys uncompressed). `npm test` runs the same code against `spec/vectors.json`. WebCrypto needs a secure context, so the proof link must be HTTPS: the server serves the built dashboard (`dashboard/dist`) from the same origin as the API, the Proof QR points at `PUBLIC_BASE_URL/proof/<case_id>` (the cloudflared tunnel), and a build can bake the server key in with `VITE_SERVER_PUB` (base64url) so the page doesn't take the key from the server it is checking.

**[v4.20] Second check: the C++ verifier, as WebAssembly.** Each press of **Verify** also runs `stormcash-verify`'s proof check (`cpp/verify`, the code behind `stormcash-verify proof`) in the browser, on the same `/v1/proof` JSON and with the same server key. It shares no code with the WebCrypto check: it decodes the transport JSON with its own strict codec, rebuilds every canonical string and digest, re-derives the rule, and uses its own P-256 (p256-m) and SHA-256 instead of the browser's. WebCrypto stays the primary result, exactly as before. The C++ verdict is shown under it, then one line: **"Verified by 2 independent implementations"** when both verify, **"Neither implementation verified this proof"** when neither does, and **"The two implementations disagree"** otherwise, never hidden. If WebAssembly can't load, or the C++ side can't read the file, the card says **"C++ check unavailable"** and the WebCrypto result stands alone. The module is built from `cpp/verify/wasm/` with Emscripten 6.0.10 and committed as `dashboard/src/wasm/` (518 KB, 163 KB gzipped), loaded only by the proof page. CI's `wasm` job rebuilds it and fails unless it equals the committed files byte for byte; `npm test` runs both checks on proofs captured from the server and on tampered copies. The C++ verifier passes all 124 vectors and Project Wycheproof's P-256 tests with both its crypto backends (OpenSSL natively, p256-m in the browser).

**Done when:** the full core demo runs with only dashboard clicks + phones, and every tab survives a page reload.

**[v4.23] As built (#93).** Light and phone-first: the rule and why, one full-width Verify button, then "Checked on your phone" with a row per implementation (WebCrypto first) and the agreement line, the browser's checks, the C++ verifier's answer, and the two tags as one table with the conflicting row tinted.

### 18.7 Droid tab (Factory add-on) [v4.16]

What Droid does in the running product, at the table in seconds, from stored runs only (§0 rule 3). `GET /v1/droid/console` (`server/stormcash/routes/droid_console.py`, read-only transaction) aggregates `stormdesk_runs`:

- **Per run:** job (investigate, triage, respond, review), model used and requested, prompt version, duration (`finished_at − started_at`), Factory credits, StormDesk tool calls (Droid's own `ToolSearch` counted apart), verdict, and one outcome: `valid`, `invalid_citation`, `structured_output_failed` (failed after its retry), `fallback` (Droid couldn't run, the fake runner answered), `fake` (`STORMDESK_RUNNER=fake`), `failed`, `running`, or `unfinished` (`running` for over 15 min).
- **Totals per job** count Droid's own finished runs (valid share, mean credits and duration). Fake-runner runs, fallbacks included, are counted beside them and never in a success rate.
- **Guardrails:** invalid citations rejected, structured output failed after the retry, fallbacks, and, once runs record them (`transcript.attempts`, `transcript.permission_denials`, or `fallback_attempts` / `fallback_permission_denials` for a fallback's Droid attempt, §14.7b), structured-output retries and permission-handler denials. A guardrail no stored run records has a null count and the tab says "not recorded yet", never 0.
- **Reviews (§14.7b):** verdict counts of valid Droid reviews; `transcript.reviewed.run_id` links a review to the run it checked.
- **Appeals (§14.7c) [v4.21]:** respond runs that are turns of an appeal's Droid session: turns, sessions, how many turns resumed a session and how many restarted from the stored thread. Each such run is labelled "appeal turn N".
- **Harness:** the 11 read-only tools, the built-in tools switched off, prompt versions, the runner new jobs get now, and Droid's cool-down if one is on.

- **[v4.22] Author runs (§14.7d):** job `author`, subject "detector for <kind>", verdict "<name>: PR #N opened" / "re-run matched" / "rejected by the re-run", outcome `rerun_rejected` ("Re-run rejected") when our re-run didn't match, and a guardrail "Proposed detectors rejected by the re-run". Their tool calls (sandbox reads, Create/Edit, `run_tests`, `run_eval`) count "in the sandbox", not read-only, and never as built-ins "still seen". The harness says `author_on`.

The tab (`#droid`): summary tiles, Droid's runs (fake-runner runs behind a toggle, badged), a run view with its tool calls replayed step by step (the Cases tab's `StepList`), the guardrail events with links to their runs, totals per job, and runs in progress live from `stormdesk_step`. Empty state: "No StormDesk runs yet."

**[v4.23] As built (#93).** Three views under a summary strip (Droid runs, valid outputs, credits, mean time, invalid citations, write tools) and the harness line: **Runs** (live runs, the runs table and the selected run's facts and steps), **Guardrails** (each guardrail with its runs, and totals per job) and **Detector proposals** (the author runs and "Ask Droid to write a detector").

---

## 19. Mobile app

### 19.1 Roles and setup

Same app for everyone. First launch: choose **Resident** or **Merchant** (hidden demo menu can also assign a **demo label**: `MAYA`, `PHARMACY`, `GAS_STATION`). Setup needs internet: generate a P-256 key (software key in SecureStore; Secure Enclave timeboxed swap, §19.6), register, receive cert or merchant cert, download the latest policy.

### 19.2 Screens

| Screen | Role | Contents |
|---|---|---|
| Wallet | Resident | Big remaining balance ("$38 of $50 left"), cert status, Storm Mode toggle (online only), "Carrying N records", offline/online badge |
| Pay | Resident | Camera scans REQ QR → "Pay Pharmacy $12.00" → Face ID → shows PAY QR |
| Charge | Merchant | Keypad (whole dollars for the real demo merchants, §11.4 **[v4.2]**) → shows REQ QR (2-min countdown) → "Scan customer's code" |
| Scan payment | Merchant | Camera scans PAY QR → runs C1–C6 |
| Result | Merchant | **Green:** "Verified. Backed by Capital One, $12 of $50 used." **Red:** names the failed check and rule, e.g. "Refused: these funds were already spent nearby (Rule: same counter). Certificate flagged." |
| Records | Both | Carrying N items by kind, nearby peers, last sync, "Sync by QR" button, last upload + hops |
| Demo menu (hidden: long-press logo) | Both | Demo label, demo topology on/off, **Judge mode**, reset local data, show device pub |

### 19.3 Judge mode (attacker tool)

Banner: **"Demo: attacker tool"**. Big red **Roll back wallet** with two modes:

- **Reuse the money:** restore the wallet to before the last payment (same counter, same running total).
- **Be clever:** restore, then skip the counter (counter +1 past the real one, running total from before the payment).

Both produce payments that the gas station refuses via C6 (R1 or R2/R3), as long as it holds the pharmacy's tag. Copy explains: "This is what a modified app or a restored backup could do."

### 19.4 Local stores (SQLite)

| Table | Contents |
|---|---|
| `wallet` | cert versions, counter, cum, chain head, holder key ref |
| `items` | every syncable item (§10.2): id, kind, body JSON, path, priority, received_at, receipted |
| `device_log` | own DLOG entries |
| `peers` | last seen peers, sessions |
| `merchant_state` | open request (nonce, amount, expiry), merchant cert, limit |
| `policy` | latest verified policy |

### 19.5 Transport

`transport/index.ts` exposes one interface; implementations: `multipeer` (expo-nearby-connections or `modules/sc-multipeer`) and `qr`.

```ts
interface Transport {
  start(deviceLabel: string): Promise<void>;
  onPeer(cb: (peer: Peer) => void): void;
  open(peer: Peer): Promise<Channel>;     // runs §10.3 session
  stop(): Promise<void>;
}
```

- Advertise + browse while the app is foregrounded. Respect the demo topology allowlist.
- Show peer connections on the Records screen and a small dot in the header.

**Hour-1 test:** two iPhones in the hall discover and exchange a 2 KB message within 5 s, 5 times in a row. If not, write `modules/sc-multipeer` (Swift, ~150 lines: `MCPeerID`, `MCSession`, `MCNearbyServiceAdvertiser`, `MCNearbyServiceBrowser`, auto-invite and auto-accept within the allowlist) before anything else in the transport.

### 19.6 Hardware keys (timeboxed 1 h, Saturday)

Swap the software key for a Secure Enclave key (`kSecAttrTokenIDSecureEnclave`, ECDSA P-256, signs digests). Needs a small native module; DER → raw conversion helper. If not done in 1 h, stay on software keys and say so on stage.

### 19.7 Performance

- Payment QR end to end (scan REQ → Face ID → show PAY → merchant scans → result): **< 10 s**. Measure on Saturday.
- Install **Release** builds Saturday night. Grant camera, local network, Bluetooth, Face ID during setup, never on stage.

**Done when:** with all 3 phones in airplane mode (Wi-Fi and Bluetooth back on, no network joined), Maya pays the pharmacy, rolls back, and the gas station refuses, with the pharmacy's tag having reached it through Maya's phone.

---

## 20. Test vectors

`spec/gen_vectors.py` (Python, `cryptography`) generates `spec/vectors.json` from **fixed private keys** (hard-coded test scalars) for: server, Maya (holder), Pharmacy, Gas Station, Corner Store.

Each vector:

```json
{
  "name": "tag_counter1",
  "type": "TAG",
  "fields": {"cert_id": "…hex…", "counter": 1, "...": "..."},
  "canonical": "SC1|TAG|…",
  "digest": "…hex…",
  "pub": "…hex…",
  "sig": "…hex (raw r||s, low-S)…",
  "valid": true
}
```

Required vectors:

1. GEN, CERT v1, CERT v2 (Storm Mode), MCERT, REQ, DET, TAG counter 1, TAG counter 2, PAY.
2. One **negative** vector per offline check C1–C6.
3. One pair per equivocation rule R1, R2, R3, plus a valid 3-tag chain (no rule fires).
4. R4 over-cap scenario (sequence of tags + caps).
5. DLOG chain of 4 entries (ACCEPT, CONTACT, CONTACT, REFUSE) + a forked chain (R6) + a broken link (R6).
6. R5 scenarios: (a) via `held_ids`, (b) via paired contact, (c) one-sided contact (must **not** fire R5).
7. CONTACT id computed by both sides.
8. POLICY, RCPT, RENEW.
9. A high-S signature that must verify.
10. A DER signature from Python converted to raw.

Tests: `server/tests/test_vectors.py` and `mobile/src/protocol/__tests__/vectors.test.ts` both load `spec/vectors.json` and must reproduce every canonical string and digest byte for byte, verify every valid signature, reject every invalid vector, and agree on every rule outcome.

**File layout.** Object vectors (`objects`) use the shape above, plus `json` (the transport form, which the codec must produce exactly) and `item_kind` / `item_id` / `id8` for item types. Scenario sections carry objects as `{type, fields, sig}` with hex bytes, and an `expect` block: `encoding`, `pays`, `signatures`, `der`, `contact_ids`, `single_tag`, `equivocation`, `proofs`, `merchant_checks` (C1–C6 with reason tokens, §8.2), `over_cap` (R4), `log_tamper` (R6), `merchant_knew` (R5). `spec/README.md` lists what each section checks. Signing is RFC 6979 deterministic, so regenerating gives the same file byte for byte, and `test_vectors.py` fails if the committed file is stale.

**This is the first thing built (WS0).** Nothing else merges until both test files pass.

---

## 21. Demo: table, scripts, sponsor add-ons

### 21.1 Table

- 3 iPhones on stands, labeled **Maya**, **Pharmacy**, **Gas Station**, all on Release builds, chargers + power bank.
- Mac 2: dashboard full screen (Accounts tab open). Second browser tab: proof page.
- Mac 1: Telegram Desktop logged in as the **Corner Store owner**.
- A printed **Proof QR card**.
- Phones in airplane mode with Wi-Fi + Bluetooth on, no network joined. Gas Station has a hotspot or venue Wi-Fi ready for the reconnect beat.

Pre-staged before each judging slot: `/v1/demo/reset`, Maya cert at Storm Mode $50, seeded town loaded, StormDesk replays ready.

### 21.2 Core script (2:30, every judge)

| Time | On screen / table | Say |
|---|---|---|
| 0:00 | Helene photo slide | "After Hurricane Helene, card readers in Asheville went dark and ATMs ran dry. A month later some shops were still cash-only. People had money in the bank and phones with battery, and still couldn't pay." |
| 0:15 | Maya taps Storm Mode; Accounts tab: escrow $20 → $50, Nessie log line | "Capital One locks $50 of Maya's balance in escrow through Nessie, and our server signs her certificate. Her key never leaves her phone." |
| 0:30 | Show airplane mode on all 3 phones | "Now everything is offline. No cell, no Wi-Fi network." |
| 0:35 | Maya pays the Pharmacy $12 by QR → green | "No server. The pharmacy checks the bank's signature and Maya's, and sees it's backed: $12 of $50 used." |
| 0:55 | Maya walks the phone past the Gas Station (topology: Pharmacy ↔ Maya ↔ Gas Station). Hand the judge Maya's phone → Judge mode → Roll back (reuse) | "Now you're Maya, and you're cheating. Roll your wallet back and spend the same money next door." |
| 1:10 | Gas Station scans → **red**, names the rule. Offer "Be clever" → red again | "Refused, with no internet anywhere. Maya's phone carried the pharmacy's record here. Try the clever version: skip a counter. Also refused: the running total went backwards." |
| 1:35 | Gas Station joins Wi-Fi → Accounts: Nessie log scrolls; relay path "Pharmacy → Maya → Gas Station → server · 2 hops" | "The gas station finds a signal and uploads its records and the pharmacy's, two hops away. The pharmacy is paid in Nessie. The certificate is frozen." |
| 1:55 | Cases tab: two signatures; judge scans Proof QR and taps Verify on their own phone | "This isn't a fraud score. It's Maya's signature, twice, on the same money. Check it yourself." |
| 2:10 | Town tab: "Your 3 phones are part of a 40-shop simulated town." StormDesk flag: Corner Store | "Our agent watches the whole town. It found a shop that went silent while taking guarantee-pool money." |
| 2:25 | — | "Math flags. The agent investigates. A person decides." |

### 21.3 Sponsor add-ons (30 s each, when that judge is at the table)

| Judge | Show | Say |
|---|---|---|
| **Capital One** | Accounts tab: escrow, pool, merchant accounts, refund on close, call log, ledger balanced | "Every dollar is recorded in Nessie: escrow on Storm Mode, settlement to merchants, the guarantee pool above the escrow, and the refund on close. Here's every call." |
| **Factory** | Cases → StormDesk: live step stream on a hard case, the Flag schema, the permission handler denying writes, README "Where Droid runs" | "Droid runs on every case and every suspicion in production. It re-verifies the proof itself, pulls the logs, and writes a structured proposal. It has no write tools; a person approves." |
| **Chalk** | Evals tab: rules-only vs. StormDesk; a trap case it dismissed; `query_features` calls in the step stream | "The agent reads live features from Chalk: Nessie, phone logs, weather alerts. We evaluated it on labeled simulated towns with deliberate traps: here's what rules alone flag, and what the agent gets right." |
| **Photon** | Approve the Corner Store flag → Mac 1 Telegram buzzes → type a reply → agent answers with evidence | "The merchant can argue back by text. The agent checks their claim against their own signed log, live." |
| **Digital Trust** | "Merchant knew" case: Corner Store's own ACCEPT entry listing the conflicting tag | "We found an attack on our own system: a shop that plays dumb to get pool money. Its own signed log proves it knew." |

### 21.4 Table version (90 s) and short-slot rule

If judging slots are < 3 min, drop the Town beat from the core and show StormDesk only in sponsor add-ons.

### 21.5 Backups

1. Multipeer flaky → QR sync between phones (still offline).
2. Live agent slow → replay stored transcript (labeled).
3. Nessie down → queued payouts visible, ledger moving.
4. Everything broken → 2-minute recorded video on Mac 2.

### 21.6 Demo dry run (pre-flight) [v4.18]

`cd server && python -m stormcash.dryrun --base-url http://localhost:8000`, before every judging slot and after any merge. It plays the server side of §21.2 headlessly, about 15 s against the hosted database, and prints ✓ or ✗ with a one-line reason and the time for each step. Exit code 0 only when every step passed.

- **Identities.** "Dry-run Maya", "Dry-run Pharmacy" and "Dry-run Gas Station", each with a fresh key, registered through the API (real Nessie accounts). It never signs as the real Maya: her key is on her phone. It acts as the phones with the real protocol library (`stormcash/dryrun.py`): QR payloads through the transport codec, C1–C6 run locally as the merchant's phone does, judge mode's rollback as `mobile/src/store/wallet.ts` does it, sync sessions that carry items with their `path` and write CONTACT entries.
- **Steps.** (1) server up, the database has every table, column and CHECK value of `schema.sql`, the server key equals `SERVER_PUB` (`--server-pub`, else `SERVER_PUB_HEX` in `server/.env`, else `mobile/src/config.ts`; a stale app constant is a note), and the server says StormDesk skips dry-run data; (2) register: CERT and MCERTs under `SERVER_PUB`, Nessie checking $480, escrow $20, shops $0; (3) Storm Mode: escrow $20 → $50 in Nessie (computed from its transactions), cert version up; (4) $12 at the pharmacy passes C1–C6; (5) "Reuse the money" → C6 SAME_COUNTER, "Be clever" → C6 BROKEN_LINK (and TOTAL_BACKWARDS) at the gas station, which holds the pharmacy's tag via Maya; (6) the gas station's `/v1/sync` carries the pharmacy's PAY 2 hops: it settles from escrow as a Nessie withdrawal + deposit pair (read from Nessie directly), the case opens (found offline), the cert is frozen and a new POLICY lists it, the relay path names the three phones; (7) `/v1/proof/{case_id}` verifies in Python against the pinned key, and with `cpp/build/verify/stormcash-verify proof` when it's built; (8) the seeded town has a Droid flag on the Corner Store, with the reviewer's verdict; (9) cleanup.
- **No Factory credits.** The only automatic StormDesk trigger is the worker (triage chains the review); it skips dry-run identities. The dry run refuses a server without `GET /v1/demo/dry-run` (it can't say so) before writing anything, and fails step 9 if any StormDesk run touches dry-run data.
- **Cleanup.** `POST /v1/demo/reset`, which first removes every dry-run identity and everything that touches it, including the Nessie call-log lines (`demo.clear_dry_run`), so the table ends exactly as a reset leaves it: register Maya's phone again afterwards. The simulated town is never written. The dry-run Nessie customers stay in the sandbox, unreferenced. `--keep` skips the cleanup for debugging; the next reset removes what it left.
- **Not covered:** the phones, Multipeer, the dashboard's rendering and Photon. The phones are tested separately on the real hardware.

---

## 22. Build plan, cut order, checklists

### 22.1 First hour (Friday, right after the opening ceremony)

**Person A (Mac 1):**
- [ ] Developer Mode on all 3 iPhones (restart)
- [ ] Expo app shell with dev client builds and installs as Release on all 3 phones with free signing
- [ ] `expo-nearby-connections` discovers + sends 2 KB between two iPhones in the hall, 5/5 times
- [ ] **[v4.1]** Photon account + number (Photon workshop Fri 4–5 PM); Telegram on Mac 1 reaches a webhook through cloudflared

**Person B (Mac 2):**
- [ ] Repo created with this layout; this spec + CLAUDE.md committed
- [ ] Hosted Postgres (Neon/Supabase) up; `schema.sql` applied
- [ ] Nessie key works; two accounts; a withdrawal + deposit pair recorded **[v4.2]**
- [ ] `droid` CLI logged in; `run(..., output=Model)` returns structured output; built-in tool ids listed
- [ ] Chalk account (chalk.ai/hackharvard); evaluations quick start runs
- [ ] Server signing key generated; public key pasted into `mobile/src/config.ts`

**Claude (Mac 2):** WS0 protocol libs + `gen_vectors.py` + both vector test suites.

### 22.2 Schedule

| Block | Person A (mobile) | Person B (server/dash) | Claude sessions |
|---|---|---|---|
| **Fri 5–8 PM** | App shell, key, Face ID, QR show/scan, register flow | DB, `/register`, `/storm-mode` on Nessie, SSE skeleton | WS0 vectors (both languages) → WS2 settlement core |
| **Fri 8 PM–1 AM** | Offline checks C1–C6, wallet + items + device_log stores, judge mode v1 | `/sync` + settlement + ledger + Nessie payouts; Accounts tab | WS2 cases + policy + R5/R6; WS4 simulator v1; WS3 dashboard skeleton |
| **Sat 9 AM–1 PM** | Full offline pay flow on 3 phones; sync session over Multipeer | Cases tab + proof page; sponsor fair 10–12 (show Capital One, Factory, Chalk, Photon) | WS4 scenarios + seed-town; WS5 StormDesk worker + tools; WS6 Chalk features |
| **Sat 1 PM** | **Decision:** Multipeer reliable in the hall? If not, QR sync now | | |
| **Sat 1–6 PM** | Store-and-forward relay, demo topology, path metadata, upload | StormDesk panel + approvals; Town tab | WS6 eval dataset + first Chalk run; WS7 Photon notices + appeals |
| **Sat 6 PM** | **Checkpoint:** core demo end to end. Apply cut order if behind. | | |
| **Sat 6 PM–12 AM** | Judge mode both modes, Secure Enclave timebox (1 h), QR fallback | Evals tab, demo reset, replay mode, README | WS5 replays for planted cases; WS6 final eval run; WS7 appeal agent |
| **Sat 12 AM** | **Feature freeze** | | |
| **Sun 12–6 AM** | Release builds on all phones, permissions, rehearse, backup video **[v4.1]** | Devpost write-up, architecture image | README "Where Droid runs" / "How we use Chalk" drafts |
| **Sun 6–8 AM** | Rehearse twice clean | Submit by 7:30 AM | — |

### 22.3 Cut order (apply at Sat 6 PM checkpoint if behind)

1. Photon voice
2. Photon appeal agent (keep the one-way hold notice)
3. `region_dark` + weather resolvers
4. LLM-judge scorer
5. Secure Enclave keys
6. Two-hop demo topology (fall back to the gas station uploading its own + received items, 1 hop)
7. Multipeer (fall back to QR sync)

**Never cut:** offline pay, refusal C6, judge mode (both modes), Verify-it-yourself, Nessie settlement + Accounts tab, R5 merchant-knew, `merchant_silence` + StormDesk triage, one real Chalk eval run.

### 22.4 Fallback table

| Risk | Fallback | Switch |
|---|---|---|
| Multipeer unreliable | QR sync | Records → Sync by QR |
| Hosted Postgres unreachable | Local Postgres on Mac 2; Chalk reads features via Postgres views exposed through the API tunnel or StormDesk uses `postgres_fallback` | `DATABASE_URL` |
| Chalk down or slow **[v4.6]** | `query_features` answers from Postgres (`postgres_fallback`, the detectors' frozen features) | automatic; `CHALK_DISABLED=1` |
| Nessie down/slow | queued payouts + replay | automatic |
| Nessie unusable for the whole demo **[v4.3]** | ledger-only money, Accounts tab shows ledger | `NESSIE_DISABLED=1` |
| Phone can't sign API writes yet **[v4.3]** | accept unsigned writes | `API_SIG_REQUIRED=0` |
| Droid slow or failing | replay stored transcripts | dashboard toggle |
| Reviewer slow, failing or too costly **[v4.15]** | triage alone: the flag as StormDesk proposed it | `STORMDESK_REVIEW=0` |
| Appeal sessions misbehave **[v4.21]** | one fresh Droid run per message | `STORMDESK_APPEAL_SESSIONS=0` |
| Author job misbehaving or too costly **[v4.22]** | no author runs; the stored run and its PR stay on the Droid tab | `STORMDESK_AUTHOR=0` (the default) |
| Chalk eval task can't reach tunnel | run agent locally, upload outputs, score in Chalk | `chalk/evals/run_local.py` |
| Photon webhook issues | outbound notice only; show the thread from the DB | config |
| Venue Wi-Fi blocks server | phone hotspot for Mac 2 and the gas station | — |

### 22.5 Saturday-night checklist

- [ ] Release builds on all 3 phones; spare build plan documented
- [ ] All permissions granted
- [ ] Automatic time on before going offline
- [ ] All demo Nessie customers and accounts pre-created
- [ ] `seed-town 42` loaded; planted StormDesk runs replayable
- [ ] Final Chalk eval run rendered on the Evals tab
- [ ] Demo reset < 30 s, tested 3 times
- [ ] **[v4.18]** `python -m stormcash.dryrun` all ✓ before each judging slot (§21.6)
- [ ] 2-minute backup video recorded
- [ ] README: pitch, setup, honest limits, "Where Droid runs", "How we use Chalk", "How we use Nessie", "How we use Photon"
- [ ] Devpost skeleton + architecture image

---

## 23. Pitfalls

- Hardware keys return DER; noble wants raw. One helper, tested by a vector.
- Python and TypeScript render a field differently → digests differ. The vectors catch this; never skip them.
- noble versions differ on prehash/lowS defaults → pin the version, test with vectors.
- A permission prompt appears on stage. Grant everything during setup.
- Debug builds are slow. Release builds Saturday night.
- Multipeer needs the local-network permission and `NSBonjourServices`; without them, discovery silently fails.
- Airplane mode turns Wi-Fi off. Turn Wi-Fi and Bluetooth back on, join nothing.
- Clocks: automatic time on before going offline; 10-min tolerance.
- QR too dense (PAY ≈ 600–800 chars): base64url already; if still slow, use a larger QR on screen, max brightness, error correction L, and drop optional fields. Measure Friday night.
- Free signing: each phone may need its owner's Apple ID; never rebuild a demo phone after midnight without a known-good build.
- Nessie at 9 AM Sunday may be slow. Everything pre-created Saturday.
- Droid structured output failures are values, not exceptions: check `RunFailure.subtype`.
- Chalk functions run remotely: they can't see localhost. Use the tunnel URL.
- Simulated money must never hit Nessie.
- Agent citations: validate server-side every time.
- Battery: power bank, charge between rounds.

---

## 24. Judge Q&A (practice the first six word for word)

1. **"Isn't this just UPI Lite X or e-CNY?"** Those prove people want offline payments and that caps work. They trust the phone and check for fraud later. We add backing the merchant can verify offline, double spends refused between phones, and signed proof, on ordinary iPhones.
2. **"Can you actually stop double spending offline?"** Not perfectly; the Bank of England calls it the core trade-off. We stop it whenever a tag has reached the shop, cap it when one hasn't, and prove it at settlement every time.
3. **"What if the cheater skips a counter?"** Their running total goes backwards, which is its own signed proof. We check three ways a chain can be inconsistent.
4. **"Who eats the loss?"** Merchants are paid for payments they accepted. Escrow covers the first $50; above that the guarantee pool pays, funded by the bank as a program cost like card fraud. The cheater owes the pool, and the bank has their signatures. A merchant who knowingly accepted a double spend isn't paid by the pool, and their own log proves it.
5. **"Shops are blocks apart. How does the second one hear about the first?"** Through customers' phones, which carry records shop to shop. Today Maya's phone does it: the pharmacy and gas station never connect directly.
6. **"Why not a blockchain?"** Bitcoin stops double spends because the whole network agrees on one ledger. In a hurricane nobody can reach anybody. We kept the parts that work when the network is cut (per-account counters, gossip, refusing a spend you've seen, slashing-style proof) and dropped the part that needs everyone online.
7. **"Isn't the AI deciding who's a fraudster?"** No. Math decides hard fraud. The agent investigates suspicions and proposes; a person approves. It can't move money, and every claim it makes must cite a real record or it's discarded.
8. **"How good is the agent?"** Show the Evals tab: rules-only vs. agent on labeled simulated towns with deliberate traps. Quote only the numbers on screen.
9. **"Maria lasted weeks. Doesn't 72 hours break this?"** Certificates renew through any phone that finds a signal, the same path that settles payments.
10. **"Disasters with no warning?"** Everyone has a $20 always-on cap, renewed whenever they're online.
11. **"Is it private?"** Phones share a pseudonymous id, amounts and running totals, never names or which shop was paid. Ids rotate per storm. Production encrypts relayed bundles to the server key.
12. **"Isn't the rollback tool fake?"** It does what a modified app or a restored backup could do. Every offline system has to handle it.
13. **"Stolen phone?"** Face ID per payment, the owner can text FREEZE from their registered Telegram account on any device, and the cert expires in 72 h without renewal.
14. **"iPhones only sync with the app open?"** Yes, an honest limit today. The simulator shows how settlement time depends on how many people relay.
15. **"Is this money transmission?"** Funds stay at the bank: escrow is the customer's own Capital One account, and merchants are paid by bank transfer. A real launch runs through the bank's licenses.

---

## 25. Glossary

| Term | Meaning |
|---|---|
| Certificate (CERT) | Server-signed statement: this key may spend up to cap, backed by this escrow |
| Version | A re-issue of the same cert_id (Storm Mode, renewal, close) |
| Spend tag (TAG) | The resident's one signature per payment; the gossip record |
| Chain | A wallet's tags linked by prev_hash, counter and running total |
| Equivocation | Two tags under one cert that can't sit on one honest chain |
| PROOF | A pair of equivocating tags; self-proving |
| Device log (DLOG) | Each phone's signed, hash-chained record of accepts, refusals and contacts |
| Contact | One sync session between two phones, logged by both |
| Item | Anything that syncs phone to phone (§10.2) |
| Relay / upload | A phone with internet posting carried items to the server |
| Policy | Server-signed list of frozen certs and merchant limits |
| Hard rule | Deterministic, provable fraud rule (R1–R6) |
| Candidate | A detector's suspicion (soft) |
| Flag | StormDesk's verdict on a candidate |
| Guarantee pool | Operator account that pays accepted payments beyond a cheater's escrow |
| Simulated | Data from the town simulator; always labeled |
