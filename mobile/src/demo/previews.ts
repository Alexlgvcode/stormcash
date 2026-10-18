// Dev-build previews of the result screen (the simulator camera can't scan). Not used in Release.
// Realistic-looking ids and times so screenshots read like a real payment; nothing here is signed.
import type { Route } from '../nav';

const hex = (seed: number, bytes: number) =>
  Array.from({ length: bytes }, (_, i) => ((seed * 2654435761 + i * 40503) >>> (i % 24)) & 0xff)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
const now = Math.floor(Date.now() / 1000);

const CERT_ID = hex(7, 16);
const PREVIEW_TAG = {
  cert_id: CERT_ID, counter: 1, prev_hash: hex(11, 32), amount_cents: 1200, cum_cents: 1200,
  details_hash: hex(13, 32),
};
const PREVIEW_PAY = {
  c: { cert_id: CERT_ID, cert_ver: 2, holder_pub: '02' + hex(17, 32), cap_cents: 5000, issued_at: now - 2 * 3600, expires_at: now + 22 * 3600, escrow_ref: 'preview' },
  t: PREVIEW_TAG,
  d: { merchant_pub: '03' + hex(19, 32), nonce: hex(23, 16), ts: now },
};
// The copy the shop already holds: same wallet, same copy number, paid to the shop next door.
const HELD_TAG = { ...PREVIEW_TAG, details_hash: hex(29, 32) };
export const PREVIEW_OK: Route = { name: 'result', result: { ok: true }, pay: PREVIEW_PAY, capCents: 5000 };
export const PREVIEW_REFUSED: Route = {
  name: 'result', pay: PREVIEW_PAY, capCents: 5000,
  result: { ok: false, check: 'C6', reason: 'SAME_COUNTER', rule: 'SAME_COUNTER', conflict: HELD_TAG },
};
