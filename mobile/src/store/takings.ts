// The shop's takings, read from its own signed log: every payment it accepted or refused, with
// the amount from the stored PAY and whether the StormCash server has receipted it (§10.4).
// A receipt means the server received the record; it is not a per-payment settlement report.
import { tagHash, type Dlog, type Hex, type Pay } from '../protocol';
import { getDb } from './db';
import { itemsOfKind } from './items';

export interface Taking {
  tagHash: Hex;
  ts: number; // this phone's clock when it checked the payment
  accepted: boolean;
  check: string | null; // the failed check when refused
  amountCents: number | null; // null when the PAY has aged out of storage
  counter: number | null;
  certId: Hex;
  receipted: boolean; // the server has this payment
}

export function takings(limit = 50): Taking[] {
  const pays = new Map<Hex, { pay: Pay; receipted: boolean }>();
  for (const it of itemsOfKind('PAY')) {
    try {
      pays.set(tagHash((it.body as Pay).t), { pay: it.body as Pay, receipted: it.receipted });
    } catch {
      // a malformed stored PAY has no hash to match
    }
  }
  return getDb()
    .getAllSync<{ entry_json: string }>(
      "SELECT entry_json FROM device_log WHERE kind IN ('ACCEPT', 'REFUSE') ORDER BY seq DESC LIMIT ?", limit,
    )
    .map((r) => JSON.parse(r.entry_json) as Extract<Dlog, { kind: 'ACCEPT' | 'REFUSE' }>)
    .map((e) => {
      const p = pays.get(e.tag_hash);
      return {
        tagHash: e.tag_hash,
        ts: e.ts,
        accepted: e.kind === 'ACCEPT',
        check: e.kind === 'REFUSE' ? e.check : null,
        amountCents: p?.pay.t.amount_cents ?? null,
        counter: p?.pay.t.counter ?? null,
        certId: e.cert_id,
        receipted: p?.receipted ?? false,
      };
    });
}

export function takingsTotals(list: Taking[]): { acceptedCents: number; uploadedCents: number; waitingCents: number; refused: number } {
  let acceptedCents = 0;
  let uploadedCents = 0;
  let refused = 0;
  for (const t of list) {
    if (!t.accepted) refused++;
    else if (t.amountCents !== null) {
      acceptedCents += t.amountCents;
      if (t.receipted) uploadedCents += t.amountCents;
    }
  }
  return { acceptedCents, uploadedCents, waitingCents: acceptedCents - uploadedCents, refused };
}
