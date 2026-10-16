// Offline checks and fraud rules (§8, §9.4, §9.5). Pure functions, no I/O.
import { type Hex } from './encoding';
import {
  detailsHash,
  dlogGenesis,
  dlogHash,
  genesis,
  id8,
  tagHash,
  verifyDlog,
  verifyObject,
  type CheckId,
  type Cert,
  type Dlog,
  type EquivocationRule,
  type MCert,
  type Pay,
  type Policy,
  type Req,
  type Tag,
} from './objects';

export const CLOCK_TOLERANCE_S = 600;

// ---- Equivocation (§8.3) ----

/** Returns the first rule (R1, R2, R3) two tags of one cert break, or null. */
export function equivocation(x: Tag, y: Tag): EquivocationRule | null {
  if (x.cert_id !== y.cert_id) return null;
  const [a, b] = x.counter <= y.counter ? [x, y] : [y, x];
  const ha = tagHash(a);
  if (a.counter === b.counter) return ha !== tagHash(b) ? 'SAME_COUNTER' : null;
  if (b.counter === a.counter + 1 && b.prev_hash !== ha) return 'BROKEN_LINK';
  if (b.cum_cents - b.amount_cents < a.cum_cents) return 'TOTAL_BACKWARDS';
  return null;
}

/** Single-tag validity: counter 1 links to GENESIS and its running total equals its amount. */
export function singleTagValid(t: Tag): boolean {
  if (t.counter < 1 || t.amount_cents <= 0 || t.cum_cents < t.amount_cents) return false;
  if (t.counter === 1) return t.prev_hash === genesis(t.cert_id) && t.cum_cents === t.amount_cents;
  return true;
}

// ---- Payer-side checks (§8.1) ----

export type PayerCheck =
  | { ok: true }
  | { ok: false; reason: 'MCERT_INVALID' | 'MCERT_EXPIRED' | 'REQ_INVALID' | 'REQ_EXPIRED' | 'OVER_LIMIT' };

export function payerChecks(
  mc: MCert, rq: Req, serverPub: Hex, now: number, capCents: number, cumSoFar: number,
): PayerCheck {
  if (!verifyObject('MCERT', mc, serverPub)) return { ok: false, reason: 'MCERT_INVALID' };
  if (mc.expires_at + CLOCK_TOLERANCE_S < now) return { ok: false, reason: 'MCERT_EXPIRED' };
  if (rq.merchant_id !== mc.merchant_id || !verifyObject('REQ', rq, mc.merchant_pub)) {
    return { ok: false, reason: 'REQ_INVALID' };
  }
  if (!(rq.req_expires_at > now - CLOCK_TOLERANCE_S)) return { ok: false, reason: 'REQ_EXPIRED' };
  if (rq.amount_cents <= 0 || rq.amount_cents > capCents - cumSoFar) return { ok: false, reason: 'OVER_LIMIT' };
  return { ok: true };
}

// ---- Merchant offline checks C1–C6 (§8.2) ----

export interface MerchantContext {
  serverPub: Hex;
  now: number;
  merchantPub: Hex;
  merchantId: Hex;
  openRequest: Req | null;
  policy: Policy | null;
  storedTags: Tag[]; // every tag held for this cert_id (others are ignored)
}

export type CheckResult =
  | { ok: true }
  | {
      ok: false;
      check: CheckId;
      reason: string; // UI copy for the red screen
      rule?: EquivocationRule;
      conflicting?: Tag; // the stored tag that proves C6
    };

export const RULE_COPY: Record<EquivocationRule, string> = {
  SAME_COUNTER: 'same counter',
  BROKEN_LINK: 'broken link',
  TOTAL_BACKWARDS: 'total went backwards',
};

export function merchantLimit(policy: Policy | null, merchantId: Hex): number | null {
  for (const entry of policy?.merchant_limits ?? []) {
    const [id, cents] = entry.split(':');
    if (id === merchantId) return Number(cents);
  }
  return null;
}

