// This device's signed, hash-chained log (§9.2). Every entry is also an item so it syncs.
import { dlogGenesis, dlogHash, signDlog, type Dlog, type Hex } from '../protocol';
import { getDb } from './db';
import { nowS, putItem } from './items';

type DlogBody =
  | Pick<Extract<Dlog, { kind: 'ACCEPT' }>, 'kind' | 'tag_hash' | 'cert_id' | 'held_ids'>
  | Pick<Extract<Dlog, { kind: 'REFUSE' }>, 'kind' | 'tag_hash' | 'cert_id' | 'check'>
  | Pick<
      Extract<Dlog, { kind: 'CONTACT' }>,
      'kind' | 'contact_id' | 'peer_pub' | 'sent_ids' | 'recv_ids' | 'sent_overflow' | 'recv_overflow'
    >;

export function appendLog(body: DlogBody, devicePub: Hex, priv: Hex, ts = nowS()): Dlog {
  const db = getDb();
  let entry!: Dlog;
  db.withTransactionSync(() => {
    const last = db.getFirstSync<{ seq: number; entry_hash: string }>(
      'SELECT seq, entry_hash FROM device_log ORDER BY seq DESC LIMIT 1',
    );
    const seq = (last?.seq ?? 0) + 1;
    const prev = last ? last.entry_hash : dlogGenesis(devicePub);
    entry = signDlog({ device_pub: devicePub, seq, prev_hash: prev, ts, ...body } as Dlog, priv);
    db.runSync(
      'INSERT INTO device_log (seq, entry_hash, kind, entry_json, ts) VALUES (?, ?, ?, ?, ?)',
      seq, dlogHash(entry), entry.kind, JSON.stringify(entry), ts,
    );
    putItem('DLOG', entry, [], ts);
  });
  return entry;
}

export function logEntries(limit = 50): Dlog[] {
  return getDb()
    .getAllSync<{ entry_json: string }>('SELECT entry_json FROM device_log ORDER BY seq DESC LIMIT ?', limit)
    .map((r) => JSON.parse(r.entry_json) as Dlog);
}
