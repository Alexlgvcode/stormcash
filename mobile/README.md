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

## Protocol

`src/protocol/` mirrors `server/stormcash/protocol/` and must reproduce `spec/vectors.json` byte for byte (`npm test` runs every vector). The protocol is frozen (spec §7–§10, v4.3); change both libraries, the spec and the vectors together.

App-level choices outside the frozen protocol:

- The payer does not gossip its own TAG: the shop must receive the PAY first, or C6 refuses it as `COUNTER_NOT_NEW`. The shop's PAY travels on by store-and-forward.
- Bare gossiped TAGs arrive without their cert, so before C6 the merchant keeps only stored tags that verify under the presented cert's `holder_pub` (§8.2 assumes verified stored tags).
- With no open request, a scanned PAY is refused as C4 `WRONG_NONCE`.
- Sync HELLO carries `pays` (§10.3) and an optional `lb` demo label.
- Charge takes whole dollars only (Nessie moves whole dollars, §11.4).
