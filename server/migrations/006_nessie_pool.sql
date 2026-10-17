-- [v4.19] A demo reset opens a fresh guarantee pool account; the newest row is the current pool
-- (spec §11.4). Without a row the server uses NESSIE_POOL_ACCOUNT_ID. Safe to run twice.
CREATE TABLE IF NOT EXISTS nessie_pool_accounts (
  pool_id BIGSERIAL PRIMARY KEY,
  account_id TEXT UNIQUE NOT NULL,
  customer_id TEXT,
  opening_cents INT NOT NULL,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
