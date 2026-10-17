-- [v4.3] Payouts can be held (an approved hold_pool_payout, spec §14.6). Safe to run twice.
ALTER TABLE payouts DROP CONSTRAINT IF EXISTS payouts_status_check;
ALTER TABLE payouts ADD CONSTRAINT payouts_status_check
  CHECK (status IN ('queued','pending','executed','failed','ledger_only','held'));
