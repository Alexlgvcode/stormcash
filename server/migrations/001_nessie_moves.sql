-- [v4.3] Adds nessie_moves to a database created from an older schema.sql (e.g. the hosted demo DB).
-- Safe to run twice. A fresh database gets it from schema.sql.
CREATE TABLE IF NOT EXISTS nessie_moves (             -- [v4.3] one Nessie withdrawal + deposit pair per money movement (§11.4)
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
