-- [v4.13] Residents text FREEZE through Photon (spec §17.2): a resident's Photon handle, their thread in
-- `messages`, and when the owner asked for the freeze (feeds cap_drain's owner_freeze_request, §13.2).
-- Additive and safe to run twice. A fresh database gets all of it from schema.sql.
CREATE TABLE IF NOT EXISTS resident_contacts (  -- [v4.13] Photon mapping for residents (FREEZE by text)
  resident_id UUID NOT NULL REFERENCES residents,
  channel TEXT NOT NULL,                -- 'telegram' | 'imessage' | 'sms'
  handle TEXT NOT NULL,
  PRIMARY KEY (channel, handle)
);
ALTER TABLE cert_status ADD COLUMN IF NOT EXISTS owner_freeze_at BIGINT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS resident_id UUID REFERENCES residents;
