// Offline checks and hard fraud rules (§8.2, §8.3, §9.4, §9.5). Pure functions, no I/O.
// Mirrors server/stormcash/protocol/rules.py; spec/vectors.json keeps the two in step.
// Inputs other than the PAY under test are assumed verified (stored tags, policy, logs).
import { type Hex } from './encoding';
import {
  detailsHash,
  dlogGenesis,
  dlogHash,
  genesis,
  id8,
  tagHash,
  verifyObject,
  type CheckId,
  type Dlog,
  type EquivocationRule,
  type MCert,
  type Pay,
  type Policy,
  type Proof,
  type Req,
  type Tag,
} from './objects';

export const CLOCK_TOLERANCE_S = 600;

// ---- Single tags and pairs (§8.3) ----

/** counter ≥ 1, amount > 0, cum ≥ amount; counter 1 starts the chain (prev = GENESIS, cum = amount). */
export function tagValid(t: Tag): boolean {
  if (t.counter < 1 || t.amount_cents <= 0 || t.cum_cents < t.amount_cents) return false;
  if (t.counter === 1) return t.prev_hash === genesis(t.cert_id) && t.cum_cents === t.amount_cents;
  return true;
}

const cmp = (x: string, y: string): number => (x < y ? -1 : x > y ? 1 : 0);
const byCounterThenHash = (x: Tag, y: Tag): number => x.counter - y.counter || cmp(tagHash(x), tagHash(y));

/** Orders a pair so a.counter ≤ b.counter (ties by tag_hash). */
function ordered(x: Tag, y: Tag): [Tag, Tag] {
  return byCounterThenHash(x, y) <= 0 ? [x, y] : [y, x];
}

/** Every equivocation rule the pair breaks, in rule order R1, R2, R3. */
export function rulesFired(x: Tag, y: Tag): EquivocationRule[] {
  if (x.cert_id !== y.cert_id) return [];
  const [a, b] = ordered(x, y);
  const ha = tagHash(a);
  const fired: EquivocationRule[] = [];
  if (a.counter === b.counter && ha !== tagHash(b)) fired.push('SAME_COUNTER');
  if (b.counter === a.counter + 1 && b.prev_hash !== ha) fired.push('BROKEN_LINK');
  if (b.counter > a.counter && b.cum_cents - b.amount_cents < a.cum_cents) fired.push('TOTAL_BACKWARDS');
  return fired;
}

/** The lowest-numbered rule the pair breaks, or null. */
export function equivocation(x: Tag, y: Tag): EquivocationRule | null {
  return rulesFired(x, y)[0] ?? null;
}

export function makeProof(x: Tag, y: Tag): Proof | null {
  const rule = equivocation(x, y);
  if (!rule) return null;
  const [a, b] = ordered(x, y);
  return { a, b, rule };
}

/** Both tags signed by holderPub and they break the named rule (either order). */
export function verifyProof(p: Proof, holderPub: Hex): boolean {
  return (
    verifyObject('TAG', p.a, holderPub) &&
    verifyObject('TAG', p.b, holderPub) &&
    rulesFired(p.a, p.b).includes(p.rule)
  );
}

// ---- Payer-side checks (§8.1) ----

export type PayerCheck =
  | { ok: true }
  | { ok: false; reason: 'MCERT_INVALID' | 'MCERT_EXPIRED' | 'REQ_INVALID' | 'REQ_EXPIRED' | 'OVER_LIMIT' };

export function payerChecks(
  mc: MCert, rq: Req, serverPub: Hex, now: number, capCents: number, cumSoFar: number,
): PayerCheck {
  if (!verifyObject('MCERT', mc, serverPub)) return { ok: false, reason: 'MCERT_INVALID' };
  if (now > mc.expires_at + CLOCK_TOLERANCE_S) return { ok: false, reason: 'MCERT_EXPIRED' };
  if (rq.merchant_id !== mc.merchant_id || !verifyObject('REQ', rq, mc.merchant_pub)) {
    return { ok: false, reason: 'REQ_INVALID' };
  }
  if (!(rq.req_expires_at > now - CLOCK_TOLERANCE_S)) return { ok: false, reason: 'REQ_EXPIRED' };
  if (rq.amount_cents <= 0 || rq.amount_cents > capCents - cumSoFar) return { ok: false, reason: 'OVER_LIMIT' };
  return { ok: true };
}

