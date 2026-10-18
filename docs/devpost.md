# StormCash on Devpost

Paste each section into the matching Devpost field. One thing is still marked **FILL BEFORE SUBMIT**: the demo video link. Brian and Alex: read "How we worked as a team" and "What we learned" and adjust anything that doesn't sound like you before pasting. Don't type any number that isn't already here: every figure below comes from a real run or from the code (eval numbers from Chalk runs, listed with their ids in the README).

Submission deadline: **Sunday Oct 18, 8:00 AM** (aim for 7:30). Track: **Digital Trust**. Sponsor challenges: **Best Use of Nessie (Capital One)**, **Factory Droid SDK**, **Chalk**.

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
- **Pay by QR with no network.** The shop's iPad checkout checks the bank's signature and the resident's signature offline, runs all six checks (C1–C6), and stamps the payment VERIFIED: "Backed by Capital One. $12 of $50 used."
- **Cheating is refused offline.** Every payment is a signed, chained spend tag. Devices pass tags to each other over Bluetooth and peer Wi-Fi, and customers carry them from shop to shop. If someone rolls back their wallet and spends the same money again, the next shop that has seen the tag refuses it, with no internet anywhere, and the two conflicting signatures are proof anyone can check.
- **Records hop device to device.** Payments, tags and signed device logs travel device to device until any one finds a signal and uploads them. The server pays shops through Nessie, freezes the cheater, and sends receipts and the freeze list back the same way.
- **"Merchant knew."** Every device keeps a signed, hash-chained log of what it accepted and whom it met. A shop that took a double spend while holding the conflicting tag is caught by its own signature.
- **StormDesk.** A back-office agent built on Factory's Droid SDK investigates fraud cases and triages suspicious patterns, reading live features from Chalk. A second Droid session reviews every proposal and tries to refute it. The agent proposes; a person approves.

## How we built it

- **Protocol:** ECDSA P-256 signatures over a canonical encoding, with a Python library on the server and a TypeScript twin on the phones. Both must reproduce a shared set of test vectors byte for byte, so the two sides can never disagree about what was signed.
- **Mobile:** one React Native (Expo) app for every role. On a phone it's the customer's wallet; on an iPad it's the shop's counter checkout: ring up the sale, show the code, scan the customer's, stamp the result. Face ID per payment, QR show and scan, local SQLite stores, Apple Multipeer Connectivity for device-to-device sync with a QR sync fallback, and a small Swift module for optional Secure Enclave keys. The checkout shows each of the six offline checks (C1–C6) with its evidence.
- **Server:** Python, FastAPI and plain SQL on hosted Postgres (Neon): settlement, a double-entry ledger, six deterministic fraud rules (R1–R6), signed freeze lists, and live updates to the dashboard over server-sent events.
- **Capital One Nessie:** checking, escrow, guarantee-pool and shop accounts. Every money movement is a matched withdrawal and deposit linked to our ledger, the dashboard reads balances live from Nessie, and a live reconciliation checks, account by account, that our ledger agrees with Nessie's own records.
- **Factory Droid SDK:** StormDesk runs Droid sessions inside the product with structured outputs (Pydantic), eleven read-only tools served as an in-process MCP server, a permission handler that blocks everything else, and a citation check that rejects any claim citing an id that doesn't exist. A second Droid session reviews every proposal. In one sandboxed job Droid also writes code: it proposes a new deterministic fraud detector as a pull request, our own code re-runs its tests and evaluation, and a person decides whether to merge it.
- **Chalk:** feature classes and SQL resolvers over our Postgres data plus live National Weather Service alerts, queried by StormDesk at runtime, and Chalk Evaluations scoring StormDesk against a rules-only baseline.
- **Simulator:** a deterministic 38-shop town built on the same protocol and settlement code as the real devices, with labeled scenarios and deliberate traps, used for the dashboard's Network view and as the eval dataset. Everything from it is labeled "simulated".
- **C++ verifier:** `stormcash-verify`, a third independent implementation of the protocol's checks, which reproduces all 124 shared test vectors and passes Project Wycheproof's 262 P-256 signature tests. Compiled to WebAssembly, it runs on the public proof page as a second check next to WebCrypto, so a judge's phone shows "Verified by 2 independent implementations".
- **Dashboard:** React, Vite and TypeScript, built as an operations command center with five workspaces: Overview, Network, Cases, Ledger and StormDesk. The cryptographic proof sits in its own panel, apart from StormDesk's reading, which is labeled "advisory only", and every open proposal says exactly what Approve will run. A public "Verify it yourself" proof page checks the signatures in the judge's own browser.

### How we worked as a team

