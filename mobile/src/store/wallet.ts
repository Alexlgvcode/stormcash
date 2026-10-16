// Resident wallet: cert versions, counter, running total, chain head (§19.4).
import { genesis, type Cert, type Hex, type Tag, tagHash } from '../protocol';
import { getDb } from './db';

export interface WalletState {
  certId: Hex;
  counter: number;
  cumCents: number;
  chainHead: Hex;
  keyRef: string;
}

export function saveCertVersion(cert: Cert, keyRef: string): void {
  const db = getDb();
  db.withTransactionSync(() => {
    db.runSync(
      'INSERT OR REPLACE INTO wallet (cert_id, cert_ver, cert_json) VALUES (?, ?, ?)',
      cert.cert_id, cert.cert_ver, JSON.stringify(cert),
    );
    db.runSync(
      `INSERT OR IGNORE INTO wallet_state (id, cert_id, counter, cum_cents, chain_head, key_ref)
       VALUES (1, ?, 0, 0, ?, ?)`,
      cert.cert_id, genesis(cert.cert_id), keyRef,
    );
  });
}

export function certVersions(): Cert[] {
  return getDb()
    .getAllSync<{ cert_json: string }>('SELECT cert_json FROM wallet ORDER BY cert_ver')
    .map((r) => JSON.parse(r.cert_json) as Cert);
}

export function latestCert(): Cert | null {
  const r = getDb().getFirstSync<{ cert_json: string }>(
    'SELECT cert_json FROM wallet ORDER BY cert_ver DESC LIMIT 1',
  );
  return r ? (JSON.parse(r.cert_json) as Cert) : null;
}

export function walletState(): WalletState | null {
  const r = getDb().getFirstSync<{
    cert_id: string; counter: number; cum_cents: number; chain_head: string; key_ref: string;
  }>('SELECT * FROM wallet_state WHERE id = 1');
  return r
    ? { certId: r.cert_id, counter: r.counter, cumCents: r.cum_cents, chainHead: r.chain_head, keyRef: r.key_ref }
    : null;
}

/** Advances the wallet past a signed tag and keeps a snapshot for judge mode. Atomic. */
export function commitPayment(tag: Tag, before: WalletState): void {
  const db = getDb();
  db.withTransactionSync(() => {
    db.runSync(
      'INSERT OR REPLACE INTO wallet_history (counter, cum_cents, chain_head, tag_hash) VALUES (?, ?, ?, ?)',
      tag.counter, before.cumCents, before.chainHead, tagHash(tag),
    );
    db.runSync(
      'UPDATE wallet_state SET counter = ?, cum_cents = ?, chain_head = ? WHERE id = 1',
      tag.counter, tag.cum_cents, tagHash(tag),
    );
  });
}

export type RollbackMode = 'reuse' | 'clever';

/**
 * Judge mode (§19.3). "reuse": back to before the last payment (same counter, same total).
 * "clever": same, but the next counter skips one past the real one.
 * Returns false when there is no payment to roll back.
 */
export function rollBack(mode: RollbackMode): boolean {
  const db = getDb();
  const state = walletState();
  if (!state) return false;
  const last = db.getFirstSync<{ counter: number; cum_cents: number; chain_head: string }>(
    'SELECT counter, cum_cents, chain_head FROM wallet_history WHERE counter <= ? ORDER BY counter DESC LIMIT 1',
    state.counter,
  );
  if (!last) return false;
  const counter = mode === 'reuse' ? last.counter - 1 : last.counter;
  db.runSync(
    'UPDATE wallet_state SET counter = ?, cum_cents = ?, chain_head = ? WHERE id = 1',
    counter, last.cum_cents, last.chain_head,
  );
  return true;
}
