# photon/ (WS7)

Photon messaging agent (spec §17): hold and settled notices to merchants, appeals answered by StormDesk, and residents who text FREEZE.

| File | What |
|---|---|
| `routes.py` | `POST /v1/photon/inbound` (Spectrum webhook, HMAC-verified), `GET /v1/photon/messages?merchant_id=` or `?resident_id=`, `POST /v1/photon/notify/{flag_id}` (operator), `POST /v1/photon/resident-contact` (operator), `GET /v1/photon/freezes` |
| `client.py` | `send(channel, handle, text)` via the bridge; `send_to_merchant` records a `messages` row and a `message` SSE event, delivered or not; `reply` answers the handle that wrote in |
| `freeze.py` | Resident FREEZE (§17.2): a text that is exactly `FREEZE` (trimmed, any case) from a resident's handle freezes their cert with `cases.freeze_cert` (new POLICY), sets `cert_status.owner_freeze_at` (cap_drain's `owner_freeze_request`) and confirms by text. No agent. Idempotent; texting can't unfreeze; an unknown handle gets a neutral reply |
| `notices.py` | `hold_notice(deps, settings, flag_id)`: the agent's draft only if every number in it is in the flag's evidence, else a template. `settled_notice(deps, settings, payout_id)` |
| `appeal.py` | Inbound reply → StormDesk `respond` job → reply sent only if it cites ids that exist; otherwise a neutral acknowledgement. SSE `appeal`. With `STORMDESK_APPEAL_SESSIONS=1` (default) each appeal thread (shop + flag) is one Droid session, resumed for every text, one turn at a time (spec §14.7c); `0` = one run per message |
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
5. Give Maya a handle for FREEZE: the phone can send `contact` on `POST /v1/residents/register`, or the operator sets it (one handle can be both the Corner Store and Maya: `FREEZE` is Maya's, anything else is the shop's appeal):

```bash
curl -X POST "$BASE/v1/photon/resident-contact" -H 'X-SC-Operator: alex' -H 'content-type: application/json' \
  -d '{"display_name": "Maya", "channel": "telegram", "handle": "<Telegram user id>"}'
```

Fallbacks (§22.4): `PHOTON_DISABLED=1` records every message on the dashboard thread and sends nothing; a FREEZE still freezes. A failed send is recorded with `delivered: false`. `STORMDESK_APPEAL_SESSIONS=0` answers each appeal text with its own fresh run.
