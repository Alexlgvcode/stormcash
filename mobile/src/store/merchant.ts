// Merchant state: merchant cert, the open payment request, per-payment limit (§19.4).
import type { MCert, Req } from '../protocol';
import { getDb } from './db';

interface Row { mcert_json: string | null; open_request_json: string | null; limit_cents: number | null }

function row(): Row | null {
  return getDb().getFirstSync<Row>('SELECT * FROM merchant_state WHERE id = 1');
}

function ensureRow(): void {
  getDb().runSync('INSERT OR IGNORE INTO merchant_state (id) VALUES (1)');
}

export function merchantCert(): MCert | null {
  const r = row();
  return r?.mcert_json ? (JSON.parse(r.mcert_json) as MCert) : null;
}

export function saveMerchantCert(mc: MCert): void {
  ensureRow();
  getDb().runSync('UPDATE merchant_state SET mcert_json = ? WHERE id = 1', JSON.stringify(mc));
}

export function openRequest(): Req | null {
  const r = row();
  return r?.open_request_json ? (JSON.parse(r.open_request_json) as Req) : null;
}

export function setOpenRequest(rq: Req | null): void {
  ensureRow();
  getDb().runSync('UPDATE merchant_state SET open_request_json = ? WHERE id = 1', rq ? JSON.stringify(rq) : null);
}
