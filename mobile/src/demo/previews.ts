// Dev-build previews of the result screen (the simulator camera can't scan). Not used in Release.
import type { Route } from '../nav';

const PREVIEW_TAG = {
  cert_id: '00'.repeat(16), counter: 1, prev_hash: '00'.repeat(32), amount_cents: 1200, cum_cents: 1200,
  details_hash: '00'.repeat(32),
};
const PREVIEW_PAY = {
  c: { cert_id: '00'.repeat(16), cert_ver: 2, holder_pub: '02' + '00'.repeat(32), cap_cents: 5000, issued_at: 0, expires_at: 0, escrow_ref: 'preview' },
  t: PREVIEW_TAG,
  d: { merchant_pub: '02' + '00'.repeat(32), nonce: '00'.repeat(16), ts: 0 },
};
export const PREVIEW_OK: Route = { name: 'result', result: { ok: true }, pay: PREVIEW_PAY, capCents: 5000 };
export const PREVIEW_REFUSED: Route = {
  name: 'result', pay: PREVIEW_PAY, capCents: 5000,
  result: { ok: false, check: 'C6', reason: 'SAME_COUNTER', rule: 'SAME_COUNTER', conflict: PREVIEW_TAG },
};