- **A clean split.** Brian owned everything on the devices: the Expo app, the iPhone wallet and iPad checkout, Face ID and QR, the offline checks, Multipeer sync and relay, Secure Enclave keys, and at the end the dashboard's command-center redesign. Alex owned everything behind them: the server, settlement and Nessie, the fraud rules, the simulator, the dashboard, StormDesk on Droid, the Chalk evaluations and the C++ verifier.
- **A contract between our halves.** Before either side built on the protocol, we wrote a spec and generated shared test vectors. Brian's TypeScript and Alex's Python had to reproduce them byte for byte, so the phones and the server agreed on every signature without either of us reading the other's code.
- **One workflow for everything.** We tracked the work as 50+ GitHub issues, one per piece, grouped by workstream and by schedule block. Every change went in through a pull request (71 merged), and CI had to pass on all four parts (server, mobile, dashboard and C++) before anything merged. The spec stayed the source of truth: when code changed the design, the spec changed in the same pull request.
- **Checking each other's assumptions.** Hour-one checks against the real APIs (Nessie, Droid, Chalk) changed our design early. Nessie's balances don't move, so we redesigned settlement around withdrawal and deposit pairs before writing it.

## Challenges we ran into

- **Nessie didn't work the way we expected.** In hour one we found that account balances in the current Nessie API are fixed when an account is created, transfers have no payee, and amounts are whole dollars. We redesigned settlement so every money movement is a matched withdrawal and deposit, and the dashboard computes live balances from Nessie's own transaction records.
- **Two languages, one signature.** Python and TypeScript had to agree on every byte: string normalization, signature encoding, deterministic signing. Shared test vectors caught the differences before they reached the phones.
- **Devices that found each other but never connected.** The Multipeer library gave advertising and browsing separate sessions, so devices saw each other and then silently dropped. We traced it with on-device logs, patched it, and stopped inviting the same peer twice. Links now hold while the apps stay open; reconnecting after an app restart is still unreliable, so QR sync stays as the fallback.
- **Latency to a hosted database.** Loading the simulated town into Neon first took 46 minutes, because every statement waited on a network round trip. Pipelining the writes brought it to about 40 seconds.
- **Our first agent was too lenient.** Its first real evaluation caught 2 of 23 real fraud cases: it dismissed stolen phones because "the escrow covered it". We rewrote the prompt with general analyst principles, labeled the new score as not blind, and tested it on towns it had never seen.
- **An agent that writes code needs a real sandbox.** We found that Droid's CLI runs shell commands it rates read-only (like `ls`) without asking our permission handler. So we turned its shell off, gave it the two commands it needs as tools, ran it under a macOS sandbox profile, and re-run every number it reports before a pull request opens.
- **One check wasn't enough for the proof page.** The first C++ elliptic-curve library we tried for WebAssembly rejected 2 valid Wycheproof signatures, so we switched to p256-m, and CI now runs every Wycheproof test on both crypto backends.
- **Offline double spending can't be fully prevented.** We had to be honest about the limit: a shop that no record has reached can be fooled once, up to the cap. We designed for bounded loss, offline refusal whenever a record has arrived, and proof at settlement every time.

## Accomplishments that we're proud of

- A judge can personally try to double spend with every device in airplane mode, and the shop refuses it.
- We ran the whole story on real hardware: an iPhone customer and two iPad shops in airplane mode. The pharmacy accepted $12 offline, the customer's phone carried that record to the gas station, the gas station refused the rolled-back copy, and when the iPads found signal the pharmacy was paid $12 through Nessie and a case opened with both signatures, relayed Gas Station → Maya → Pharmacy → server.
- The proof of cheating is two signatures anyone can verify in their own browser, not a fraud score, and the proof page checks it with two implementations that share no code.
- No AI in the money path. Hard fraud rules are deterministic code; the agent can't move money or freeze anything, and every claim it makes must cite a real record.
- The simulated town is checked by exactly the same code as the real devices.
- On towns it had never seen, the agent wrongly flagged none of 11 honest subjects (rules alone flagged all 11) while catching every stolen phone.
- Three independent implementations of the protocol, in Python, TypeScript and C++, agree byte for byte on 124 shared test vectors.
- Droid proposed a new fraud detector as a pull request, our own re-run matched every number it claimed, and it stays open until a person decides to merge it.

## What we learned

- How far offline verification can go, and exactly where it has to stop.
- Why gossip protocols and epidemic routing suit disaster networks better than consensus.
- How to evaluate an agent honestly: deliberate traps, a rules-only baseline, and numbers that only ever come from a real run.
- How to split a system between two people so neither blocks the other: agree on a written contract and machine-checked test vectors first, then build in parallel.
- Mobile: native iOS peer-to-peer (Multipeer Connectivity), Secure Enclave keys and React Native native modules, all without a paid Apple developer account.
- Backend: designing settlement around a bank API's real behavior, double-entry ledgers and reconciliation, and pipelining a hosted database (46 minutes down to 40 seconds).

