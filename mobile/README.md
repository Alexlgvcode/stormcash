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