// ---- Merchant offline checks C1–C6 (§8.2) ----

export type ReasonToken =
  | 'BAD_CERT_SIG' | 'EXPIRED' | 'FROZEN' | 'WRONG_CERT' | 'BAD_TAG_SIG'
  | 'DETAILS_MISMATCH' | 'WRONG_MERCHANT' | 'WRONG_NONCE' | 'WRONG_AMOUNT' | 'REQ_EXPIRED'
  | 'BAD_AMOUNT' | 'OVER_CAP' | 'OVER_LIMIT' | 'INVALID_TAG' | EquivocationRule | 'COUNTER_NOT_NEW';

export type CheckResult =
  | { ok: true }
  | { ok: false; check: CheckId; reason: ReasonToken; rule: EquivocationRule | null; conflict: Tag | null };

export interface MerchantCheckInput {
  serverPub: Hex;
  merchant: MCert; // this shop's own MCERT
  req: Req; // the open request it showed
  policy: Policy | null; // highest verified POLICY
  storedTags: Tag[]; // every verified tag this phone holds
  now: number;
}

export function merchantLimit(policy: Policy | null, merchantId: Hex): number | null {
  const prefix = merchantId + ':';
  for (const entry of policy?.merchant_limits ?? []) {
    if (entry.startsWith(prefix)) return Number(entry.slice(prefix.length));
  }
  return null;
}

/** Runs C1–C6 in order on a scanned PAY; the first failure wins. */
export function merchantCheck(pay: Pay, inp: MerchantCheckInput): CheckResult {
  const { c: cert, t: tag, d: det } = pay;
  const fail = (
    check: CheckId, reason: ReasonToken, rule: EquivocationRule | null = null, conflict: Tag | null = null,
  ): CheckResult => ({ ok: false, check, reason, rule, conflict });

  // C1: certificate issued by StormCash.
  if (!verifyObject('CERT', cert, inp.serverPub)) return fail('C1', 'BAD_CERT_SIG');

  // C2: not expired (10-min clock tolerance) and not frozen.
  if (inp.now > cert.expires_at + CLOCK_TOLERANCE_S) return fail('C2', 'EXPIRED');
  if (inp.policy && inp.policy.frozen_certs.includes(cert.cert_id)) return fail('C2', 'FROZEN');

  // C3: the tag is for this certificate and signed by its holder.
  if (tag.cert_id !== cert.cert_id) return fail('C3', 'WRONG_CERT');
  if (!verifyObject('TAG', tag, cert.holder_pub)) return fail('C3', 'BAD_TAG_SIG');

  // C4: the payment answers this shop's open request (merchant's own clock, no tolerance).
  if (tag.details_hash !== detailsHash(det)) return fail('C4', 'DETAILS_MISMATCH');
  if (det.merchant_pub !== inp.merchant.merchant_pub) return fail('C4', 'WRONG_MERCHANT');
  if (det.nonce !== inp.req.nonce) return fail('C4', 'WRONG_NONCE');
  if (tag.amount_cents !== inp.req.amount_cents) return fail('C4', 'WRONG_AMOUNT');
  if (inp.now > inp.req.req_expires_at) return fail('C4', 'REQ_EXPIRED');

  // C5: amounts.
  if (tag.amount_cents <= 0 || tag.cum_cents < tag.amount_cents) return fail('C5', 'BAD_AMOUNT');
  if (tag.cum_cents > cert.cap_cents) return fail('C5', 'OVER_CAP');
  const limit = merchantLimit(inp.policy, inp.merchant.merchant_id);
  if (limit !== null && tag.amount_cents > limit) return fail('C5', 'OVER_LIMIT');

  // C6: chain checks against every stored tag for this cert.
  if (!tagValid(tag)) return fail('C6', 'INVALID_TAG');
  const sameCert = inp.storedTags.filter((s) => s.cert_id === tag.cert_id).sort(byCounterThenHash);
  for (const stored of sameCert) {
    const rule = equivocation(stored, tag);
    if (rule) return fail('C6', rule, rule, stored);
  }
  if (sameCert.length && tag.counter <= Math.max(...sameCert.map((s) => s.counter))) {
    return fail('C6', 'COUNTER_NOT_NEW');
  }
  return { ok: true };
}

// ---- R4 OVER_CAP (server; here for vector parity) ----

