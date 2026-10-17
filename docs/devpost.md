# StormCash on Devpost

Paste each section into the matching Devpost field. Two things are marked **FILL BEFORE SUBMIT**: the eval numbers (copy them from the dashboard's Evals tab once the real StormDesk run is saved, with its Chalk run id) and the demo video link. Don't type any other number that isn't already here: every figure below comes from a real run or from the code.

Submission deadline: **Sunday Oct 18, 8:00 AM** (aim for 7:30). Track: **Digital Trust**. Sponsor challenges: **Best Use of Nessie (Capital One)**, **Factory Droid SDK**, **Chalk**, **Photon**.

---

## Project name

StormCash

## Tagline (one line)

When a disaster takes out towers and card readers, StormCash keeps phones paying local shops, and stops cheaters with no internet.

## Inspiration

After Hurricane Helene in 2024, card readers in western North Carolina couldn't connect, most ATMs were down or empty, and some shops stayed cash-only for a month. After Hurricane Maria, it was nearly impossible to find a place in San Juan that took cards. People had money in the bank and phones with battery, and still couldn't pay, because every payment app needs a server to approve each payment.

We wanted to know how much of a payment can be checked with no network at all, and how to catch the cheating that offline payments invite.

## What it does

- **Bank-backed spending limit.** A resident's bank (Capital One, through the Nessie API) locks money in an escrow account, and our server signs a certificate for the phone's key: "this phone may spend up to $X". Everyone has $20 always on; Storm Mode raises it to $50.
- **Pay by QR with no network.** The shop's phone checks the bank's signature and the resident's signature offline, and shows "Verified. Backed by Capital One, $12 of $50 used."
- **Cheating is refused offline.** Every payment is a signed, chained spend tag. Phones pass tags to each other over Bluetooth and peer Wi-Fi, and customers carry them from shop to shop. If someone rolls back their wallet and spends the same money again, the next shop that has seen the tag refuses it, with no internet anywhere, and the two conflicting signatures are proof anyone can check.
- **Records hop phone to phone.** Payments, tags and signed device logs travel phone to phone until any phone finds a signal and uploads them. The server pays shops through Nessie, freezes the cheater, and sends receipts and the freeze list back the same way.
- **"Merchant knew."** Every phone keeps a signed, hash-chained log of what it accepted and whom it met. A shop that took a double spend while holding the conflicting tag is caught by its own signature.
- **StormDesk.** A back-office agent built on Factory's Droid SDK investigates fraud cases and triages suspicious patterns, reading live features from Chalk. It proposes; a person approves. Shops get notices and can appeal by text through Photon.

**Math flags. The agent investigates. A person decides.**

## How we built it

- **Protocol:** ECDSA P-256 signatures over a canonical encoding, with a Python library on the server and a TypeScript twin on the phones. Both must reproduce a shared set of test vectors byte for byte, so the two sides can never disagree about what was signed.
- **Mobile:** React Native with Expo development builds on three iPhones, Face ID per payment, QR show and scan, local SQLite stores, and Apple Multipeer Connectivity for phone-to-phone sync, with a QR sync fallback.
- **Server:** Python, FastAPI and plain SQL on hosted Postgres (Neon): settlement, a double-entry ledger, six deterministic fraud rules (R1–R6), signed freeze lists, and live updates to the dashboard over server-sent events.
- **Capital One Nessie:** checking, escrow, guarantee-pool and shop accounts. Every money movement is a matched withdrawal and deposit linked to our ledger, and the dashboard reads balances live from Nessie.
- **Factory Droid SDK:** StormDesk runs Droid sessions with structured outputs (Pydantic), eleven read-only tools served as an in-process MCP server, a permission handler that blocks everything else, and a citation check that rejects any claim citing an id that doesn't exist.
- **Chalk:** feature classes and SQL resolvers over our Postgres data plus live National Weather Service alerts, queried by StormDesk at runtime, and Chalk Evaluations scoring StormDesk against a rules-only baseline.
- **Photon:** hold notices and appeal conversations with shop owners over Telegram.
- **Simulator:** a deterministic 40-shop town built on the same protocol and settlement code as the real phones, with labeled scenarios and deliberate traps, used for the dashboard's Town tab and as the eval dataset.
- **Dashboard:** React, Vite and TypeScript, with Accounts, Cases, Town and Evals tabs and a public "Verify it yourself" proof page that checks the signatures in the judge's own browser.

## Challenges we ran into

- **Nessie didn't work the way we expected.** In hour one we found that account balances in the current Nessie API are fixed when an account is created, transfers have no payee, and amounts are whole dollars. We redesigned settlement so every money movement is a matched withdrawal and deposit, and the dashboard computes live balances from Nessie's own transaction records.
- **Two languages, one signature.** Python and TypeScript had to agree on every byte: string normalization, signature encoding, deterministic signing. Shared test vectors caught the differences before they reached the phones.
- **Latency to a hosted database.** Loading the simulated town into Neon first took 46 minutes, because every statement waited on a network round trip. Pipelining the writes brought it to about 40 seconds.
- **Offline double spending can't be fully prevented.** We had to be honest about the limit: a shop that no record has reached can be fooled once, up to the cap. We designed for bounded loss, offline refusal whenever a record has arrived, and proof at settlement every time.

## Accomplishments that we're proud of

- A judge can personally try to double spend with every phone in airplane mode, and the shop refuses it.
- The proof of cheating is two signatures anyone can verify in their own browser, not a fraud score.
- No AI in the money path. Hard fraud rules are deterministic code; the agent can't move money or freeze anything, and every claim it makes must cite a real record.
- The simulated town is checked by exactly the same code as the real phones.

## What we learned

- How far offline verification can go, and exactly where it has to stop.
- Why gossip protocols and epidemic routing suit disaster networks better than consensus.
- How to evaluate an agent honestly: deliberate traps, a rules-only baseline, and numbers that only ever come from a real run.

## What's next for StormCash

- Secure Enclave keys by default, so the wallet counter can't be rolled back by restoring a backup.
- Encrypting relayed bundles to the server's key, so relaying phones can't read what they carry.
- Background sync on iOS, so phones exchange records without the app open.
- Working with a bank on real escrow and licensing.

## Built with

python, fastapi, postgresql, neon, react, typescript, vite, tailwindcss, react-native, expo, swift, multipeer-connectivity, ecdsa, capital-one-nessie, factory-droid, chalk, photon, telegram, cloudflare

---

## Sponsor challenge notes

Paste these where Devpost asks how you used each sponsor.

**Best Use of Nessie (Capital One).** Nessie moves every dollar in the demo: the resident's escrow lock and Storm Mode top-up, settlement to shops from escrow, the guarantee pool paying above a cheater's escrow, and the refund on close. Each movement is a withdrawal and deposit pair linked to our double-entry ledger, the dashboard's Accounts tab reads balances live from Nessie, and every call is visible in the Nessie call log.

**Factory Droid SDK.** Droid runs inside the product as StormDesk: on every fraud case it re-verifies the proof with our deterministic verifier and writes a case file, and on every detector suspicion it decides whether it's real and proposes an action, with structured outputs, read-only MCP tools, and a permission handler that blocks writes. Every step streams live to the dashboard, and a person approves every action. See "Where Droid runs" in the README.

**Chalk.** StormDesk reads live Chalk features at runtime (shop contact rates against neighbors, pool-funded share, certificate drain speed, upload gaps, weather alerts). We evaluated it with Chalk Evaluations on labeled simulated towns with deliberate traps, against a rules-only baseline.

> **FILL BEFORE SUBMIT:** add the headline numbers exactly as shown on the Evals tab (StormDesk vs. rules-only: colluders caught, honest shops wrongly flagged, citations valid), with the Chalk run id. If there's no real StormDesk run by then, leave numbers out and say the rules-only baseline is evaluated and the agent run is in progress.

**Photon.** When an operator approves a hold, the shop owner gets a notice on Telegram whose numbers all come from the flag's evidence. Their reply is answered by StormDesk, citing their own signed logs, and anything uncertain goes to a person.

**Digital Trust track.** The judge tries to cheat with no internet and is refused. The evidence is self-proving signatures, and our "merchant knew" rule catches a colluding shop with its own signed log.

---

## Links and media

- Repo: https://github.com/Alexlgvcode/stormcash
- Architecture image: [`docs/architecture.png`](architecture.png) (upload to the image gallery)
- Demo video: **FILL BEFORE SUBMIT** (Brian's 2-minute backup video, #42)
- Team: Alexandre Lugovoi, Brian Maina
