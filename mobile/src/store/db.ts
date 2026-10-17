// Local SQLite stores (§19.4). One database, opened once, synchronous API.
import { openDatabaseSync, type SQLiteDatabase } from 'expo-sqlite';

let db: SQLiteDatabase | null = null;

const SCHEMA = `
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- One row per cert version; the counter/cum/head live in wallet_state.
CREATE TABLE IF NOT EXISTS wallet (
  cert_id TEXT NOT NULL,
  cert_ver INTEGER NOT NULL,
  cert_json TEXT NOT NULL,
  PRIMARY KEY (cert_id, cert_ver)
);

CREATE TABLE IF NOT EXISTS wallet_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  cert_id TEXT NOT NULL,
  counter INTEGER NOT NULL,
  cum_cents INTEGER NOT NULL,
  chain_head TEXT NOT NULL,
  key_ref TEXT NOT NULL
);

-- Wallet snapshots taken before each payment; judge mode restores them (§19.3).
CREATE TABLE IF NOT EXISTS wallet_history (
  counter INTEGER PRIMARY KEY,
  cum_cents INTEGER NOT NULL,
  chain_head TEXT NOT NULL,
  tag_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
  item_id TEXT PRIMARY KEY,
  id8 TEXT NOT NULL,
  kind TEXT NOT NULL,
  body_json TEXT NOT NULL,
  path_json TEXT NOT NULL DEFAULT '[]',
  priority INTEGER NOT NULL,
  cert_id TEXT,
  received_at INTEGER NOT NULL,
  receipted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_id8 ON items (id8);
CREATE INDEX IF NOT EXISTS items_cert ON items (cert_id);

CREATE TABLE IF NOT EXISTS device_log (
  seq INTEGER PRIMARY KEY,
  entry_hash TEXT NOT NULL,
  kind TEXT NOT NULL,
  entry_json TEXT NOT NULL,
  ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS peers (
  peer_pub TEXT PRIMARY KEY,
  label TEXT,
  last_seen INTEGER NOT NULL,
  sessions INTEGER NOT NULL DEFAULT 0,
  last_contact_id TEXT
);

CREATE TABLE IF NOT EXISTS merchant_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  mcert_json TEXT,
  open_request_json TEXT,
  limit_cents INTEGER
);

CREATE TABLE IF NOT EXISTS policy (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  policy_ver INTEGER NOT NULL,
  policy_json TEXT NOT NULL
);
`;

export function getDb(): SQLiteDatabase {
  if (!db) {
    db = openDatabaseSync('stormcash.db');
    db.execSync(SCHEMA);
  }
  return db;
}

export function resetDb(): void {
  const d = getDb();
  d.execSync(`
    DELETE FROM settings; DELETE FROM wallet; DELETE FROM wallet_state; DELETE FROM wallet_history;
    DELETE FROM items; DELETE FROM device_log; DELETE FROM peers; DELETE FROM merchant_state;
    DELETE FROM policy;
  `);
}

export function getSetting(key: string): string | null {
  return getDb().getFirstSync<{ value: string }>('SELECT value FROM settings WHERE key = ?', key)?.value ?? null;
}

export function setSetting(key: string, value: string | null): void {
  if (value === null) getDb().runSync('DELETE FROM settings WHERE key = ?', key);
  else getDb().runSync('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', key, value);
}
