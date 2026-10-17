-- [v4.22] Droid proposes a detector as a pull request (spec §14.7d): author runs are StormDesk runs.
-- Additive and safe to run twice. A fresh database gets it from schema.sql.
ALTER TABLE stormdesk_runs DROP CONSTRAINT IF EXISTS stormdesk_runs_job_check;
ALTER TABLE stormdesk_runs ADD CONSTRAINT stormdesk_runs_job_check
  CHECK (job IN ('investigate','triage','respond','review','author'));
