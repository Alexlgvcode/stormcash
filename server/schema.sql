-- StormCash schema. Source: STORMCASH_BUILD_SPEC.md §11.1. Owned by WS2.

-- Entities
CREATE TABLE regions (
  region_id TEXT PRIMARY KEY,           -- e.g. 'asheville-downtown'
  display_name TEXT NOT NULL,
  county TEXT NOT NULL,                 -- 'Buncombe'
  x INT NOT NULL, y INT NOT NULL, w INT NOT NULL, h INT NOT NULL  -- map rectangle on town grid
);

CREATE TABLE residents (
  resident_id UUID PRIMARY KEY,
  display_name TEXT NOT NULL,
  holder_pub BYTEA UNIQUE NOT NULL,
  region_id TEXT REFERENCES regions,
  nessie_customer_id TEXT,
  checking_account_id TEXT,
  escrow_account_id TEXT,
  simulated BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE merchants (
  merchant_id BYTEA PRIMARY KEY,        -- 16 bytes
  display_name TEXT NOT NULL,
  merchant_pub BYTEA UNIQUE NOT NULL,
  region_id TEXT REFERENCES regions,
  x INT, y INT,                         -- position on town map
  nessie_account_id TEXT,
  per_payment_limit_cents INT,          -- NULL = none
  pool_eligible BOOLEAN NOT NULL DEFAULT TRUE,
  simulated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE merchant_contacts (        -- Photon mapping
  merchant_id BYTEA REFERENCES merchants,
  channel TEXT NOT NULL,                -- 'telegram' | 'imessage' | 'sms'
  handle TEXT NOT NULL,
  PRIMARY KEY (channel, handle)
);

CREATE TABLE certificates (
  cert_id BYTEA NOT NULL,
  cert_ver INT NOT NULL,
  resident_id UUID REFERENCES residents,
  holder_pub BYTEA NOT NULL,
  cap_cents INT NOT NULL,
  issued_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL,
  escrow_ref TEXT NOT NULL,
  server_sig BYTEA NOT NULL,
  PRIMARY KEY (cert_id, cert_ver)
);
CREATE TABLE cert_status (
  cert_id BYTEA PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('active','frozen','closing','closed')),
  max_cap_cents INT NOT NULL,
  frozen_at BIGINT,
  storm_mode BOOLEAN NOT NULL DEFAULT FALSE,
  storm_mode_at BIGINT
);

-- Protocol data
CREATE TABLE tags (                     -- every tag the server has seen (from PAY or gossip)
  tag_hash BYTEA PRIMARY KEY,
  cert_id BYTEA NOT NULL,
  counter INT NOT NULL,
  prev_hash BYTEA NOT NULL,
  amount_cents INT NOT NULL,
  cum_cents INT NOT NULL,
  details_hash BYTEA NOT NULL,
  sig BYTEA NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON tags (cert_id, counter);

CREATE TABLE payments (
  tag_hash BYTEA PRIMARY KEY REFERENCES tags,
  cert_id BYTEA NOT NULL,
  merchant_id BYTEA NOT NULL REFERENCES merchants,
  nonce BYTEA NOT NULL,
  device_ts BIGINT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  relay_device BYTEA,                   -- pub of the uploader
  hops INT,
  path JSONB,
  status TEXT NOT NULL CHECK (status IN
    ('pending','settled','held','denied_knowing','refused_evidence','invalid')),
  funded_escrow_cents INT NOT NULL DEFAULT 0,
  funded_pool_cents INT NOT NULL DEFAULT 0
);
CREATE INDEX ON payments (merchant_id, device_ts);
CREATE INDEX ON payments (cert_id);

CREATE TABLE device_log (
  device_pub BYTEA NOT NULL,
  seq INT NOT NULL,
  entry_hash BYTEA NOT NULL,
  prev_hash BYTEA NOT NULL,
  ts BIGINT NOT NULL,
  kind TEXT NOT NULL,
  body JSONB NOT NULL,
  sig BYTEA NOT NULL,
  PRIMARY KEY (device_pub, seq, entry_hash)   -- allows storing forks as evidence
);
CREATE INDEX ON device_log (device_pub, ts);

CREATE TABLE contacts (                 -- derived from CONTACT entries
  contact_id BYTEA NOT NULL,
  device_pub BYTEA NOT NULL,
  peer_pub BYTEA NOT NULL,
  ts BIGINT NOT NULL,
  sent_ids BYTEA[] NOT NULL,
  recv_ids BYTEA[] NOT NULL,
  paired BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (contact_id, device_pub)
);
CREATE INDEX ON contacts (device_pub, ts);

-- Hard cases (deterministic)
CREATE TABLE cases (
  case_id BIGSERIAL PRIMARY KEY,
  rule TEXT NOT NULL CHECK (rule IN
    ('SAME_COUNTER','BROKEN_LINK','TOTAL_BACKWARDS','OVER_CAP','MERCHANT_KNEW','LOG_TAMPER')),
  cert_id BYTEA,
  merchant_id BYTEA,
  device_pub BYTEA,
  tag_a BYTEA, tag_b BYTEA,
  evidence JSONB NOT NULL,              -- ids of everything that proves it
  detected_where TEXT NOT NULL CHECK (detected_where IN ('offline','server')),
  exposure_cents INT NOT NULL DEFAULT 0,
  case_file_md TEXT,                    -- written by StormDesk
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Soft flags (detector candidates + agent verdicts)
CREATE TABLE candidates (
  candidate_id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('merchant_silence','cap_drain','region_dark')),
  subject_id TEXT NOT NULL,             -- merchant_id hex | cert_id hex | region_id
  window_start BIGINT NOT NULL, window_end BIGINT NOT NULL,
  features JSONB NOT NULL,              -- detector inputs, frozen at creation
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, subject_id, window_start)
);

CREATE TABLE flags (                    -- StormDesk output (one per candidate)
  flag_id BIGSERIAL PRIMARY KEY,
  candidate_id BIGINT REFERENCES candidates,
  kind TEXT NOT NULL,                   -- may be 'none' (agent dismissed)
  severity TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  evidence_ids TEXT[] NOT NULL,
  exposure_cents INT NOT NULL,
  summary TEXT NOT NULL,
  proposed_action TEXT NOT NULL,
  citations_valid BOOLEAN NOT NULL,
  agent_session_id TEXT,
  agent_transcript JSONB,               -- tool calls for replay on dashboard
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','rejected','dismissed','invalid')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE approvals (
  approval_id BIGSERIAL PRIMARY KEY,
  flag_id BIGINT REFERENCES flags,
  decision TEXT NOT NULL CHECK (decision IN ('approve','reject')),
  operator TEXT NOT NULL,
  note TEXT,
  executed_actions JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (                 -- Photon conversations
  message_id BIGSERIAL PRIMARY KEY,
  merchant_id BYTEA REFERENCES merchants,
  flag_id BIGINT REFERENCES flags,
  direction TEXT NOT NULL CHECK (direction IN ('out','in')),
  channel TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Money
CREATE TABLE payouts (
  payout_id BIGSERIAL PRIMARY KEY,
  tag_hash BYTEA REFERENCES payments,
  merchant_id BYTEA NOT NULL,
  amount_cents INT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('escrow','pool')),
  nessie_transfer_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('queued','pending','executed','failed','ledger_only')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ledger_entries (
  entry_id BIGSERIAL PRIMARY KEY,
  txn_id UUID NOT NULL,
  account TEXT NOT NULL,
  debit_cents INT NOT NULL DEFAULT 0,
  credit_cents INT NOT NULL DEFAULT 0,
  ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE nessie_calls (             -- feeds the dashboard call log
  call_id BIGSERIAL PRIMARY KEY,
  method TEXT, path TEXT, request JSONB, status INT, response JSONB,
  summary TEXT,                         -- "POST transfer escrow → Pharmacy, $12.00"
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policy_versions (
  policy_ver INT PRIMARY KEY,
  issued_at BIGINT NOT NULL,
  frozen_certs BYTEA[] NOT NULL,
  merchant_limits TEXT[] NOT NULL,
  server_sig BYTEA NOT NULL
);

CREATE TABLE uploads (                  -- one row per /v1/sync call
  upload_id BIGSERIAL PRIMARY KEY,
  device_pub BYTEA NOT NULL,
  region_id TEXT,
  item_count INT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  simulated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE weather_alerts (
  alert_id TEXT PRIMARY KEY,
  region_id TEXT REFERENCES regions,
  event TEXT NOT NULL,                  -- 'Hurricane Warning', 'Flash Flood Warning'
  severity TEXT,
  onset BIGINT, expires BIGINT,
  source TEXT NOT NULL CHECK (source IN ('live','replayed')),
  raw JSONB
);
