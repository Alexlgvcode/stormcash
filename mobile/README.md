# mobile/

Expo / React Native app for iPhone (WS1, owner A). Same app for residents and merchants.

- **Spec:** §6.1–§6.2 stack and free-signing setup, §7–§10 protocol, §19 screens, stores, transport, judge mode
- **Done when (§19):** with all 3 phones in airplane mode, Maya pays the pharmacy, rolls back, and the gas station refuses, with the pharmacy's tag reaching it through Maya's phone.

## Setup

Expo SDK 58, development build (`expo-dev-client`), New Architecture. Expo Go cannot run this app.

```bash
npm install
npx expo prebuild --platform ios     # generates ios/ (gitignored)
npm run ios:release                  # Release build to a USB-connected iPhone
npm start                            # Metro for Debug dev-client builds
npm test                             # protocol vector tests (vitest)
```

Free signing (§6.2): in Xcode open `ios/StormCash.xcworkspace` → target → Signing & Capabilities → Team = your Personal Team. Each phone signed with a different Apple ID needs its own bundle id: change `ios.bundleIdentifier` in `app.json` (default `edu.bu.stormcash.bm`) and prebuild again. Multipeer matches by service type, not bundle id.

The Info.plist keys from §6.2 (local network, Bonjour `_stormcash._tcp/_udp`, Bluetooth, camera, Face ID) are set in `app.json`.

## Layout

| Path | What |
|---|---|
| `src/protocol/` | TypeScript protocol twin (WS0): `encoding.ts`, `crypto.ts`, `objects.ts`, `rules.ts` |
| `src/store/` | SQLite stores (§19.4): wallet, items, device_log, peers, merchant_state, policy |
| `src/payments.ts` | Payer checks + signing (§8.1), merchant checks C1–C6 + ACCEPT/REFUSE/PROOF (§8.2) |
| `src/sync/` | Sync session (§10.3), item verification, upload (§10.5), QR frames (§10.7), manager |
| `src/transport/` | Transport interface + Multipeer via `expo-nearby-connections` |
| `src/demo/topology.ts` | Demo topology allowlist (§10.6) |
| `src/screens/` | Setup, Wallet, Pay, Charge, Result, Records, QR sync, Demo menu, Judge mode |
| `modules/sc-keys/` | Secure Enclave P-256 key (§19.6), off by default; demo menu → "Hardware key on next setup" |
| `plugins/` | Config plugin that keeps both `_stormcash._tcp` and `_stormcash._udp` Bonjour entries |

Hidden demo menu: long-press the StormCash logo.

## Protocol choices the Python twin must match

These are decisions the spec leaves open. Keep `server/stormcash/protocol/` in line, or change both.

- **JSON short keys not given in the spec:** DLOG bodies use `th` tag_hash, `ci` cert_id, `hi` held_ids, `ck` check, `cid` contact_id, `pp` peer_pub, `si` sent_ids, `ri` recv_ids, `so` sent_overflow, `ro` recv_overflow. RENEW uses `ci`, `ch` chain_head, `k`, `ts`. RCPT uses `ts`, `ids`. POLICY uses `pv`, `ia`, `fc`, `ml`.
- **API request signature:** `X-SC-Sig` is over `canonical(API, path, sha256_hex(body), ts)`, with the path rendered as a string field (§7.2 rules: ≤ 48 chars, no `|`).
- **REQ expiry:** both the payer and C4 accept `req_expires_at > now − 600` (the same 10-minute clock tolerance).
- **C6:** stored tags that are byte-identical to the presented tag are ignored, because the payer's own phone may gossip it first; replays are caught by C4 (the request closes on accept). Stored tags only count if they verify against the presented cert's `holder_pub`. A counter-1 tag whose `prev_hash` isn't `GENESIS` fails C6 as `BROKEN_LINK`; counter 1 with `cum ≠ amount` fails C5.
- **CONTACT ids:** `sent_ids` / `recv_ids` include PAY items as well as TAG and PROOF, since a PAY has the same id as its tag (needed for R5 b).
- **Sync HELLO** has an optional `pay` list (id8 of items held as a full PAY), so a phone holding only the bare TAG still fetches the PAY the server needs.
- **Path:** the phone that creates an item adds itself as the first hop; each receiver appends `[short_id, ts]`.