export function merchantChecks(pay: Pay, ctx: MerchantContext): CheckResult {
  const { c, t, d } = pay;
  const fail = (check: CheckId, reason: string, extra: object = {}): CheckResult => ({
    ok: false, check, reason, ...extra,
  });

  // C1
  if (!verifyObject('CERT', c, ctx.serverPub)) return fail('C1', 'Certificate not issued by StormCash');
  // C2
  if (c.expires_at + CLOCK_TOLERANCE_S < ctx.now) return fail('C2', 'Certificate expired');
  if (ctx.policy?.frozen_certs.includes(c.cert_id)) return fail('C2', 'Certificate frozen');
  // C3
  if (t.cert_id !== c.cert_id || !verifyObject('TAG', t, c.holder_pub)) {
    return fail('C3', "Signature doesn't match");
  }
  // C4
  const rq = ctx.openRequest;
  let detOk = false;
  try {
    detOk = detailsHash(d) === t.details_hash;
  } catch {
    detOk = false;
  }
  if (
    !rq || !detOk || d.merchant_pub !== ctx.merchantPub || d.nonce !== rq.nonce ||
    t.amount_cents !== rq.amount_cents || !(rq.req_expires_at > ctx.now - CLOCK_TOLERANCE_S)
  ) {
    return fail('C4', 'Payment is for a different request');
  }
  // C5
  if (t.amount_cents <= 0 || t.cum_cents < t.amount_cents || t.cum_cents > c.cap_cents) {
    return fail('C5', 'Over certificate cap');
  }
  if (t.counter === 1 && t.cum_cents !== t.amount_cents) return fail('C5', 'Over certificate cap');
  const limit = merchantLimit(ctx.policy, ctx.merchantId);
  if (limit !== null && t.amount_cents > limit) return fail('C5', "Over this shop's limit");
  // C6
  const spent = (rule: EquivocationRule, conflicting?: Tag) =>
    fail('C6', `These funds were already spent nearby (Rule: ${RULE_COPY[rule]}). Certificate flagged.`, {
      rule, conflicting,
    });
  if (t.counter === 1 && t.prev_hash !== genesis(t.cert_id)) return spent('BROKEN_LINK');
  const same = ctx.storedTags.filter((s) => s.cert_id === t.cert_id);
  for (const s of same) {
    const rule = equivocation(s, t);
    if (rule) return spent(rule, s);
  }
  const highest = same.reduce((m, s) => Math.max(m, s.counter), 0);
  if (t.counter <= highest) {
    const dup = same.find((s) => s.counter === t.counter) ?? same[0];
    return fail('C6', 'This payment was already received.', { conflicting: dup });
  }
  return { ok: true };
}

// ---- R4 OVER_CAP (server-side; here for vector parity) ----

export function overCap(tags: Tag[], certVersions: Cert[]): boolean {
  const maxCap = certVersions.reduce((m, c) => Math.max(m, c.cap_cents), 0);
  const maxCum = tags.reduce((m, t) => Math.max(m, t.cum_cents), 0);
  return maxCum > maxCap;
}

// ---- R6 LOG_TAMPER (§9.5) ----

export type ChainCheck = { ok: true } | { ok: false; seq: number; reason: 'FORK' | 'BROKEN_LINK' | 'BAD_SIG' };

/** Checks one device's DLOG entries (any order). */
export function checkDlogChain(entries: Dlog[]): ChainCheck {
  const bySeq = new Map<number, Dlog>();
  for (const e of [...entries].sort((x, y) => x.seq - y.seq)) {
    if (!verifyDlog(e)) return { ok: false, seq: e.seq, reason: 'BAD_SIG' };
    const prev = bySeq.get(e.seq);
    if (prev && dlogHash(prev) !== dlogHash(e)) return { ok: false, seq: e.seq, reason: 'FORK' };
    bySeq.set(e.seq, e);
  }
  for (const [seq, e] of bySeq) {
    const expected =
      seq === 1 ? dlogGenesis(e.device_pub) : bySeq.has(seq - 1) ? dlogHash(bySeq.get(seq - 1)!) : null;
    if (expected !== null && e.prev_hash !== expected) return { ok: false, seq, reason: 'BROKEN_LINK' };
  }
  return { ok: true };
}

// ---- R5 MERCHANT_KNEW (§9.4) ----

export interface MerchantKnewInput {
  accepted: Tag; // z
  merchantPub: Hex;
  acceptTs: number;
  acceptEntry: Dlog | null; // M's ACCEPT entry for z
  otherTags: Tag[]; // known tags of the same cert
  contacts: Dlog[]; // CONTACT entries from every device, verified
}

/** Returns the tag x that M knowingly accepted a conflict with, or null. */
export function merchantKnew(inp: MerchantKnewInput): Tag | null {
  const z = inp.accepted;
  const zHash = tagHash(z);
  const conflicts = inp.otherTags.filter((x) => tagHash(x) !== zHash && equivocation(x, z));
  for (const x of conflicts) {
    const xHash = tagHash(x);
    // (a) M's own ACCEPT entry lists x
    if (inp.acceptEntry?.kind === 'ACCEPT' && inp.acceptEntry.held_ids.includes(xHash)) return x;
    // (b) a paired contact before acceptance that delivered x to M
    const x8 = id8(xHash);
    const contacts = inp.contacts.filter((e) => e.kind === 'CONTACT') as Extract<Dlog, { kind: 'CONTACT' }>[];
    const mine = contacts.filter((e) => e.device_pub === inp.merchantPub && e.ts < inp.acceptTs);
    for (const m of mine) {
      const peer = contacts.find(
        (p) => p.contact_id === m.contact_id && p.device_pub === m.peer_pub && p.peer_pub === inp.merchantPub,
      );
      if (!peer) continue; // one-sided contact is weak evidence only
      if (peer.sent_ids.includes(x8) || m.recv_ids.includes(x8)) return x;
    }
  }
  return null;
}
