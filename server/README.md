# server/

FastAPI server: settlement, ledger, Nessie, policy, detectors, SSE, plus StormDesk (`stormcash/stormdesk/`, WS5) and Photon (`stormcash/photon/`, WS7).

- **Workstreams:** WS2 server core (reviewer B), WS5 StormDesk (B), WS7 Photon (A)
- **Spec:** §6.3 env, §11 schema/settlement/ledger/Nessie, §12 API, §13 detectors, §14 StormDesk, §17 Photon
- **Rule:** WS2 owns `stormcash/db.py`, `schema.sql` and `app.py`; other workstreams add routers in their own module.

```bash
cd server && python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

```bash
cp .env.example .env
```

```bash
psql "$DATABASE_URL" -f schema.sql
```
