-- [v4.15] The reviewer Droid (spec §14.7b): review runs, and each flag's second opinion.
-- Additive and safe to run twice. A fresh database gets all of it from schema.sql.
ALTER TABLE stormdesk_runs DROP CONSTRAINT IF EXISTS stormdesk_runs_job_check;
ALTER TABLE stormdesk_runs ADD CONSTRAINT stormdesk_runs_job_check
  CHECK (job IN ('investigate','triage','respond','review'));
ALTER TABLE flags ADD COLUMN IF NOT EXISTS review JSONB;
ALTER TABLE flags ADD COLUMN IF NOT EXISTS agents_disagree BOOLEAN NOT NULL DEFAULT FALSE;
