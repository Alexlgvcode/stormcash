// Syncable items (§10.2, §10.4): everything this phone carries until a receipt covers it.
import {
  deviceShortId,
  id8,
  itemId,
  ITEM_PRIORITY,
  type Hex,
  type ItemBody,
  type ItemKind,
  type Pay,
  type Proof,
  type Tag,
} from '../protocol';
import { getDb } from './db';

export type PathHop = [deviceShortId: string, ts: number];

export interface StoredItem {
  itemId: Hex;
  kind: ItemKind;
  body: ItemBody;
  path: PathHop[];
  priority: number;
  receivedAt: number;
  receipted: boolean;
}

const MAX_ITEMS = 5000;
const RETENTION_S = 7 * 24 * 3600;

interface Row {
  item_id: string; kind: ItemKind; body_json: string; path_json: string;
  priority: number; received_at: number; receipted: number;
}

const fromRow = (r: Row): StoredItem => ({
  itemId: r.item_id,
  kind: r.kind,
  body: JSON.parse(r.body_json) as ItemBody,
  path: JSON.parse(r.path_json) as PathHop[],
  priority: r.priority,
  receivedAt: r.received_at,
  receipted: r.receipted === 1,
});

function certIdOf(kind: ItemKind, body: ItemBody): Hex | null {
  switch (kind) {
    case 'TAG': return (body as Tag).cert_id;
    case 'PAY': return (body as Pay).t.cert_id;
    case 'PROOF': return (body as Proof).a.cert_id;
    default: return null;
  }
}

/** Stores an item (already verified by the caller). Returns its id and whether it was new. */
export function putItem(kind: ItemKind, body: ItemBody, path: PathHop[] = [], now = nowS()): { id: Hex; isNew: boolean } {
  const id = itemId(kind, body);
  const db = getDb();
  const existing = db.getFirstSync<{ kind: string }>('SELECT kind FROM items WHERE item_id = ?', id);
  if (existing) {
    // PAY and TAG share an id; a PAY supersedes the bare TAG.
    if (existing.kind === 'TAG' && kind === 'PAY') {
      db.runSync('UPDATE items SET kind = ?, body_json = ?, priority = ?, path_json = ? WHERE item_id = ?',
        kind, JSON.stringify(body), ITEM_PRIORITY[kind], JSON.stringify(path), id);
    }
    return { id, isNew: false };
  }
  db.runSync(
    `INSERT INTO items (item_id, id8, kind, body_json, path_json, priority, cert_id, received_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    id, id8(id), kind, JSON.stringify(body), JSON.stringify(path), ITEM_PRIORITY[kind], certIdOf(kind, body), now,
  );
  evict(now);
  return { id, isNew: true };
}

export function appendPath(ids: Hex[], hop: PathHop): void {
  const db = getDb();
  for (const id of ids) {
    const r = db.getFirstSync<{ path_json: string }>('SELECT path_json FROM items WHERE item_id = ?', id);
    if (!r) continue;
    const path = JSON.parse(r.path_json) as PathHop[];
    path.push(hop);
    db.runSync('UPDATE items SET path_json = ? WHERE item_id = ?', JSON.stringify(path), id);
  }
}

export function getItem(id: Hex): StoredItem | null {
  const r = getDb().getFirstSync<Row>('SELECT * FROM items WHERE item_id = ?', id);
  return r ? fromRow(r) : null;
}

/** id8 of everything held, highest priority first, capped (§10.3). */
export function inventory(cap = 5000): Hex[] {
  return getDb()
    .getAllSync<{ id8: string }>('SELECT id8 FROM items ORDER BY priority, received_at LIMIT ?', cap)
    .map((r) => r.id8);
}

export function inventoryOfKind(kind: ItemKind): Hex[] {
  return getDb().getAllSync<{ id8: string }>('SELECT id8 FROM items WHERE kind = ?', kind).map((r) => r.id8);
}

export function itemsById8(ids8: Hex[]): StoredItem[] {
  if (ids8.length === 0) return [];
  const marks = ids8.map(() => '?').join(',');
  return getDb()
    .getAllSync<Row>(`SELECT * FROM items WHERE id8 IN (${marks}) ORDER BY priority, received_at`, ...ids8)
    .map(fromRow);
}

/** Items with no receipt yet, for upload (§10.5). */
export function unreceipted(): StoredItem[] {
  return getDb().getAllSync<Row>('SELECT * FROM items WHERE receipted = 0 ORDER BY priority, received_at').map(fromRow);
}

export function itemsOfKind(kind: ItemKind): StoredItem[] {
  return getDb().getAllSync<Row>('SELECT * FROM items WHERE kind = ? ORDER BY received_at', kind).map(fromRow);
}

/** Every tag this phone holds for a cert: bare TAGs, tags inside PAYs, both tags of PROOFs. */
export function tagsForCert(certId: Hex): Tag[] {
  const rows = getDb().getAllSync<Row>('SELECT * FROM items WHERE cert_id = ?', certId).map(fromRow);
  const tags: Tag[] = [];
  for (const it of rows) {
    if (it.kind === 'TAG') tags.push(it.body as Tag);
    else if (it.kind === 'PAY') tags.push((it.body as Pay).t);
    else if (it.kind === 'PROOF') tags.push((it.body as Proof).a, (it.body as Proof).b);
  }
  return tags;
}

export function markReceipted(ids: Hex[]): void {
  const db = getDb();
  for (const id of ids) {
    db.runSync("DELETE FROM items WHERE item_id = ? AND kind NOT IN ('PROOF', 'POLICY')", id);
    db.runSync('UPDATE items SET receipted = 1 WHERE item_id = ?', id);
  }
}

export function countsByKind(): Partial<Record<ItemKind, number>> {
  const out: Partial<Record<ItemKind, number>> = {};
  for (const r of getDb().getAllSync<{ kind: ItemKind; n: number }>(
    'SELECT kind, COUNT(*) AS n FROM items WHERE receipted = 0 GROUP BY kind',
  )) out[r.kind] = r.n;
  return out;
}

function evict(now: number): void {
  const db = getDb();
  db.runSync(
    "DELETE FROM items WHERE received_at < ? AND kind NOT IN ('PROOF', 'POLICY')",
    now - RETENTION_S,
  );
  const n = db.getFirstSync<{ n: number }>('SELECT COUNT(*) AS n FROM items')?.n ?? 0;
  if (n > MAX_ITEMS) {
    db.runSync(
      `DELETE FROM items WHERE item_id IN (
         SELECT item_id FROM items WHERE kind NOT IN ('PROOF', 'POLICY')
         ORDER BY priority DESC, received_at ASC LIMIT ?)`,
      n - MAX_ITEMS,
    );
  }
}

export const nowS = (): number => Math.floor(Date.now() / 1000);

/** First hop for an item this device creates: [first 4 bytes of the device pub, ts] (§10.2). */
export const originHop = (devicePub: Hex, ts: number): PathHop[] => [[deviceShortId(devicePub), ts]];