export function overCap(settledTags: Tag[], caps: number[]): boolean {
  if (caps.length === 0) throw new Error('overCap needs the caps of the issued versions');
  return settledTags.length > 0 && Math.max(...settledTags.map((t) => t.cum_cents)) > Math.max(...caps);
}

// ---- R5 MERCHANT_KNEW (§9.4) ----

export interface MerchantKnew {
  clause: 'HELD_IDS' | 'PAIRED_CONTACT';
  conflict: Hex; // tag_hash of the conflicting tag x
  contactId: Hex | null; // set for clause (b)
}

type Contact = Extract<Dlog, { kind: 'CONTACT' }>;
type Accept = Extract<Dlog, { kind: 'ACCEPT' }>;

/**
 * Did merchant M knowingly accept tag z? A contact counts only when paired (both sides logged
 * the same contact_id naming each other), dated by M's own CONTACT entry.
 */
export function merchantKnew(
  z: Tag, inp: { merchantPub: Hex; tAccept: number; certTags: Tag[]; logs: Dlog[] },
): MerchantKnew | null {
  const zh = tagHash(z);
  const conflicts = inp.certTags
    .filter((x) => x.cert_id === z.cert_id && tagHash(x) !== zh && equivocation(x, z))
    .sort(byCounterThenHash);
  if (!conflicts.length) return null;

  // (a) M's own ACCEPT entry for z lists x in held_ids.
  const accepts = inp.logs.filter(
    (e): e is Accept => e.device_pub === inp.merchantPub && e.kind === 'ACCEPT' && e.tag_hash === zh,
  );
  for (const x of conflicts) {
    if (accepts.some((e) => e.held_ids.includes(tagHash(x)))) {
      return { clause: 'HELD_IDS', conflict: tagHash(x), contactId: null };
    }
  }

  // (b) a paired contact before t_accept in which x reached M.
  const mine = new Map<Hex, Contact>();
  for (const e of inp.logs) if (e.device_pub === inp.merchantPub && e.kind === 'CONTACT') mine.set(e.contact_id, e);
  const pairs: [Contact, Contact][] = [];
  for (const peer of inp.logs) {
    if (peer.kind !== 'CONTACT' || peer.peer_pub !== inp.merchantPub) continue;
    const own = mine.get(peer.contact_id);
    if (!own || own.peer_pub !== peer.device_pub || own.ts >= inp.tAccept) continue;
    pairs.push([own, peer]);
  }
  pairs.sort((p, q) => p[0].ts - q[0].ts || cmp(p[0].contact_id, q[0].contact_id));
  for (const x of conflicts) {
    const x8 = id8(tagHash(x));
    for (const [own, peer] of pairs) {
      if (peer.sent_ids.includes(x8) || own.recv_ids.includes(x8)) {
        return { clause: 'PAIRED_CONTACT', conflict: tagHash(x), contactId: own.contact_id };
      }
    }
  }
  return null;
}

// ---- R6 LOG_TAMPER (§9.5) ----

export interface LogTamper { kind: 'FORK' | 'BROKEN_LINK'; seq: number }

/**
 * One device's entries: the first fork or broken link by ascending seq. A missing seq is not
 * tampering (entries arrive out of order); links are checked only where the previous entry is known.
 */
export function logTamper(entries: Dlog[]): LogTamper | null {
  const bySeq = new Map<number, Map<Hex, Dlog>>();
  const devices = new Set<Hex>();
  for (const e of entries) {
    devices.add(e.device_pub);
    if (!bySeq.has(e.seq)) bySeq.set(e.seq, new Map());
    bySeq.get(e.seq)!.set(dlogHash(e), e);
  }
  if (devices.size > 1) throw new Error('logTamper checks one device at a time');
  if (devices.size === 0) return null;
  const devicePub = [...devices][0];
  for (const seq of [...bySeq.keys()].sort((a, b) => a - b)) {
    const here = bySeq.get(seq)!;
    if (here.size > 1) return { kind: 'FORK', seq };
    const entry = [...here.values()][0];
    if (seq === 1) {
      if (entry.prev_hash !== dlogGenesis(devicePub)) return { kind: 'BROKEN_LINK', seq };
    } else if (bySeq.has(seq - 1) && !bySeq.get(seq - 1)!.has(entry.prev_hash)) {
      return { kind: 'BROKEN_LINK', seq };
    }
  }
  return null;
}
