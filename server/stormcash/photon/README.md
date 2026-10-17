# photon/ (WS7)

Photon messaging agent (spec §17): hold and settled notices to merchants, and appeals answered by StormDesk.

| File | What |
|---|---|
| `routes.py` | `POST /v1/photon/inbound` (Spectrum webhook, HMAC-verified), `GET /v1/photon/messages?merchant_id=`, `POST /v1/photon/notify/{flag_id}` (operator) |
| `client.py` | `send(channel, handle, text)` via the bridge; `send_to_merchant` records a `messages` row and a `message` SSE event, delivered or not |
| `notices.py` | `hold_notice(deps, settings, flag_id)`: the agent's draft only if every number in it is in the flag's evidence, else a template. `settled_notice(deps, settings, payout_id)` |
| `appeal.py` | Inbound reply → StormDesk `respond` job → reply sent only if it cites ids that exist; otherwise a neutral acknowledgement. SSE `appeal` |
| `bridge/` | Node process that owns the `spectrum-ts` SDK (sending is TypeScript-only) |

## Wiring (WS2)

```python
from .photon import routes as photon
app.include_router(photon.router)
```

Call `notices.hold_notice(deps, photon_settings, flag_id)` from the approval route for `hold_pool_payout` / `lower_merchant_limit`, and `notices.settled_notice(...)` when a real merchant's payout is executed. Until then, `POST /v1/photon/notify/{flag_id}` with `X-SC-Operator` sends the hold notice.

## Run

1. In Photon (app.photon.codes): a project with the Telegram provider; note `PROJECT_ID` / `PROJECT_SECRET`. Create a bot with @BotFather for `TELEGRAM_BOT_TOKEN`. Register a webhook to `${PUBLIC_BASE_URL}/v1/photon/inbound` and put its signing secret in `SPECTRUM_WEBHOOK_SECRET` (server/.env).
2. Pick any random `PHOTON_BRIDGE_TOKEN` and set it for both the server and the bridge.
3. Start the bridge:

```bash
cd server/stormcash/photon/bridge && npm install && PROJECT_ID=... PROJECT_SECRET=... TELEGRAM_BOT_TOKEN=... PHOTON_BRIDGE_TOKEN=... npm start
```

4. Register the Corner Store with `contact: {channel: "telegram", handle: "<owner's Telegram user id>"}`. The owner must have messaged the bot once (Telegram bots can't start a chat).

Fallbacks (§22.4): `PHOTON_DISABLED=1` records every message on the dashboard thread and sends nothing. A failed send is recorded with `delivered: false`.
