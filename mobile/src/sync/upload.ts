// Upload (§10.5): any phone with internet posts every item without a receipt, then stores the
// receipt, policy and renewed certs as items so they gossip back down.
import * as api from '../api';
import type { Hex, ItemBody, ItemKind } from '../protocol';
import { unreceipted } from '../store/items';
import { setSetting, getSetting } from '../store/db';
import { storeVerified } from './apply';
import { verifyItem } from './verify';

export interface UploadResult { sent: number; receipted: number; maxHops: number; ts: number }

const SERVER_ORIGINATED = new Set<ItemKind>(['RCPT', 'POLICY', 'CERT']);

export async function uploadAll(serverPub: Hex, now: number): Promise<UploadResult> {
  const items = unreceipted().filter((i) => !SERVER_ORIGINATED.has(i.kind));
  const res = await api.sync(items.map((i) => ({ kind: i.kind, body: i.body, path: i.path })));
  const down: [ItemKind, ItemBody | null][] = [['RCPT', res.rcpt], ['POLICY', res.policy], ...res.certs.map((c) => ['CERT', c] as [ItemKind, ItemBody])];
  for (const [kind, body] of down) {
    if (body && verifyItem(kind, body, serverPub)) storeVerified(kind, body, [], now);
  }
  const result: UploadResult = {
    sent: items.length,
    receipted: res.rcpt?.item_ids.length ?? 0,
    maxHops: items.reduce((m, i) => Math.max(m, i.path.length), 0),
    ts: now,
  };
  setSetting('last_upload', JSON.stringify(result));
  return result;
}

export function lastUpload(): UploadResult | null {
  const s = getSetting('last_upload');
  return s ? (JSON.parse(s) as UploadResult) : null;
}