## What's next for StormCash

- Secure Enclave keys by default, so the wallet counter can't be rolled back by restoring a backup.
- Encrypting relayed bundles to the server's key, so relaying devices can't read what they carry.
- Background sync on iOS, so devices exchange records without the app open.
- Testing Droid's proposed detector on real data: its perfect score is on simulated towns that plant the very pattern it relies on.
- Working with a bank on real escrow and licensing.

## Built with

python, fastapi, postgresql, neon, react, typescript, vite, tailwindcss, react-native, expo, swift, c++, cmake, openssl, multipeer-connectivity, ecdsa, capital-one-nessie, factory-droid, chalk, cloudflare

---

## Sponsor challenge notes

Paste these where Devpost asks how you used each sponsor.

**Best Use of Nessie (Capital One).** Nessie moves every dollar in the demo: the resident's escrow lock and Storm Mode top-up, settlement to shops from escrow, the guarantee pool paying above a cheater's escrow, and the refund on close. Each movement is a withdrawal and deposit pair linked to our double-entry ledger, the dashboard's Accounts tab reads balances live from Nessie, and every call is visible in the Nessie call log. A live reconciliation checks, account by account, that our ledger agrees with Nessie's own records, and explains any difference from real data (for example a payout still queued while Nessie was down).

**Factory Droid SDK.** Droid runs inside the product as StormDesk: on every fraud case it re-verifies the proof with our deterministic verifier and writes a case file, and on every detector suspicion it decides whether it's real and proposes an action, with structured outputs, read-only MCP tools, and a permission handler that blocks writes. Every step streams live to the dashboard, and a person approves every action. A second, independent Droid session reviews each proposal and tries to refute it. In a Chalk evaluation on held-out towns, that raised the real fraud cases reaching a person from 6 of 9 to 8 of 9, with no honest subject added. A Droid tab on the dashboard shows every run's model, credits, tool calls and the guardrails that fired. See "Where Droid runs" in the README.

**Chalk.** StormDesk reads live Chalk features at runtime (shop contact rates against neighbors, pool-funded share, certificate drain speed, upload gaps, weather alerts). We evaluated it with Chalk Evaluations on labeled simulated towns with deliberate traps, against a rules-only baseline.

On two held-out simulated towns, chosen before the run and never seen while we wrote the agent's prompt, StormDesk caught 6 of 9 real fraud cases, including every stolen phone, and wrongly flagged 0 of 11 honest subjects, with every cited record valid (Chalk run `51b74f56-d8d8-466b-a07c-3ddf8baa8064`). The rules-only baseline on the same rows caught all 9 but also flagged all 11 honest subjects (`dc1fd4c9-734e-408d-8c48-9c583dcb3867`). Our first prompt was far too lenient (2 of 23 real cases on our main set), so we rewrote it, said so openly, and then tested it blind. It still misses some colluding shops and every dark region on the held-out towns, which is why a person approves every action.

**Digital Trust track.** The judge tries to cheat with no internet and is refused. The evidence is self-proving signatures, and our "merchant knew" rule catches a colluding shop with its own signed log.

---

## Links and media

- Repo: https://github.com/Alexlgvcode/stormcash
- Image gallery: upload [`docs/gallery/`](gallery/) in order (3:2, 2400×1600). Suggested captions:
  1. `01-stormcash.png`: StormCash: the customer's wallet on a phone, the shop's checkout on an iPad.
  2. `02-accepted-offline.png`: A $12 payment accepted with no internet: six checks on the shop's iPad, with the evidence behind them.
  3. `03-refused-offline.png`: The same money spent twice is refused offline. Two signatures on one payment number are proof, not a score.
  4. `04-settled-with-proof.png`: Case #101 from our rehearsal on real devices: settled through Capital One Nessie, with both signed payments side by side.
  5. `05-command-center.png`: The operations command center: every dollar by state, reconciled live with Nessie.
  6. `06-network.png`: Records hop device to device across a simulated 38-shop town around the real devices.
  7. `07-stormdesk.png`: StormDesk: rules flag, a Droid agent investigates, a second agent reviews, a person decides.
  8. `08-architecture.png`: How it fits together.
- Architecture image: [`docs/architecture.png`](architecture.png) (also slide 8)
- Demo video: **FILL BEFORE SUBMIT** (Brian's 2-minute backup video, #42)
- Team: Alexandre Lugovoi, Brian Maina
