-- [v4.3] Adds stormdesk_runs to a database created from an older schema.sql (e.g. the hosted demo DB).
-- Safe to run twice. A fresh database gets it from schema.sql.
CREATE TABLE IF NOT EXISTS stormdesk_runs (           -- [v4.3] every StormDesk run, for replay and audit (§14.7, §14.8)
  run_id BIGSERIAL PRIMARY KEY,
  job TEXT NOT NULL CHECK (job IN ('investigate','triage','respond')),
  case_id BIGINT REFERENCES cases,
  candidate_id BIGINT REFERENCES candidates,
  merchant_id BYTEA,
  runner TEXT NOT NULL,                 -- 'droid' | 'fake' (a fake run is never shown as an agent result)
  status TEXT NOT NULL CHECK (status IN ('running','succeeded','invalid','failed')),
  output JSONB,                         -- the structured output (Flag / CaseFile / AppealReply)
  citations_valid BOOLEAN,
  transcript JSONB NOT NULL DEFAULT '{}', -- {runner, steps: [{tool, input, ok}], missing_citations, error}
  session_id TEXT,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);
